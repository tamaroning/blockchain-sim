"""
plot_temporal_success_prob.py の selfish mining 版。
名目ハッシュレート alpha を get_effective_alpha で実効 alpha に変換してから、
単一時点の多数派捕獲確率（二項の尾確率）を描画する。

plot_success_prob_selfish.py と同様、横軸は名目 alpha、gamma は実効 alpha の式に用いる。
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DEFAULT_N_ALPHA = 4097
DEFAULT_GAMMA = 0.5


def get_effective_alpha(alpha, gamma=0.5):
    """
    Selfish Mining 実行時の実効ハッシュレート割合（名目 alpha から）。
    alpha >= 0.5 の場合はネットワークを支配できるため 1.0 とする。
    alpha はスカラーまたは numpy 配列。
    """
    a = np.asarray(alpha, dtype=np.float64)
    scalar = a.ndim == 0
    a1 = np.atleast_1d(a)

    num = a1 * (1.0 - a1) ** 2 * (4.0 * a1 + gamma * (1.0 - 2.0 * a1)) - a1**3
    den = 1.0 - a1 * (1.0 + (2.0 - a1) * a1)
    eff = num / den
    eff = np.where(a1 <= 0.0, 0.0, eff)
    eff = np.where(a1 >= 0.5, 1.0, eff)

    if scalar:
        return float(eff[0])
    return eff.reshape(a.shape)


def get_popcounts(window_size):
    return np.array([bin(i).count("1") for i in range(1 << window_size)])


def single_capture_probability(alpha, window_size):
    """窓が i.i.d. Bernoulli(alpha) のとき、単一時点で多数派捕獲とみなされる確率。"""
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


def run_simulation(
    n_alpha=DEFAULT_N_ALPHA,
    gamma=DEFAULT_GAMMA,
    windows=None,
    x_min=0.0,
    x_max=0.5,
    xlim_lo=0.0,
    xlim_hi=0.5,
):
    if windows is None:
        windows = [13, 11, 9, 7, 5]
    plt.figure(figsize=(12, 7))

    xs = np.linspace(x_min, x_max, n_alpha)

    for w in windows:
        print(f"Processing WINDOW={w}...")
        alpha_eff = get_effective_alpha(xs, gamma=gamma)
        ys = single_capture_probability(alpha_eff, w)
        plt.plot(xs, ys, linewidth=1.6, label=f"Window={w}")

    plt.yscale("linear")
    plt.ylim(-0.05, 1.05)
    plt.xlim(xlim_lo, xlim_hi)

    plt.xlabel("Attacker Nominal Hashrate (alpha)")
    plt.ylabel("Single-step capture probability (with Selfish Mining)")
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.legend()
    out_path = Path(__file__).resolve().parents[1] / "results" / "temporal_success_prob_selfish.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    print(f"Saved: {out_path}")
    plt.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Plot single-step capture probability vs nominal hashrate (selfish mining)."
    )
    p.add_argument(
        "--n-alpha",
        type=int,
        default=DEFAULT_N_ALPHA,
        help="横軸 [x_min,x_max] を等間隔に何点で評価するか（既定: %(default)s）",
    )
    p.add_argument(
        "--gamma",
        type=float,
        default=DEFAULT_GAMMA,
        help="get_effective_alpha の gamma（既定: %(default)s）",
    )
    p.add_argument(
        "--x-min",
        type=float,
        default=0.0,
        help="名目 alpha のサンプル下限",
    )
    p.add_argument(
        "--x-max",
        type=float,
        default=0.5,
        help="名目 alpha のサンプル上限（selfish で意味のある範囲の上限）",
    )
    p.add_argument(
        "--xlim-lo",
        type=float,
        default=0.0,
        help="表示する横軸の下限",
    )
    p.add_argument(
        "--xlim-hi",
        type=float,
        default=0.5,
        help="表示する横軸の上限",
    )
    p.add_argument(
        "--windows",
        type=str,
        default="",
        help="カンマ区切り（例: 11,9,7）。空なら既定の窓一覧",
    )
    args = p.parse_args()
    win_list = None
    if args.windows.strip():
        win_list = [int(x.strip()) for x in args.windows.split(",") if x.strip()]
    run_simulation(
        n_alpha=args.n_alpha,
        gamma=args.gamma,
        windows=win_list,
        x_min=args.x_min,
        x_max=args.x_max,
        xlim_lo=args.xlim_lo,
        xlim_hi=args.xlim_hi,
    )
