"""
plot_success_prob.py は total_events ステップのマルコフ連鎖で「継続的捕獲」（生存）確率を描画する。

本スクリプトは同一の窓モデルにおいて、各時点で窓内ブロックが独立に確率 alpha で攻撃者由来とみなすとき、
**一度の観測**で多数派条件（popcount >= ceil(W/2)）を満たす確率を描画する。
（連続スクリプトの生存計算の初期分布を正規化する前の質量の合計と一致する。）
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# 単一ステップ確率は評価が軽いので密にサンプルする（adaptive_sample だと区間が直線に見える）
DEFAULT_N_ALPHA = 4097


def get_popcounts(window_size):
    return np.array([bin(i).count("1") for i in range(1 << window_size)])


def single_capture_probability(alpha, window_size):
    """窓が i.i.d. Bernoulli(alpha) のとき、単一時点で多数派捕獲とみなされる確率。

    alpha はスカラーまたは numpy 配列（ブロードキャスト可）。
    """
    a = np.asarray(alpha, dtype=np.float64)
    scalar = a.ndim == 0
    a1 = np.atleast_1d(a)

    num_states = 1 << window_size
    min_a = (window_size + 1) // 2
    popcounts = get_popcounts(window_size)
    valid_mask = popcounts >= min_a
    k = popcounts.astype(np.float64)

    aa = a1.reshape(-1, 1)
    kk = k.reshape(1, -1)
    probs = (aa**kk) * ((1.0 - aa) ** (window_size - kk))
    probs[:, ~valid_mask] = 0.0
    out = probs.sum(axis=1)
    out = np.where(a1 <= 0.0, 0.0, out)
    out = np.where(a1 >= 1.0, 1.0, out)

    if scalar:
        return float(out[0])
    return out.reshape(a.shape)


def run_simulation(n_alpha=DEFAULT_N_ALPHA, windows=None):
    if windows is None:
        windows = [17, 15, 13, 11, 9, 7, 5, 3, 1]
    plt.figure(figsize=(12, 7))

    xs = np.linspace(0.0, 0.5, n_alpha)

    for w in windows:
        print(f"Processing WINDOW={w}...")
        ys = single_capture_probability(xs, w)
        plt.plot(
            xs,
            ys,
            linewidth=1.6,
            label=f"Window={w}",
        )

    plt.yscale("linear")
    plt.ylim(-0.05, 1.05)
    plt.xlim(0.0, 0.5)

    plt.xlabel("Attacker hashrate (without selfish mining)")
    plt.ylabel("Single-step capture probability")
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.legend()
    out_path = Path(__file__).resolve().parents[1] / "results" / "temporal_success_prob.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    print(f"Saved: {out_path}")
    plt.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Plot single-step (one-time) capture probability vs hashrate."
    )
    p.add_argument(
        "--n-alpha",
        type=int,
        default=DEFAULT_N_ALPHA,
        help="横軸 [0,0.5] を等間隔に何点で評価するか（既定: %(default)s）",
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
    run_simulation(n_alpha=args.n_alpha, windows=win_list)
