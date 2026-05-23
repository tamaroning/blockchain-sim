#!/usr/bin/env python3
"""
stale block rate を計測し `results/stale_rate.csv` を生成する。

2 ノード（攻撃者 + honest 1）。攻撃者戦略は timewarp / selfish_mining。
名目ハッシュレート割合 alpha と無次元 λΔ をスイープする。

伝播遅延 Δ(ms) を固定し、Bitcoin `Fixed` genesis 難易度 D=1 のときネットワーク平均ブロック間隔を
「Poisson レース」の近似 ``T_mean ≈ D·2^32 / H_tot`` とみなして総 hashrate H_tot を選び、
無次元 ``λΔ = Δ / T_mean`` が ``10^k``（k は LAMBDA_DELTA_EXPS）になるように λ を調整する。

CSV 出力列::
  strategy, alpha, inverse_lambda_delta, stale_rate

- strategy は ``timewarp`` または ``selfish_mining``（プロファイル上の type は ``selfish``）
- inverse_lambda_delta = 1 / (λΔ) = ``10^(-k)``
- stale_rate は各条件で複数シード実行し、シミュレータが書く `stale_rate` の中央値

前提: Bitcoin のみ（`--genesis-difficulty-mode fixed`）。
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

StrategyName = Literal["timewarp", "selfish_mining"]

STRATEGIES: tuple[StrategyName, ...] = ("timewarp", "selfish_mining")
# プロファイル JSON の strategy.type（CSV の strategy 名とは別）
PROFILE_TYPES: dict[StrategyName, str] = {
    "timewarp": "timewarp",
    "selfish_mining": "selfish",
}

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = next(
    c for c in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents] if (c / "Cargo.toml").exists()
)
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import ensure_release_binary, write_profile_json

STALE_RATE_DIR = SCRIPT_PATH.parent.parent
RESULTS_DIR = STALE_RATE_DIR / "results"
PROFILES_DIR = STALE_RATE_DIR / "profiles" / "generated"
TMP_METRICS_DIR = RESULTS_DIR / "_metrics_tmp"

# λΔ = 10^k となる k の列
LAMBDA_DELTA_EXPS: tuple[float, ...] = (-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0)
# 攻撃者の名目ハッシュレート割合 alpha（timewarp ノード / 総 hashrate）
ALPHAS: tuple[float, ...] = (0.1, 0.3, 0.5, 0.7, 0.9)
BITCOIN_D_TIMES_2_32 = 2.0**32


def total_hashrate_for_lambda_delta_exp(
    *, delay_ms: float, exp: float, d_fixed: float = 1.0
) -> int:
    """λΔ = 10^exp としたいときの H_tot（近似式用）。2 ノード各 1 以上になるよう最低 2。"""
    lambda_delta = 10.0**exp
    t_mean_ms = delay_ms / lambda_delta
    if t_mean_ms <= 0:
        raise ValueError("delay_ms / lambda_delta が正である必要があります")
    h = int(round(d_fixed * BITCOIN_D_TIMES_2_32 / t_mean_ms))
    return max(2, h)


def split_two_by_alpha(total: int, alpha: float) -> tuple[int, int]:
    """攻撃者 alpha、残り honest（2 ノード）。各ノード hashrate は最低 1。"""
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha は (0, 1) である必要があります: {alpha}")
    attacker = int(round(total * alpha))
    attacker = max(1, min(attacker, total - 1))
    honest = total - attacker
    return attacker, honest


def build_profile(
    *,
    strategy: StrategyName,
    alpha: float,
    total_hashrate: int,
    profile_path: Path,
) -> Path:
    attacker_hr, honest_hr = split_two_by_alpha(total_hashrate, alpha)
    profile_type = PROFILE_TYPES[strategy]
    nodes: list[dict[str, Any]] = [
        {"hashrate": attacker_hr, "strategy": {"type": profile_type}},
        {"hashrate": honest_hr, "strategy": {"type": "honest"}},
    ]
    return write_profile_json({"nodes": nodes}, profile_path)


def run_simulation(
    *,
    binary_path: Path,
    profile_path: Path,
    end_round: int,
    delay_ms: int,
    protocol: str,
    metrics_csv: Path,
    seed: int,
) -> None:
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(binary_path),
        f"--end-round={end_round}",
        f"--protocol={protocol}",
        f"--profile={profile_path}",
        f"--delay={delay_ms}",
        f"--seed={seed}",
        "--genesis-difficulty-mode=fixed",
        f"--metrics={metrics_csv}",
    ]
    env = {**os.environ, "RUST_LOG": "error"}
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"シミュレーション失敗 (exit={result.returncode})\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def read_stale_rate(metrics_csv: Path) -> float:
    with metrics_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
    if row is None or "stale_rate" not in row:
        raise ValueError(f"metrics CSV が不正です: {metrics_csv}")
    return float(row["stale_rate"])


def measure_group(
    *,
    binary_path: Path,
    strategy: StrategyName,
    alpha: float,
    exp: float,
    runs: int,
    seed_start: int,
    end_round: int,
    delay_ms: int,
    protocol: str,
) -> tuple[float, float, float]:
    """戻り値: (alpha, inverse_lambda_delta, median stale_rate)"""
    h_tot = total_hashrate_for_lambda_delta_exp(delay_ms=float(delay_ms), exp=exp)
    alpha_tag = str(alpha).replace(".", "p")
    strat_slug = "selfish" if strategy == "selfish_mining" else strategy
    profile_path = PROFILES_DIR / f"{strat_slug}_alpha_{alpha_tag}_exp_{exp:g}.json"
    build_profile(
        strategy=strategy, alpha=alpha, total_hashrate=h_tot, profile_path=profile_path
    )

    rates: list[float] = []
    for i in range(runs):
        seed = seed_start + i
        mpath = (
            TMP_METRICS_DIR
            / f"{strat_slug}_alpha_{alpha_tag}_exp_{exp:g}_run{i}_seed{seed}.csv"
        )
        run_simulation(
            binary_path=binary_path,
            profile_path=profile_path,
            end_round=end_round,
            delay_ms=delay_ms,
            protocol=protocol,
            metrics_csv=mpath,
            seed=seed,
        )
        rates.append(read_stale_rate(mpath))

    inverse_ld = 1.0 / (10.0**exp)
    return alpha, inverse_ld, statistics.median(rates)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="stale block rate sweep（timewarp/selfish + honest 2 ノード、alpha × λΔ）"
    )
    parser.add_argument("--runs", type=int, default=10, help="各条件のシード反復回数")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--end-round", type=int, default=100)
    parser.add_argument("--delay-ms", type=int, default=600, help="伝播遅延 Δ（ms）。CLI 既定に合わせる")
    parser.add_argument("--protocol", type=str, default="bitcoin")
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR / "stale_rate.csv",
        help="集約 CSV の出力先",
    )
    parser.add_argument("--auto-build", action="store_true", help="release バイナリが無ければ cargo build")
    args = parser.parse_args()

    if args.protocol != "bitcoin":
        raise SystemExit("現在は Bitcoin + fixed genesis のみ対応しています")

    binary_path = ensure_release_binary(SCRIPT_PATH, auto_build=args.auto_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    TMP_METRICS_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, float, float, float]] = []

    for strategy in STRATEGIES:
        for alpha in ALPHAS:
            for exp in LAMBDA_DELTA_EXPS:
                a, inv_ld, median_sr = measure_group(
                    binary_path=binary_path,
                    strategy=strategy,
                    alpha=alpha,
                    exp=exp,
                    runs=args.runs,
                    seed_start=args.seed_start,
                    end_round=args.end_round,
                    delay_ms=args.delay_ms,
                    protocol=args.protocol,
                )
                rows.append((strategy, a, inv_ld, median_sr))
                print(
                    f"{strategy} alpha={a:g} λΔ=10^{exp:g}  1/(λΔ)={inv_ld:g}  "
                    f"median stale_rate={median_sr:.6f}"
                )

    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "alpha", "inverse_lambda_delta", "stale_rate"])
        for strat, a, inv_ld, sr in rows:
            w.writerow([strat, a, inv_ld, sr])

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
