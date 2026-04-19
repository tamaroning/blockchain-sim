import argparse
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from numba import njit

# 環境変数 TIMEWARP_TOTAL_EVENTS で上書き可（プレビュー用に小さくすると速い）
TOTAL_EVENTS = int(os.environ.get("TIMEWARP_TOTAL_EVENTS", "2016"))

# adaptive_sample 用。大きいと区間が線形に見えるほど再帰が止まり点が極端に少なくなる
# （例: tol=0.1 かつ Window=11 だと点が 5 個程度になり折れ線が直線に見える）。Numba とは無関係。
DEFAULT_SAMPLE_TOL = 0.03

def get_popcounts(window_size):
    return np.array([bin(i).count('1') for i in range(1 << window_size)])

# 窓ごとに idx / mask は α に依存しないので再利用（毎回の巨大配列構築を省略）
_WINDOW_STRUCT = {}

def _window_struct(window_size):
    if window_size not in _WINDOW_STRUCT:
        num_states = 1 << window_size
        min_a = (window_size + 1) // 2
        popcounts = get_popcounts(window_size)
        valid_mask = popcounts >= min_a
        idx = np.arange(num_states, dtype=np.intp)
        idx_a = ((idx << 1) | 1) & (num_states - 1)
        idx_b = (idx << 1) & (num_states - 1)
        mask_a = valid_mask[idx_a]
        mask_b = valid_mask[idx_b]
        _WINDOW_STRUCT[window_size] = (
            num_states,
            popcounts,
            valid_mask,
            np.ascontiguousarray(idx_a, dtype=np.int64),
            np.ascontiguousarray(idx_b, dtype=np.int64),
            np.ascontiguousarray(mask_a),
            np.ascontiguousarray(mask_b),
        )
    return _WINDOW_STRUCT[window_size]


# cache=False: スクリプトを直接実行すると __main__ / <dynamic> 名でキャッシュが保存され、
# 読み込み時に ModuleNotFoundError: No module named '<dynamic>' になることがある。
@njit(cache=False)
def _survival_probability_numba(
    probs,
    nxt,
    idx_a,
    idx_b,
    mask_a,
    mask_b,
    window_size,
    total_events,
    alpha,
):
    num_states = probs.shape[0]
    oma = 1.0 - alpha
    for _ in range(window_size, total_events):
        nxt.fill(0.0)
        for s in range(num_states):
            if mask_a[s]:
                nxt[idx_a[s]] += probs[s] * alpha
            if mask_b[s]:
                nxt[idx_b[s]] += probs[s] * oma
        probs, nxt = nxt, probs
        sm = 0.0
        for s in range(num_states):
            sm += probs[s]
        if sm < 1e-12:
            return 0.0
    sm = 0.0
    for s in range(num_states):
        sm += probs[s]
    return sm


def survival_probability_fast(alpha, window_size, total_events=TOTAL_EVENTS):
    if alpha <= 0.0: return 0.0
    if alpha >= 1.0: return 1.0

    (
        num_states,
        popcounts,
        valid_mask,
        idx_a_nb,
        idx_b_nb,
        mask_a_nb,
        mask_b_nb,
    ) = _window_struct(window_size)

    probs = np.zeros(num_states, dtype=np.float64)
    nxt = np.zeros(num_states, dtype=np.float64)
    k = popcounts
    probs[:] = (alpha ** k) * ((1 - alpha) ** (window_size - k))
    probs[~valid_mask] = 0.0

    if np.sum(probs) == 0: return 0.0

    return float(
        _survival_probability_numba(
            probs,
            nxt,
            idx_a_nb,
            idx_b_nb,
            mask_a_nb,
            mask_b_nb,
            window_size,
            total_events,
            alpha,
        )
    )

def adaptive_sample(f, x0, x1, y0, y1, tol=0.03, max_depth=5, depth=0):
    mid_x = (x0 + x1) / 2
    mid_y = f(mid_x)
    # 線形補間とのズレがtol未満なら分割終了
    # 元実装は depth > 5 で打ち切り（depth==6 で終了）
    if depth > max_depth or abs(mid_y - (y0 + y1) / 2) < tol:
        return [(mid_x, mid_y)]
    return (adaptive_sample(f, x0, mid_x, y0, mid_y, tol, max_depth, depth + 1) +
            [(mid_x, mid_y)] +
            adaptive_sample(f, mid_x, x1, mid_y, y1, tol, max_depth, depth + 1))

def run_simulation(
    total_events=TOTAL_EVENTS,
    sample_tol=DEFAULT_SAMPLE_TOL,
    sample_max_depth=5,
    windows=None,
):
    if windows is None:
        windows = [17, 15, 13, 11, 9, 7, 5, 3, 1]
    plt.figure(figsize=(12, 7))

    for w in windows:
        print(f"Processing WINDOW={w}...")
        f = lambda a, ww=w: survival_probability_fast(a, ww, total_events=total_events)

        # アルファ 0.5〜1.0 の範囲を調査
        xs_base = [0.5, 1.0]
        ys_base = [f(0.5), 1.0]

        samples = [(xs_base[0], ys_base[0])] + \
                  adaptive_sample(f, xs_base[0], xs_base[1], ys_base[0], ys_base[1], tol=sample_tol, max_depth=sample_max_depth) + \
                  [(xs_base[1], ys_base[1])]

        samples.sort()
        xs, ys = zip(*samples)

        plt.plot(xs, ys, marker='.', markersize=4, label=f'Window={w} (points={len(xs)})')

    # --- グラフ設定の変更点 ---
    plt.yscale('linear')      # リニアスケールに設定
    plt.ylim(-0.05, 1.05)     # 0と1が綺麗に見えるようにマージンを調整
    plt.xlim(0.7, 1.0)        # alpha=0.5以下の意味は薄いため絞り込み

    plt.xlabel("Attacker hashrate (without selfish mining)")
    plt.ylabel("Attack success rate")
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.legend()
    out_path = Path(__file__).resolve().parents[1] / "results" / "success_prob.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    print(f"Saved: {out_path}")
    plt.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Plot attack success probability vs hashrate.")
    p.add_argument(
        "--total-events",
        type=int,
        default=TOTAL_EVENTS,
        help="Markov ステップ数（既定: %(default)s。プレビューは 256 などにすると大幅に速い）",
    )
    p.add_argument(
        "--sample-tol",
        type=float,
        default=DEFAULT_SAMPLE_TOL,
        help="adaptive_sample の許容誤差（大きいほど点が少なく速い。直線っぽく見えたら下げる）",
    )
    p.add_argument(
        "--sample-max-depth",
        type=int,
        default=5,
        help="adaptive_sample の再帰の深さ上限（小さいほど速い）",
    )
    p.add_argument(
        "--windows",
        type=str,
        default="",
        help="カンマ区切り（例: 11,9,7）。空なら全窓",
    )
    args = p.parse_args()
    win_list = None
    if args.windows.strip():
        win_list = [int(x.strip()) for x in args.windows.split(",") if x.strip()]
    run_simulation(
        total_events=args.total_events,
        sample_tol=args.sample_tol,
        sample_max_depth=args.sample_max_depth,
        windows=win_list,
    )
