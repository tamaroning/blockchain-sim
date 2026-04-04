"""
README の手順に従い、timewarp 攻撃者のハッシュレート割合を走査して
「難易度が十分に降下した」とみなすまでのブロック高を記録する。

閾値: 最終チェーン上でいずれかのブロックの difficulty が
  D_ref / 4 未満になった最初の高さを採用。
  D_ref = delay_ms * total_hashrate / 2^32 （T_gen ≈ T_prop となる難易度の目安）
到達しなければ blocks_to_threshold = -1。
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = next(
    c for c in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents] if (c / "Cargo.toml").exists()
)
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import (
    ensure_release_binary,
    find_project_root,
    run_cargo_build_release,
    write_profile_json,
)

# README: 300 * 2016 ブロック、遅延 1.5s、目標生成 600s（Rust Bitcoin プロトコルは 10 分 ms で固定）
DEFAULT_END_ROUND = 300 * 2016
DEFAULT_DELAY_MS = 1500
# README の 800 EH/s (=800e18 H/s) は i64 を超える。シミュレータは相対比が主なので
# 8e17 をデフォルトとする（必要なら --total-hashrate で変更）。
README_TOTAL_HASHRATE_EH = 800
I64_MAX = 2**63 - 1
DEFAULT_TOTAL_HASHRATE = 800_000_000_000_000_000  # 8e17 H/s


def default_total_hashrate() -> int:
    return DEFAULT_TOTAL_HASHRATE


def difficulty_threshold(delay_ms: int, total_hashrate: int) -> float:
    return (delay_ms * float(total_hashrate) / float(2**32)) / 4.0


def ensure_profile(attacker_percent: int, total_hashrate: int, profile_dir: Path) -> Path:
    if not (0 <= attacker_percent <= 100):
        raise ValueError("attacker_percent は 0〜100")

    attacker_hr = (total_hashrate * attacker_percent) // 100
    defender_hr = total_hashrate - attacker_hr
    if defender_hr < 0:
        raise ValueError("defender hashrate が負になりました")

    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / f"timewarp_attacker_{attacker_percent:03d}pct.json"
    profile: dict[str, Any] = {
        "nodes": [
            {"hashrate": attacker_hr, "strategy": {"type": "timewarp"}},
            {"hashrate": defender_hr, "strategy": {"type": "honest"}},
        ]
    }
    return write_profile_json(profile, profile_path)


def run_one_simulation(
    *,
    binary_path: Path,
    profile_path: Path,
    end_round: int,
    delay_ms: int,
    protocol: str,
    output_csv: Path,
    seed: int,
) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(binary_path),
        f"--end-round={end_round}",
        f"--protocol={protocol}",
        f"--profile={profile_path}",
        f"--output={output_csv}",
        f"--delay={delay_ms}",
        f"--seed={seed}",
    ]
    env = {**os.environ, "RUST_LOG": "info"}
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"シミュレーション失敗 (exit={result.returncode})\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def first_block_below_threshold(csv_path: Path, threshold: float) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path)
    if "round" not in df.columns or "difficulty" not in df.columns:
        raise ValueError(f"{csv_path} に round / difficulty 列がありません")
    df = df.sort_values("round")
    mask = df["difficulty"] < threshold
    if not mask.any():
        return -1
    return int(df.loc[mask, "round"].iloc[0])


def run_single_job(
    args_tuple: tuple[
        Path,
        Path,
        Path,
        int,
        int,
        int,
        str,
        float,
        int,
        int,
        int,
    ],
) -> dict[str, Any]:
    (
        binary_path,
        profile_path,
        results_dir,
        attacker_percent,
        run_index,
        end_round,
        protocol,
        thresh,
        delay_ms,
        seed,
        total_hashrate,
    ) = args_tuple

    results_dir.mkdir(parents=True, exist_ok=True)
    out_csv = results_dir / f"raw_pct_{attacker_percent:03d}_run_{run_index:04d}.csv"
    run_one_simulation(
        binary_path=binary_path,
        profile_path=profile_path,
        end_round=end_round,
        delay_ms=delay_ms,
        protocol=protocol,
        output_csv=out_csv,
        seed=seed,
    )
    blocks = first_block_below_threshold(out_csv, thresh)
    return {
        "attacker_percent": attacker_percent,
        "run_index": run_index,
        "seed": seed,
        "blocks_to_threshold": blocks,
        "total_hashrate": total_hashrate,
        "delay_ms": delay_ms,
        "threshold_difficulty": thresh,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="timewarp 攻撃者割合を走査し、難易度閾値到達までのブロック高を CSV に記録する。"
    )
    p.add_argument(
        "--min-pct",
        type=int,
        default=70,
        help="攻撃者ハッシュレート割合の下限 [%%]（デフォルト: 70）",
    )
    p.add_argument(
        "--max-pct",
        type=int,
        default=100,
        help="攻撃者ハッシュレート割合の上限 [%%]（デフォルト: 100）",
    )
    p.add_argument(
        "--step",
        type=int,
        default=1,
        help="割合の刻み（デフォルト: 1）",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=100,
        help="各割合あたりのシミュレーション回数（デフォルト: 100）",
    )
    p.add_argument(
        "--end-round",
        type=int,
        default=DEFAULT_END_ROUND,
        help=f"--end-round（デフォルト: {DEFAULT_END_ROUND} = 300*2016）",
    )
    p.add_argument(
        "--delay",
        type=int,
        default=DEFAULT_DELAY_MS,
        help="伝播遅延 [ms]（デフォルト: 1500）",
    )
    p.add_argument(
        "--total-hashrate",
        type=int,
        default=None,
        help="ネットワーク総ハッシュレート（省略時は README の 800EH/s を満たす値、i64 超過時は上限にクランプ）",
    )
    p.add_argument("--protocol", type=str, default="bitcoin", help="--protocol（デフォルト: bitcoin）")
    p.add_argument(
        "--binary",
        type=Path,
        default=None,
        help="blockchain-sim バイナリ（省略時は target/release/blockchain-sim）",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="集約 CSV（デフォルト: experiments/determine_required_hashrate/results/required_hashrate_sweep.csv）",
    )
    p.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="中間 CSV（各 run）の保存先（デフォルト: experiments/determine_required_hashrate/results/runs/）",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="同時実行するジョブ数（デフォルト: 1）",
    )
    p.add_argument(
        "--base-seed",
        type=int,
        default=None,
        help="再現用の基底シード。指定時は seed = (base + pct*100000 + run) %% 2^63",
    )
    p.add_argument(
        "--keep-raw-csv",
        action="store_true",
        help="各 run の生 CSV を削除しない",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="cargo build --release をスキップ（バイナリが既にある場合）",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="スケールに関する注意メッセージを出さない",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    base_dir = SCRIPT_PATH.parents[1]

    if args.min_pct > args.max_pct or args.step <= 0 or args.runs <= 0:
        raise ValueError("--min-pct <= --max-pct、--step > 0、--runs > 0 が必要です")

    total_hr = args.total_hashrate if args.total_hashrate is not None else default_total_hashrate()
    if args.total_hashrate is None and not args.quiet:
        print(
            f"注意: デフォルト total_hashrate={total_hr} を使用しています。"
            f"README の {README_TOTAL_HASHRATE_EH} EH/s そのものは i64 上限 ({I64_MAX}) を超えます。"
            f"閾値は delay×total_hashrate に比例するため、別スケールなら --total-hashrate を指定してください。",
            file=sys.stderr,
        )

    thresh = difficulty_threshold(args.delay, total_hr)
    percents = list(range(args.min_pct, args.max_pct + 1, args.step))

    profile_dir = base_dir / "profiles"
    profiles: dict[int, Path] = {}
    for pct in percents:
        profiles[pct] = ensure_profile(pct, total_hr, profile_dir)

    if args.binary is not None:
        binary_path = args.binary
    else:
        project_root = find_project_root(SCRIPT_PATH.parent)
        if not args.skip_build:
            run_cargo_build_release(project_root)
        binary_path = ensure_release_binary(SCRIPT_PATH.parent)

    results_dir = args.results_dir or (base_dir / "results" / "runs")
    output_csv = args.output or (base_dir / "results" / "required_hashrate_sweep.csv")
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    def make_seed(pct: int, run_i: int) -> int:
        if args.base_seed is not None:
            return (args.base_seed + pct * 100_000 + run_i) % (2**63)
        return int.from_bytes(os.urandom(8), "little") & ((1 << 63) - 1)

    jobs: list[tuple[Any, ...]] = []
    for pct in percents:
        prof = profiles[pct]
        for r in range(1, args.runs + 1):
            jobs.append(
                (
                    binary_path,
                    prof,
                    results_dir,
                    pct,
                    r,
                    args.end_round,
                    args.protocol,
                    thresh,
                    args.delay,
                    make_seed(pct, r),
                    total_hr,
                )
            )

    fieldnames = [
        "attacker_percent",
        "run_index",
        "seed",
        "blocks_to_threshold",
        "total_hashrate",
        "delay_ms",
        "threshold_difficulty",
    ]

    rows_out: list[dict[str, Any]] = []
    if args.parallel <= 1:
        for j in jobs:
            rows_out.append(run_single_job(j))
            print(
                f"pct={j[3]} run={j[4]} -> blocks={rows_out[-1]['blocks_to_threshold']}",
                flush=True,
            )
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(run_single_job, j): j for j in jobs}
            for fut in as_completed(futs):
                j = futs[fut]
                row = fut.result()
                rows_out.append(row)
                print(f"pct={j[3]} run={j[4]} -> blocks={row['blocks_to_threshold']}", flush=True)

    rows_out.sort(key=lambda r: (r["attacker_percent"], r["run_index"]))
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    if not args.keep_raw_csv:
        for pct in percents:
            for r in range(1, args.runs + 1):
                p = results_dir / f"raw_pct_{pct:03d}_run_{r:04d}.csv"
                if p.exists():
                    p.unlink()

    print(f"集約 CSV を書き込みました: {output_csv}")


if __name__ == "__main__":
    main()
