# uv run scripts/plot_alpha_probability_curve.py --samples 40 --target 0.5 --N 2016
# uv run scripts/plot_alpha_probability_curve.py --samples 40 --target 0.99 --N 2015
# uv run scripts/plot_alpha_probability_curve.py --samples 40 --target 0.9 --N 2015
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable, Optional, Tuple
import sys
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

import numpy as np

# 同じディレクトリにある calc.py を import できるようにパスを追加
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.append(str(THIS_DIR))

from calc_window_success_probability import prob_always_at_least_6_As_in_last_11


def _pool_worker_init() -> None:
    # 各 worker プロセス起動時に1回呼ばれる
    try:
        start_method = mp.get_start_method()
    except RuntimeError:
        start_method = "unknown"
    print(
        f"[spawn-debug] worker started pid={os.getpid()} ppid={os.getppid()} start_method={start_method}",
        file=sys.stderr,
    )


def _alpha_times_prob_worker(args: Tuple[int, float]) -> float:
    """
    multiprocessing (spawn) でも pickle できるよう、トップレベル関数にする。
    戻り値は alpha * P(N, alpha)。
    """
    N, a = args
    return a * prob_always_at_least_6_As_in_last_11(N, float(a))


def _compute_alpha_times_prob(
    N: int,
    alphas: Iterable[float],
    *,
    parallel: bool,
    workers: Optional[int],
    chunksize: Optional[int] = None,
) -> np.ndarray:
    alphas_list = [float(a) for a in alphas]
    if not parallel or len(alphas_list) <= 1:
        return np.array([_alpha_times_prob_worker((N, a)) for a in alphas_list])

    max_workers = workers if workers is not None else (os.cpu_count() or 1)
    # chunksize を指定しないとオーバーヘッドが目立つことがあるため、適度にまとめる
    if chunksize is None:
        chunksize = max(1, len(alphas_list) // (max_workers * 4) or 1)

    try:
        try:
            start_method = mp.get_start_method()
        except RuntimeError:
            start_method = "unknown"
        print(
            f"[spawn-debug] creating pool max_workers={max_workers} start_method={start_method}",
            file=sys.stderr,
        )
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_pool_worker_init,
        ) as ex:
            vals = list(
                ex.map(
                    _alpha_times_prob_worker,
                    ((N, a) for a in alphas_list),
                    chunksize=chunksize,
                )
            )
        return np.array(vals)
    except Exception as e:
        # sandbox 等でプロセス並列が禁止されている場合に落ちないようフォールバック
        print(
            f"警告: プロセス並列が利用できないため逐次計算にフォールバックします: {e}",
            file=sys.stderr,
        )
        return np.array([_alpha_times_prob_worker((N, a)) for a in alphas_list])


def adaptive_sample_alpha_values(
    N: int,
    num_samples: int = 41,
    alpha_min: float = 0.0,
    alpha_max: float = 1.0,
    coarse_points: int = 21,
    weight_floor: float = 1e-6,
    *,
    parallel: bool = True,
    workers: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    変化が大きい区間により多く点を割くような alpha サンプリング。
    1) 粗いグリッドで値を取り、区間勾配を重みとしてCDFを作る
    2) 重みに沿って num_samples 個の alpha を再サンプリング
    """
    coarse_alphas = np.linspace(alpha_min, alpha_max, coarse_points)
    coarse_vals = _compute_alpha_times_prob(
        N, coarse_alphas, parallel=parallel, workers=workers
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

    vals = _compute_alpha_times_prob(N, alphas, parallel=parallel, workers=workers)
    return alphas, vals


def interpolate_curve(
    alphas: np.ndarray, vals: np.ndarray, dense_points: int = 400
) -> Tuple[np.ndarray, np.ndarray]:
    """1次補間で滑らかな描画用サンプルを生成する。"""
    dense_alphas = np.linspace(alphas.min(), alphas.max(), dense_points)
    dense_vals = np.interp(dense_alphas, alphas, vals)
    return dense_alphas, dense_vals


def plot_alpha_prob(
    N: int,
    num_samples: int,
    target: float,
    *,
    parallel: bool,
    workers: Optional[int],
) -> None:
    alphas, vals = adaptive_sample_alpha_values(
        N, num_samples=num_samples, parallel=parallel, workers=workers
    )
    dense_a, dense_v = interpolate_curve(alphas, vals)

    # dense_v (= alpha * P(N, alpha)) が target に最も近い alpha を求める
    best_idx = int(np.argmin(np.abs(dense_v - target)))
    best_alpha = float(dense_a[best_idx])
    best_val = float(dense_v[best_idx])
    print(
        f"alpha * P(N={N}, alpha) が {target} に最も近い: "
        f"alpha={best_alpha:.6g}, value={best_val:.6g}"
    )

    # matplotlib は子プロセスで読み込ませたくないので遅延 import
    import matplotlib.pyplot as plt

    plt.figure(figsize=(6, 4))
    plt.plot(dense_a, dense_v, label="interpolated alpha * P(N, alpha)")
    plt.scatter(alphas, vals, s=12, c="orange", label="samples")
    plt.axvline(best_alpha, color="tab:green", linestyle="--", linewidth=1.2, alpha=0.8)
    plt.axhline(target, color="gray", linestyle=":", linewidth=1.2, alpha=0.8)
    plt.scatter([best_alpha], [best_val], s=36, c="tab:green", zorder=5)
    plt.text(
        0.02,
        0.98,
        f"closest to {target}:\nalpha={best_alpha:.6g}\nvalue={best_val:.6g}",
        transform=plt.gca().transAxes,
        va="top",
        ha="left",
        fontsize=10,
        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.85),
    )
    plt.title(f"alpha * P(N={N}, alpha)")
    plt.xlabel("alpha")
    plt.ylabel(f"alpha * P(N={N}, alpha)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()


def main() -> None:
    default_workers = os.cpu_count() or 1
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
    parser.add_argument(
        "--target",
        type=float,
        default=0.5,
        help="最も近づけたい値 (default: 0.5)",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="サンプル計算を並列化しない（デバッグ用）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers,
        help="並列ワーカ数（default: 論理CPU数）",
    )
    args = parser.parse_args()

    plot_alpha_prob(
        args.N,
        args.samples,
        args.target,
        parallel=not args.no_parallel,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()