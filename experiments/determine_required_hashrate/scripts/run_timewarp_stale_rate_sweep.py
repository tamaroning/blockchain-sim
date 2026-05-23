"""
timewarp 固定で λΔ と攻撃者ハッシュレート割合をスイープし、
stale_rate / honest_only_stale_rate / attacker_only_stale_rate を CSV に出力する。

攻撃者割合は既定で 0〜100% を 5% 刻み（0.05 きざみの割合 0.0〜1.0 に相当）。
各 (λΔ, 割合) で --trials 本シミュレーションし、--stale-stat で集約する
（既定 median_run: stale_rate が中央値に最も近い試行の3指標を採用）。

シミュレーション長・metrics 高さ範囲は run_required_hashrate_fifty_percent.py と同様
（--end-round 省略時は 2×epoch_len ブロック、skip_initial_epochs 以降を集計）。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = next(
    c for c in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents] if (c / "Cargo.toml").exists()
)
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_PATH.parent))

from experiments.utils import ensure_release_binary, find_project_root, run_cargo_build_release
from run_required_hashrate_fifty_percent import (
    BITCOIN_DAA_EPOCH_LEN,
    DEFAULT_LAMBDA_DELTAS,
    DEFAULT_SIM_EPOCHS,
    EpochSuccessParams,
    I64_MAX,
    README_TOTAL_HASHRATE_EH,
    SIMULATION_END_ROUND_BUFFER,
    default_total_hashrate,
    delay_ms_for_lambda_delta,
    ensure_profile,
    mean_stale_rate_at_percent,
)

DEFAULT_ATTACKER_PERCENTS = tuple(float(i) for i in range(0, 101, 5))


def default_attacker_percents(step_pct: float, pct_min: float, pct_max: float) -> tuple[float, ...]:
    if step_pct <= 0:
        raise ValueError("step_pct は正である必要があります")
    if pct_min > pct_max:
        raise ValueError("pct_min は pct_max 以下である必要があります")
    n = int(round((pct_max - pct_min) / step_pct))
    return tuple(round(pct_min + i * step_pct, 10) for i in range(n + 1))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--lambda-deltas",
        type=str,
        default=",".join(str(x) for x in DEFAULT_LAMBDA_DELTAS),
        help="カンマ区切りの λΔ（run_required_hashrate_fifty_percent.py と同じ既定）",
    )
    p.add_argument(
        "--attacker-percents",
        type=str,
        default=None,
        help=(
            "カンマ区切りの攻撃者割合 [%%]（省略時は --pct-min/--pct-max/--pct-step で生成、"
            "既定 0,5,…,100）"
        ),
    )
    p.add_argument("--pct-min", type=float, default=0.0, help="攻撃者割合スイープ下限 [%%]")
    p.add_argument("--pct-max", type=float, default=100.0, help="攻撃者割合スイープ上限 [%%]")
    p.add_argument(
        "--pct-step",
        type=float,
        default=1.0,
        help="攻撃者割合の刻み [%%]（5 → 0.05 きざみの割合）",
    )
    p.add_argument("--trials", type=int, default=40, help="各格子点の試行回数")
    p.add_argument(
        "--end-round",
        type=int,
        default=None,
        help=(
            "評価対象の end_round。省略時は "
            f"{DEFAULT_SIM_EPOCHS}×--epoch-len（既定 {BITCOIN_DAA_EPOCH_LEN}）"
        ),
    )
    p.add_argument("--protocol", type=str, default="bitcoin")
    p.add_argument("--total-hashrate", type=int, default=None)
    p.add_argument("--num-honest-nodes", type=int, default=1)
    p.add_argument("--epoch-len", type=int, default=BITCOIN_DAA_EPOCH_LEN)
    p.add_argument("--skip-initial-epochs", type=int, default=1)
    p.add_argument("--binary", type=Path, default=None)
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="集約 CSV（省略時: results/timewarp_stale_rate_sweep.csv）",
    )
    p.add_argument("--results-dir", type=Path, default=None)
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--base-seed", type=int, default=None)
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-progress", action="store_true")
    p.add_argument(
        "--keep-raw-csv",
        action="store_true",
        help="試行ごとの metrics CSV を残す（KEEP_RAW=1）",
    )
    p.add_argument(
        "--stale-stat",
        choices=("mean", "median", "median_high", "median_run"),
        default="median_run",
        help=(
            "trials 集約（既定: median_run）。"
            "stale_rate が中央値に最も近い 1 run の stale / honest / attacker 指標を採用"
        ),
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    base_dir = SCRIPT_PATH.parents[1]

    if args.keep_raw_csv:
        os.environ["KEEP_RAW"] = "1"

    lambda_deltas = tuple(
        float(x.strip()) for x in args.lambda_deltas.split(",") if x.strip()
    )
    if not lambda_deltas:
        raise ValueError("--lambda-deltas が空です")

    if args.attacker_percents is not None:
        attacker_percents = tuple(
            float(x.strip()) for x in args.attacker_percents.split(",") if x.strip()
        )
    else:
        attacker_percents = default_attacker_percents(
            args.pct_step, args.pct_min, args.pct_max
        )
    if not attacker_percents:
        raise ValueError("攻撃者割合リストが空です")
    for pct in attacker_percents:
        if not (0 <= pct <= 100):
            raise ValueError(f"攻撃者割合は 0〜100 である必要があります: {pct}")

    if args.trials <= 0:
        raise ValueError("--trials は正である必要があります")
    if args.epoch_len <= 0:
        raise ValueError("--epoch-len は正である必要があります")
    if args.skip_initial_epochs < 0:
        raise ValueError("--skip-initial-epochs は 0 以上である必要があります")
    if args.num_honest_nodes < 1:
        raise ValueError("--num-honest-nodes は 1 以上である必要があります")

    epoch_params = EpochSuccessParams(
        epoch_len=args.epoch_len,
        rolling_window=11,
        attacker_blocks_needed=6,
        attacker_node_id=0,
        skip_initial_epochs=args.skip_initial_epochs,
    )

    if args.end_round is not None:
        end_round = args.end_round
    else:
        end_round = args.epoch_len * DEFAULT_SIM_EPOCHS
    if end_round <= 0:
        raise ValueError("--end-round は正である必要があります")

    sim_end_round = end_round + SIMULATION_END_ROUND_BUFFER
    metrics_min_height = epoch_params.skip_initial_epochs * epoch_params.epoch_len
    metrics_max_height = end_round - 1

    total_hr = args.total_hashrate if args.total_hashrate is not None else default_total_hashrate()
    if args.total_hashrate is None and not args.quiet:
        print(
            f"注意: デフォルト total_hashrate={total_hr} を使用。"
            f"README の {README_TOTAL_HASHRATE_EH} EH/s は i64 上限 ({I64_MAX}) を超えます。",
            file=sys.stderr,
        )

    if args.binary is not None:
        binary_path = args.binary
    else:
        project_root = find_project_root(SCRIPT_PATH.parent)
        if not args.skip_build:
            run_cargo_build_release(project_root)
        binary_path = ensure_release_binary(SCRIPT_PATH.parent)

    profile_dir = base_dir / "profiles"
    output_csv = (
        args.output
        if args.output is not None
        else base_dir / "results" / "timewarp_stale_rate_sweep.csv"
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    results_base = (
        args.results_dir
        if args.results_dir is not None
        else base_dir / "results" / "runs_stale_rate_sweep"
    )

    rows: list[dict[str, Any]] = []
    total_cells = len(lambda_deltas) * len(attacker_percents)
    cell_num = 0
    prog = not args.no_progress
    profile_cache: dict[float, Path] = {}

    if prog:
        print("=== Timewarp stale-rate sweep: starting ===", flush=True)
        print(
            f"lambda_deltas ({len(lambda_deltas)}): {lambda_deltas}",
            flush=True,
        )
        print(
            f"attacker_percents ({len(attacker_percents)}): {attacker_percents}",
            flush=True,
        )
        print(
            f"trials={args.trials}, parallel={args.parallel}, "
            f"end_round={end_round} (sim --end-round={sim_end_round}), "
            f"metrics heights [{metrics_min_height}, {metrics_max_height}]",
            flush=True,
        )
        print(f"Total grid cells: {total_cells}", flush=True)
        print("", flush=True)

    for lambda_delta in lambda_deltas:
        delay_ms = delay_ms_for_lambda_delta(lambda_delta, args.protocol)
        ld_tag = str(lambda_delta).replace(".", "p")
        results_dir = results_base / f"tw_ld{ld_tag}"

        for attacker_percent in attacker_percents:
            cell_num += 1
            try:
                if attacker_percent not in profile_cache:
                    profile_cache[attacker_percent] = ensure_profile(
                        attacker_percent,
                        total_hr,
                        profile_dir,
                        selfish_timewarp=False,
                        num_honest_nodes=args.num_honest_nodes,
                    )
                profile_path = profile_cache[attacker_percent]
            except ValueError as e:
                if prog:
                    print(
                        f"[{cell_num}/{total_cells}] skip λΔ={lambda_delta} "
                        f"attacker={attacker_percent}%: {e}",
                        flush=True,
                    )
                continue

            if prog:
                print(
                    f"[{cell_num}/{total_cells}] λΔ={lambda_delta} "
                    f"attacker={attacker_percent}% "
                    f"({args.trials} trial(s), stale_stat={args.stale_stat}) ...",
                    flush=True,
                )

            stale_rates_agg = mean_stale_rate_at_percent(
                attacker_percent=attacker_percent,
                trials=args.trials,
                binary_path=binary_path,
                profile_path=profile_path,
                results_dir=results_dir,
                end_round=sim_end_round,
                protocol=args.protocol,
                delay_ms=delay_ms,
                base_seed=args.base_seed,
                parallel=args.parallel,
                tag="tw_sweep",
                lambda_delta=lambda_delta,
                metrics_min_height=metrics_min_height,
                metrics_max_height=metrics_max_height,
                stale_stat=args.stale_stat,
            )
            rows.append(
                {
                    "strategy": "timewarp",
                    "lambda_delta": lambda_delta,
                    "attacker_percent": attacker_percent,
                    "attacker_fraction": attacker_percent / 100.0,
                    "honest_hashrate_percent": 100.0 - attacker_percent,
                    "stale_rate": stale_rates_agg.stale_rate,
                    "honest_only_stale_rate": stale_rates_agg.honest_only_stale_rate,
                    "attacker_only_stale_rate": stale_rates_agg.attacker_only_stale_rate,
                }
            )

    fieldnames = [
        "strategy",
        "lambda_delta",
        "attacker_percent",
        "attacker_fraction",
        "honest_hashrate_percent",
        "stale_rate",
        "honest_only_stale_rate",
        "attacker_only_stale_rate",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    if prog:
        print("", flush=True)
        print(f"=== Done. Wrote {len(rows)} row(s) to {output_csv} ===", flush=True)
    else:
        print(f"Wrote aggregate CSV: {output_csv} ({len(rows)} rows)", flush=True)


if __name__ == "__main__":
    main()
