#!/usr/bin/env python3
"""
3 つの等しい hashrate の honest ノードで stale block rate を計測する。

伝播遅延 Δ(ms) を固定し、Bitcoin `Fixed` genesis 難易度 D=1 のときネットワーク平均ブロック間隔を
「Poisson レース」の近似 ``T_mean ≈ D·2^32 / H_tot`` とみなして総 hashrate H_tot を選び、
無次元 ``λΔ = Δ / T_mean`` が ``10^k``（k は LAMBDA_DELTA_EXPS）になるように λ を調整する。

各条件で複数シード実行し、stale_rate の中央値を CSV に書く。

CSV 列::
  inverse_lambda_delta, stale_rate

- inverse_lambda_delta = 1 / (λΔ) = ``10^(-k)``
- stale_rate: 各 run の stale_rate の中央値

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
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = next(
    c for c in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents] if (c / "Cargo.toml").exists()
)
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import ensure_release_binary, write_profile_json

STALE_RATE_DIR = SCRIPT_PATH.parent.parent
RESULTS_DIR = STALE_RATE_DIR / "results"
PROFILES_DIR = STALE_RATE_DIR / "profiles" / "generated"
TMP_METRICS_DIR = RESULTS_DIR / "_metrics_tmp_n_honest"

# λΔ = 10^k となる k の列（コメント仕様）
LAMBDA_DELTA_EXPS: tuple[float, ...] = (
    -2.5,
    -2.0,
    -1.5,
    -1.0,
    -0.5,
    0.0,
    0.5,
    1.0,
    1.5,
    2.0,
)
BITCOIN_D_TIMES_2_32 = 2.0**32


def total_hashrate_for_lambda_delta_exp(
    *, delay_ms: float, exp: float, d_fixed: float = 1.0
) -> int:
    """λΔ = 10^exp としたいときの H_tot（近似式用）。最低 3（ノード 1 ずつ）。"""
    lambda_delta = 10.0**exp
    t_mean_ms = delay_ms / lambda_delta
    if t_mean_ms <= 0:
        raise ValueError("delay_ms / lambda_delta が正である必要があります")
    h = int(round(d_fixed * BITCOIN_D_TIMES_2_32 / t_mean_ms))
    return max(3, h)


def split_three_equal(total: int) -> tuple[int, int, int]:
    base = total // 3
    rem = total % 3
    a = base + (1 if rem > 0 else 0)
    b = base + (1 if rem > 1 else 0)
    c = total - a - b
    return a, b, c


def build_honest_profile(*, total_hashrate: int, profile_path: Path) -> Path:
    h0, h1, h2 = split_three_equal(total_hashrate)
    nodes: list[dict[str, Any]] = [
        {"hashrate": h0, "strategy": {"type": "honest"}},
        {"hashrate": h1, "strategy": {"type": "honest"}},
        {"hashrate": h2, "strategy": {"type": "honest"}},
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
    exp: float,
    runs: int,
    seed_start: int,
    end_round: int,
    delay_ms: int,
    protocol: str,
) -> tuple[float, float]:
    """戻り値: (inverse_lambda_delta, median stale_rate)"""
    h_tot = total_hashrate_for_lambda_delta_exp(delay_ms=float(delay_ms), exp=exp)
    profile_path = PROFILES_DIR / f"n_honest_exp_{exp:g}.json"
    build_honest_profile(total_hashrate=h_tot, profile_path=profile_path)

    rates: list[float] = []
    for i in range(runs):
        seed = seed_start + i
        mpath = TMP_METRICS_DIR / f"exp_{exp:g}_run{i}_seed{seed}.csv"
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
    return inverse_ld, statistics.median(rates)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="3 honest ノード・等 hashrate で stale block rate sweep"
    )
    parser.add_argument("--runs", type=int, default=10, help="各条件のシード反復回数")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--end-round", type=int, default=100)
    parser.add_argument("--delay-ms", type=int, default=600, help="伝播遅延 Δ（ms）")
    parser.add_argument("--protocol", type=str, default="bitcoin")
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR / "N_honest_stale_rate.csv",
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

    rows: list[tuple[float, float]] = []

    for exp in LAMBDA_DELTA_EXPS:
        inv_ld, median_sr = measure_group(
            binary_path=binary_path,
            exp=exp,
            runs=args.runs,
            seed_start=args.seed_start,
            end_round=args.end_round,
            delay_ms=args.delay_ms,
            protocol=args.protocol,
        )
        rows.append((inv_ld, median_sr))
        print(f"λΔ=10^{exp:g}  1/(λΔ)={inv_ld:g}  median stale_rate={median_sr:.6f}")

    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["inverse_lambda_delta", "stale_rate"])
        for inv_ld, sr in rows:
            w.writerow([inv_ld, sr])

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
