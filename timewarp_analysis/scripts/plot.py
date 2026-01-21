from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple
import sys

import matplotlib.pyplot as plt
import numpy as np

# 同じディレクトリにある calc.py を import できるようにパスを追加
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.append(str(THIS_DIR))

from calc import prob_always_at_least_6_As_in_last_11


def adaptive_sample_alpha_values(
    N: int,
    num_samples: int = 41,
    alpha_min: float = 0.0,
    alpha_max: float = 1.0,
    coarse_points: int = 21,
    weight_floor: float = 1e-6,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    変化が大きい区間により多く点を割くような alpha サンプリング。
    1) 粗いグリッドで値を取り、区間勾配を重みとしてCDFを作る
    2) 重みに沿って num_samples 個の alpha を再サンプリング
    """
    coarse_alphas = np.linspace(alpha_min, alpha_max, coarse_points)
    coarse_vals = np.array(
        [a * prob_always_at_least_6_As_in_last_11(N, float(a)) for a in coarse_alphas]
    )

    # 区間ごとの絶対勾配を重みとする
    slopes = np.abs(np.diff(coarse_vals)) / np.diff(coarse_alphas)
    interval_w = np.maximum(slopes, weight_floor)
    cum_w = np.concatenate([[0.0], np.cumsum(interval_w)])
    total_w = cum_w[-1]

    # 重みに基づく等分割で alpha を再配置
    targets = np.linspace(0.0, total_w, num_samples)
    alphas = np.empty(num_samples)
    for i, t in enumerate(targets):
        idx = np.searchsorted(cum_w, t, side="right") - 1
        idx = min(max(idx, 0), len(interval_w) - 1)
        w = interval_w[idx]
        span = coarse_alphas[idx + 1] - coarse_alphas[idx]
        if w <= 0:
            frac = 0.5  # 念のため
        else:
            frac = (t - cum_w[idx]) / w
        alphas[i] = coarse_alphas[idx] + frac * span

    vals = np.array(
        [a * prob_always_at_least_6_As_in_last_11(N, float(a)) for a in alphas]
    )
    return alphas, vals


def interpolate_curve(
    alphas: np.ndarray, vals: np.ndarray, dense_points: int = 400
) -> Tuple[np.ndarray, np.ndarray]:
    """1次補間で滑らかな描画用サンプルを生成する。"""
    dense_alphas = np.linspace(alphas.min(), alphas.max(), dense_points)
    dense_vals = np.interp(dense_alphas, alphas, vals)
    return dense_alphas, dense_vals


def plot_alpha_prob(N: int, num_samples: int) -> None:
    alphas, vals = adaptive_sample_alpha_values(N, num_samples=num_samples)
    dense_a, dense_v = interpolate_curve(alphas, vals)

    plt.figure(figsize=(6, 4))
    plt.plot(dense_a, dense_v, label="interpolated alpha * P(N, alpha)")
    plt.scatter(alphas, vals, s=12, c="orange", label="samples")
    plt.title(f"alpha * P(N={N}, alpha)")
    plt.xlabel("alpha")
    plt.ylabel(f"alpha * P(N={N}, alpha)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="alpha * P(N, alpha) をサンプル計算し、補間してプロットする"
    )
    parser.add_argument(
        "--N",
        type=int,
        default=2015,
        help="試行回数 N (default: 2015)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=41,
        help="alpha のサンプル数 (default: 41)",
    )
    args = parser.parse_args()

    plot_alpha_prob(args.N, args.samples)


if __name__ == "__main__":
    main()