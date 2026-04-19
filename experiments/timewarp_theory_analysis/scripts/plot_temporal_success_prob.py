"""
単一時点の多数派捕獲確率（二項の尾確率）を名目ハッシュレートに対して描画する。

- honest: 横軸を実ハッシュレート alpha として直接評価（selfish なし）。
- selfish: get_effective_alpha で実効 alpha に変換してから同じ確率を評価。
- both: 同一図に両方の曲線を重ねる（窓ごとに同色で honest / selfish を対応付け）。

--plot-max: both では各窓 W ごとに honest と selfish の点ごとの最大を追加。
  honest / selfish 単独では、各 alpha で窓集合上の最大確率を 1 本追加。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DEFAULT_N_ALPHA = 4097
DEFAULT_GAMMA = 0.5

DEFAULT_WINDOWS_HONEST = [17, 15, 13, 11, 9, 7, 5, 3, 1]
DEFAULT_WINDOWS_SELFISH = [15, 11, 7, 3]


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
    """窓が i.i.d. Bernoulli(alpha) のとき、単一時点で多数派捕獲とみなされる確率。

    alpha はスカラーまたは numpy 配列（ブロードキャスト可）。
    """
    a = np.asarray(alpha, dtype=np.float64)
    scalar = a.ndim == 0
    a1 = np.atleast_1d(a)

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


def _default_windows(mode: str) -> list[int]:
    if mode == "honest":
        return list(DEFAULT_WINDOWS_HONEST)
    if mode == "selfish":
        return list(DEFAULT_WINDOWS_SELFISH)
    return list(DEFAULT_WINDOWS_SELFISH)


def _default_output_path(mode: str) -> Path:
    base = Path(__file__).resolve().parents[1] / "results"
    if mode == "honest":
        return base / "temporal_success_prob.png"
    if mode == "selfish":
        return base / "temporal_success_prob_selfish.png"
    return base / "temporal_success_prob_compare.png"


def run_plot(
    mode: str,
    n_alpha: int = DEFAULT_N_ALPHA,
    gamma: float = DEFAULT_GAMMA,
    windows: list[int] | None = None,
    x_min: float = 0.0,
    x_max: float = 0.5,
    xlim_lo: float = 0.0,
    xlim_hi: float = 0.5,
    plot_max: bool = False,
    output: Path | None = None,
) -> Path:
    if windows is None:
        windows = _default_windows(mode)
    if not windows:
        raise ValueError("windows が空です")

    plt.figure(figsize=(12, 7))
    xs = np.linspace(x_min, x_max, n_alpha)

    # --plot-max 時は元曲線を薄くし、max 曲線を主役にする
    base_lw = 1.6
    base_alpha = 1.0
    if plot_max:
        base_lw = 0.9
        base_alpha = 0.38
    max_lw = 2.35
    max_z = 3
    base_z = 1

    if mode == "both":
        alpha_eff = get_effective_alpha(xs, gamma=gamma)
        for i, w in enumerate(windows):
            print(f"[both] Processing WINDOW={w}...")
            color = f"C{i % 10}"
            y_h = single_capture_probability(xs, w)
            y_s = single_capture_probability(alpha_eff, w)
            plt.plot(
                xs,
                y_h,
                linewidth=base_lw,
                alpha=base_alpha,
                color=color,
                zorder=base_z,
                label=f"Window={w} (honest)",
            )
            plt.plot(
                xs,
                y_s,
                linewidth=base_lw,
                linestyle=":",
                alpha=base_alpha,
                color=color,
                zorder=base_z,
                label=f"Window={w} (selfish)",
            )
            if plot_max:
                plt.plot(
                    xs,
                    np.maximum(y_h, y_s),
                    linewidth=max_lw,
                    alpha=1.0,
                    color=color,
                    zorder=max_z,
                    label=f"Window={w} max(honest,selfish)",
                )
    elif mode == "honest":
        for w in windows:
            print(f"[honest] Processing WINDOW={w}...")
            ys = single_capture_probability(xs, w)
            plt.plot(
                xs,
                ys,
                linewidth=base_lw,
                alpha=base_alpha,
                zorder=base_z,
                label=f"Window={w}",
            )
        if plot_max:
            stack = np.stack([single_capture_probability(xs, w) for w in windows], axis=0)
            plt.plot(
                xs,
                stack.max(axis=0),
                linewidth=max_lw,
                alpha=1.0,
                color="C0",
                zorder=max_z,
                label="max over windows (honest)",
            )
    else:
        alpha_eff = get_effective_alpha(xs, gamma=gamma)
        for w in windows:
            print(f"[selfish] Processing WINDOW={w}...")
            ys = single_capture_probability(alpha_eff, w)
            plt.plot(
                xs,
                ys,
                linewidth=base_lw,
                alpha=base_alpha,
                zorder=base_z,
                label=f"Window={w}",
            )
        if plot_max:
            stack = np.stack(
                [single_capture_probability(alpha_eff, w) for w in windows],
                axis=0,
            )
            plt.plot(
                xs,
                stack.max(axis=0),
                linewidth=max_lw,
                alpha=1.0,
                color="C0",
                zorder=max_z,
                label="max over windows (selfish)",
            )

    plt.yscale("linear")
    plt.ylim(-0.05, 1.05)
    plt.xlim(xlim_lo, xlim_hi)

    if mode == "honest":
        plt.xlabel("Attacker hashrate (without selfish mining)")
    elif mode == "selfish":
        plt.xlabel("Attacker Nominal Hashrate (alpha)")
    else:
        plt.xlabel(
            "Attacker nominal hashrate (alpha); honest curves use nominal = true hashrate"
        )

    plt.ylabel("Single-step capture probability")
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.legend()
    out_path = output if output is not None else _default_output_path(mode)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    print(f"Saved: {out_path}")
    plt.close()
    return out_path


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="単一時点の多数派捕獲確率をプロット（honest / selfish / 比較）。"
    )
    p.add_argument(
        "--mode",
        choices=("honest", "selfish", "both"),
        default="honest",
        help="honest: 実 alpha 直評価 / selfish: 実効 alpha / both: 同一図で両方",
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
        help="get_effective_alpha の gamma（selfish / both で使用、既定: %(default)s）",
    )
    p.add_argument(
        "--x-min",
        type=float,
        default=0.0,
        help="横軸サンプル下限",
    )
    p.add_argument(
        "--x-max",
        type=float,
        default=0.5,
        help="横軸サンプル上限",
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
        help="カンマ区切り（例: 11,9,7）。空ならモード別の既定窓",
    )
    p.add_argument(
        "--plot-max",
        action="store_true",
        help="both: 各窓ごとに max(honest,selfish) を追加 / honest・selfish 単独: 窓間の最大を 1 本追加",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力 PNG パス（未指定時はモード別の既定ファイル名）",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_argparser().parse_args(argv)
    win_list: list[int] | None = None
    if args.windows.strip():
        win_list = [int(x.strip()) for x in args.windows.split(",") if x.strip()]
    run_plot(
        mode=args.mode,
        n_alpha=args.n_alpha,
        gamma=args.gamma,
        windows=win_list,
        x_min=args.x_min,
        x_max=args.x_max,
        xlim_lo=args.xlim_lo,
        xlim_hi=args.xlim_hi,
        plot_max=args.plot_max,
        output=args.output,
    )


if __name__ == "__main__":
    main()
