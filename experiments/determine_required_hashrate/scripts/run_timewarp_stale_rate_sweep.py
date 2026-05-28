"""
timewarp / selfish_timewarp / private_attack について λΔ と攻撃者ハッシュレート割合をスイープし、
stale_rate / honest_only_stale_rate / attacker_only_stale_rate と各戦略の成功確率を CSV に出力する。

攻撃者割合は既定で 0〜100% を 5% 刻み（0.05 きざみの割合 0.0〜1.0 に相当）。
各 (strategy, λΔ, 割合) で --trials 本シミュレーションし、--stale-stat で stale 指標を集約する
（既定 mean: 各指標を trials 平均）。
timewarp_success_rate は run_required_hashrate_fifty_percent.py と同じエポック合格判定
（各 run の合格エポック数 / 評価対象エポック数）の trials 平均。
private_attack_success_rate は評価高さ区間の告知済みメインチェーン tip が
攻撃者である run の割合（trials 平均。純粋な伸長競争の最終勝者）。

シミュレーション長・metrics 高さ範囲は run_required_hashrate_fifty_percent.py と同様
（--end-round 省略時は 2×epoch_len ブロック、skip_initial_epochs 以降を集計）。

--update 指定時は既存の集約 CSV を読み込み、--lambda-deltas で指定した λΔ の行だけ
再計算して置き換える（他の λΔ の行はそのまま残す）。
--update かつ --attacker-percents 省略時は、既存 CSV から当該 λΔ の攻撃者割合リストを引き継ぐ
（当該 λΔ が CSV に無い新規追加の場合は、CSV 全体の割合リストを使用）。
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
    PrivateAttackSuccessParams,
    mean_epoch_run_success_rates,
    mean_private_attack_run_success_rates,
    mean_stale_rate_at_percent,
)

DEFAULT_ATTACKER_PERCENTS = tuple(float(i) for i in range(0, 101, 5))

ALL_SWEEP_STRATEGIES = ("timewarp", "selfish_timewarp", "private_attack")
SWEEP_STRATEGY_SPECS: dict[str, tuple[str, str]] = {
    "timewarp": ("timewarp", "tw_sweep"),
    "selfish_timewarp": ("selfish_timewarp", "selfish"),
    "private_attack": ("private_attack", "pa_sweep"),
}

CSV_FIELDNAMES = [
    "strategy",
    "lambda_delta",
    "attacker_percent",
    "attacker_fraction",
    "honest_hashrate_percent",
    "stale_rate",
    "honest_only_stale_rate",
    "attacker_only_stale_rate",
    "timewarp_success_rate",
    "private_attack_success_rate",
]


def lambda_delta_key(lambda_delta: float) -> int:
    return int(round(lambda_delta * 1_000_000))


def parse_strategies(raw: str) -> tuple[str, ...]:
    strategies = tuple(s.strip() for s in raw.split(",") if s.strip())
    if not strategies:
        raise ValueError("--strategies が空です")
    unknown = [s for s in strategies if s not in SWEEP_STRATEGY_SPECS]
    if unknown:
        raise ValueError(
            f"未知の strategy: {unknown}（有効: {', '.join(ALL_SWEEP_STRATEGIES)}）"
        )
    return strategies


def sweep_strategy_tuples(
    strategies: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (name, SWEEP_STRATEGY_SPECS[name][0], SWEEP_STRATEGY_SPECS[name][1])
        for name in strategies
    )


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
        default="mean",
        help=(
            "trials 集約（既定: mean）。"
            "stale / honest / attacker 各指標を trials 平均。"
            "median_run: stale_rate が中央値に最も近い 1 run の3指標を採用"
        ),
    )
    p.add_argument(
        "--update",
        action="store_true",
        help=(
            "既存の --output CSV を読み込み、--lambda-deltas で指定した λΔ の行だけ再計算して"
            "置き換える（他の λΔ は保持）。--attacker-percents 省略時は既存行の割合リストを使用"
            "（新規 λΔ は CSV 全体の割合リスト）"
        ),
    )
    p.add_argument(
        "--strategies",
        type=str,
        default=",".join(ALL_SWEEP_STRATEGIES),
        help=(
            "カンマ区切りの strategy（既定: timewarp,selfish_timewarp,private_attack）。"
            "既存 CSV がある場合、指定した strategy の行だけ再計算・置換し、"
            "他 strategy の行は保持する"
        ),
    )
    return p


def load_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"更新対象の CSV が見つかりません: {path}")
    legacy_fieldnames = CSV_FIELDNAMES[:-1]
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if fieldnames not in (CSV_FIELDNAMES, legacy_fieldnames):
            raise ValueError(
                f"CSV 列が想定と異なります: {path}\n"
                f"expected={CSV_FIELDNAMES}\n"
                f"actual={fieldnames}"
            )
        rows = list(reader)
    if fieldnames == legacy_fieldnames:
        for row in rows:
            row["private_attack_success_rate"] = ""
    return rows


def attacker_percents_from_existing_rows(
    rows: list[dict[str, Any]],
    lambda_delta: float | None = None,
) -> tuple[float, ...]:
    if lambda_delta is None:
        return tuple(sorted({float(row["attacker_percent"]) for row in rows}))
    key = lambda_delta_key(lambda_delta)
    percents = sorted(
        {
            float(row["attacker_percent"])
            for row in rows
            if lambda_delta_key(float(row["lambda_delta"])) == key
        }
    )
    return tuple(percents)


def resolve_lambda_deltas_for_update(
    requested: tuple[float, ...],
    existing_rows: list[dict[str, Any]],
) -> tuple[float, ...]:
    existing_by_key = {
        lambda_delta_key(float(row["lambda_delta"])): float(row["lambda_delta"])
        for row in existing_rows
    }
    resolved: list[float] = []
    for requested_ld in requested:
        key = lambda_delta_key(requested_ld)
        if key in existing_by_key:
            resolved.append(existing_by_key[key])
        else:
            resolved.append(requested_ld)
    return tuple(resolved)


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_order = {"timewarp": 0, "selfish_timewarp": 1, "private_attack": 2}

    def sort_key(row: dict[str, Any]) -> tuple[int, int, float]:
        return (
            strategy_order.get(row["strategy"], 99),
            lambda_delta_key(float(row["lambda_delta"])),
            float(row["attacker_percent"]),
        )

    return sorted(rows, key=sort_key)


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def run_sweep_rows(
    *,
    lambda_deltas: tuple[float, ...],
    attacker_percents: tuple[float, ...],
    trials: int,
    end_round: int,
    sim_end_round: int,
    metrics_min_height: int,
    metrics_max_height: int,
    epoch_params: EpochSuccessParams,
    private_params: PrivateAttackSuccessParams,
    binary_path: Path,
    results_base: Path,
    profile_dir: Path,
    protocol: str,
    total_hr: int,
    num_honest_nodes: int,
    base_seed: int | None,
    parallel: int,
    stale_stat: str,
    prog: bool,
    strategies: tuple[str, ...] = ALL_SWEEP_STRATEGIES,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sweep_strategies = sweep_strategy_tuples(strategies)
    total_cells = len(sweep_strategies) * len(lambda_deltas) * len(attacker_percents)
    cell_num = 0
    profile_cache: dict[tuple[str, float], Path] = {}

    if prog:
        print(
            f"lambda_deltas ({len(lambda_deltas)}): {lambda_deltas}",
            flush=True,
        )
        print(
            f"attacker_percents ({len(attacker_percents)}): {attacker_percents}",
            flush=True,
        )
        print(
            f"trials={trials}, parallel={parallel}, "
            f"end_round={end_round} (sim --end-round={sim_end_round}), "
            f"metrics heights [{metrics_min_height}, {metrics_max_height}]",
            flush=True,
        )
        print(f"Total grid cells: {total_cells}", flush=True)
        print("", flush=True)

    for strategy, strategy_type, tag in sweep_strategies:
        for lambda_delta in lambda_deltas:
            delay_ms = delay_ms_for_lambda_delta(lambda_delta, protocol)
            ld_tag = str(lambda_delta).replace(".", "p")
            results_dir = results_base / f"{tag}_ld{ld_tag}"

            for attacker_percent in attacker_percents:
                cell_num += 1
                cache_key = (strategy_type, attacker_percent)
                try:
                    if cache_key not in profile_cache:
                        profile_cache[cache_key] = ensure_profile(
                            attacker_percent,
                            total_hr,
                            profile_dir,
                            strategy_type=strategy_type,
                            num_honest_nodes=num_honest_nodes,
                        )
                    profile_path = profile_cache[cache_key]
                except ValueError as e:
                    if prog:
                        print(
                            f"[{cell_num}/{total_cells}] skip strategy={strategy} "
                            f"λΔ={lambda_delta} attacker={attacker_percent}%: {e}",
                            flush=True,
                        )
                    continue

                if prog:
                    print(
                        f"[{cell_num}/{total_cells}] strategy={strategy} "
                        f"λΔ={lambda_delta} attacker={attacker_percent}% "
                        f"({trials} trial(s), stale_stat={stale_stat}) ...",
                        flush=True,
                    )

                stale_rates_agg = mean_stale_rate_at_percent(
                    attacker_percent=attacker_percent,
                    trials=trials,
                    binary_path=binary_path,
                    profile_path=profile_path,
                    results_dir=results_dir,
                    end_round=sim_end_round,
                    protocol=protocol,
                    delay_ms=delay_ms,
                    base_seed=base_seed,
                    parallel=parallel,
                    tag=tag,
                    lambda_delta=lambda_delta,
                    metrics_min_height=metrics_min_height,
                    metrics_max_height=metrics_max_height,
                    stale_stat=stale_stat,
                )
                timewarp_success_rate = ""
                private_attack_success_rate = ""
                if strategy in ("timewarp", "selfish_timewarp"):
                    timewarp_success_rate = mean_epoch_run_success_rates(
                        attacker_percent=attacker_percent,
                        trials=trials,
                        binary_path=binary_path,
                        profile_path=profile_path,
                        results_dir=results_dir,
                        end_round=sim_end_round,
                        protocol=protocol,
                        delay_ms=delay_ms,
                        base_seed=base_seed,
                        parallel=parallel,
                        tag=tag,
                        lambda_delta=lambda_delta,
                        epoch_params=epoch_params,
                    )
                if strategy == "private_attack":
                    private_attack_success_rate = mean_private_attack_run_success_rates(
                        attacker_percent=attacker_percent,
                        trials=trials,
                        binary_path=binary_path,
                        profile_path=profile_path,
                        results_dir=results_dir,
                        end_round=sim_end_round,
                        protocol=protocol,
                        delay_ms=delay_ms,
                        base_seed=base_seed,
                        parallel=parallel,
                        tag=tag,
                        lambda_delta=lambda_delta,
                        private_params=private_params,
                    )
                rows.append(
                    {
                        "strategy": strategy,
                        "lambda_delta": lambda_delta,
                        "attacker_percent": attacker_percent,
                        "attacker_fraction": attacker_percent / 100.0,
                        "honest_hashrate_percent": 100.0 - attacker_percent,
                        "stale_rate": stale_rates_agg.stale_rate,
                        "honest_only_stale_rate": stale_rates_agg.honest_only_stale_rate,
                        "attacker_only_stale_rate": stale_rates_agg.attacker_only_stale_rate,
                        "timewarp_success_rate": timewarp_success_rate,
                        "private_attack_success_rate": private_attack_success_rate,
                    }
                )
    return rows


def main() -> None:
    args = build_parser().parse_args()
    base_dir = SCRIPT_PATH.parents[1]

    if args.keep_raw_csv:
        os.environ["KEEP_RAW"] = "1"

    requested_lambda_deltas = tuple(
        float(x.strip()) for x in args.lambda_deltas.split(",") if x.strip()
    )
    if not requested_lambda_deltas:
        raise ValueError("--lambda-deltas が空です")

    selected_strategies = parse_strategies(args.strategies)

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
    private_params = PrivateAttackSuccessParams(
        attacker_node_id=epoch_params.attacker_node_id,
        min_height=metrics_min_height,
        max_height=metrics_max_height,
    )

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
    results_base = (
        args.results_dir
        if args.results_dir is not None
        else base_dir / "results" / "runs_stale_rate_sweep"
    )
    prog = not args.no_progress
    attacker_percents: tuple[float, ...] | None = None
    attacker_percents_by_ld: dict[int, tuple[float, ...]] | None = None
    kept_rows: list[dict[str, Any]] = []

    if args.update:
        existing_rows = load_existing_rows(output_csv)
        lambda_deltas = resolve_lambda_deltas_for_update(
            requested_lambda_deltas,
            existing_rows,
        )
        replace_keys = {lambda_delta_key(ld) for ld in lambda_deltas}
        kept_rows = [
            row
            for row in existing_rows
            if lambda_delta_key(float(row["lambda_delta"])) not in replace_keys
            or row["strategy"] not in selected_strategies
        ]
        if args.attacker_percents is not None:
            attacker_percents = tuple(
                float(x.strip()) for x in args.attacker_percents.split(",") if x.strip()
            )
        else:
            attacker_percents_by_ld = {}
            csv_attacker_percents = attacker_percents_from_existing_rows(existing_rows)
            if not csv_attacker_percents:
                raise ValueError("--update: 既存 CSV から攻撃者割合を取得できません")
            for lambda_delta in lambda_deltas:
                key = lambda_delta_key(lambda_delta)
                percents = attacker_percents_from_existing_rows(existing_rows, lambda_delta)
                if not percents:
                    percents = csv_attacker_percents
                    if prog:
                        print(
                            f"λΔ={lambda_delta}: 新規追加 — "
                            f"攻撃者割合 {len(percents)} 点を既存 CSV から引き継ぎ",
                            flush=True,
                        )
                attacker_percents_by_ld[key] = percents
            if len(attacker_percents_by_ld) == 1:
                attacker_percents = next(iter(attacker_percents_by_ld.values()))
                attacker_percents_by_ld = None
        if prog:
            print("=== Timewarp stale-rate sweep: update mode ===", flush=True)
            print(f"Input CSV: {output_csv} ({len(existing_rows)} existing row(s))", flush=True)
            print(
                f"Replacing lambda_deltas ({len(lambda_deltas)}): {lambda_deltas}",
                flush=True,
            )
            print(f"Keeping {len(kept_rows)} row(s) for other λΔ values", flush=True)
            print(f"strategies ({len(selected_strategies)}): {selected_strategies}", flush=True)
    else:
        lambda_deltas = requested_lambda_deltas
        if args.attacker_percents is not None:
            attacker_percents = tuple(
                float(x.strip()) for x in args.attacker_percents.split(",") if x.strip()
            )
        else:
            attacker_percents = default_attacker_percents(
                args.pct_step, args.pct_min, args.pct_max
            )
        if output_csv.is_file() and set(selected_strategies) != set(ALL_SWEEP_STRATEGIES):
            existing_rows = load_existing_rows(output_csv)
            kept_rows = [
                row for row in existing_rows if row["strategy"] not in selected_strategies
            ]
            if args.attacker_percents is None:
                inherited = attacker_percents_from_existing_rows(existing_rows)
                if inherited:
                    attacker_percents = inherited
                    if prog:
                        print(
                            f"攻撃者割合 {len(attacker_percents)} 点を既存 CSV から引き継ぎ",
                            flush=True,
                        )
            if prog:
                print(
                    f"既存 CSV から {len(kept_rows)} 行を保持"
                    f"（{', '.join(s for s in ALL_SWEEP_STRATEGIES if s not in selected_strategies)}）",
                    flush=True,
                )
        if prog:
            print("=== Timewarp stale-rate sweep: starting ===", flush=True)
            print(f"strategies ({len(selected_strategies)}): {selected_strategies}", flush=True)

    if attacker_percents is not None:
        if not attacker_percents:
            raise ValueError("攻撃者割合リストが空です")
        for pct in attacker_percents:
            if not (0 <= pct <= 100):
                raise ValueError(f"攻撃者割合は 0〜100 である必要があります: {pct}")

    new_rows: list[dict[str, Any]] = []
    if attacker_percents_by_ld is not None:
        for lambda_delta in lambda_deltas:
            key = lambda_delta_key(lambda_delta)
            ld_attacker_percents = attacker_percents_by_ld[key]
            if prog:
                print("", flush=True)
                print(f"--- λΔ={lambda_delta} ---", flush=True)
            new_rows.extend(
                run_sweep_rows(
                    lambda_deltas=(lambda_delta,),
                    attacker_percents=ld_attacker_percents,
                    trials=args.trials,
                    end_round=end_round,
                    sim_end_round=sim_end_round,
                    metrics_min_height=metrics_min_height,
                    metrics_max_height=metrics_max_height,
                    epoch_params=epoch_params,
                    private_params=private_params,
                    binary_path=binary_path,
                    results_base=results_base,
                    profile_dir=profile_dir,
                    protocol=args.protocol,
                    total_hr=total_hr,
                    num_honest_nodes=args.num_honest_nodes,
                    base_seed=args.base_seed,
                    parallel=args.parallel,
                    stale_stat=args.stale_stat,
                    prog=prog,
                    strategies=selected_strategies,
                )
            )
    else:
        new_rows = run_sweep_rows(
            lambda_deltas=lambda_deltas,
            attacker_percents=attacker_percents,
            trials=args.trials,
            end_round=end_round,
            sim_end_round=sim_end_round,
            metrics_min_height=metrics_min_height,
            metrics_max_height=metrics_max_height,
            epoch_params=epoch_params,
            private_params=private_params,
            binary_path=binary_path,
            results_base=results_base,
            profile_dir=profile_dir,
            protocol=args.protocol,
            total_hr=total_hr,
            num_honest_nodes=args.num_honest_nodes,
            base_seed=args.base_seed,
            parallel=args.parallel,
            stale_stat=args.stale_stat,
            prog=prog,
            strategies=selected_strategies,
        )

    rows = sort_rows(kept_rows + new_rows)
    write_rows(output_csv, rows)

    if prog:
        print("", flush=True)
        if args.update:
            print(
                f"=== Done. Updated {len(new_rows)} row(s); "
                f"total {len(rows)} row(s) in {output_csv} ===",
                flush=True,
            )
        else:
            print(f"=== Done. Wrote {len(rows)} row(s) to {output_csv} ===", flush=True)
    else:
        print(f"Wrote aggregate CSV: {output_csv} ({len(rows)} rows)", flush=True)


if __name__ == "__main__":
    main()
