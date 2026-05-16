"""
timewarp / selfish_timewarp それぞれについて、λΔ (= 伝播遅延 Δ / 目標ブロック間隔 λ) を変えながら、
二分探索で「攻撃成功」の経験確率が約 50% となる攻撃者ハッシュレート割合を求める。

成功判定は --success-mode で選べる。

- difficulty（既定）: メインチェーン上で difficulty < d_th のブロックが一度でも出る（--difficulty-threshold）。
- epoch: Bitcoin 風の 2016 ブロックを 1 エポックとみなし、各 run で合格率（合格エポック数 / 評価対象エポック数）を出し、
  複数 run のその値の平均を --epoch-median-target（既定 0.5）と比較して二分探索する。
  difficulty モードは従来どおり「試行ごとの成否」の件数で 50% を判定する。
  epoch モードの --end-round 省略時は 2×epoch_len ブロックのみシミュレーションする（DAA により実効 λΔ が長尺で初期から乖離しやすいため）。
  長い run が必要なら --end-round を明示する。

epoch モードの合格条件（エポック index e >= --skip-initial-epochs で、かつチェーンが当該エポック末端まで到達）:
  - 当該エポックの先頭・末尾ブロック（高さ e*L+1 と (e+1)*L）の minter が攻撃者ノード
  - エポック内の中間ブロック（高さ h_first+1 .. h_last-1）について、それぞれ直前 11 ブロック
    （高さ h-1, …, h-11）のうち攻撃者生成が --attacker-blocks-in-window 本以上

最初のエポック（e=0）は直前エポックがないため評価対象外（デフォルト skip=1）。

λ は Bitcoin プロトコル上 600s 相当（600_000 ms）固定。遅延は delay_ms = λΔ * 600_000。
メインチェーン CSV には minter が含まれる（profile 先頭ノードが攻撃者なら id=0）。

シミュレータには --end-round として（評価目標の end_round + SIMULATION_END_ROUND_BUFFER）を渡す。
私有分岐の公開・メインチェーン合流の余裕をとる（判定ロジックの対象エポック／高さは変えない）。

出力 CSV 列: strategy, lambda_delta, attacker_percent, stale_rate
（stale_rate は ChainMetrics.stale_rate を、推定 attacker_percent で trials 本実行し平均した値）
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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

BITCOIN_DAA_EPOCH_LEN = 2016
DEFAULT_END_ROUND_DIFFICULTY = 300 * BITCOIN_DAA_EPOCH_LEN
# epoch モード: 何 DAA エポック分だけチェーンを伸ばすか（--end-round 省略時）
DEFAULT_SIM_EPOCHS_EPOCH_MODE = 2
README_TOTAL_HASHRATE_EH = 800
I64_MAX = 2**63 - 1
DEFAULT_TOTAL_HASHRATE = 800_000_000_000_000_000
BITCOIN_TARGET_BLOCK_MS = 600_000
# デフォルト λΔ: 10^k（k = -2.5, -2, …, 0.5）
DEFAULT_LAMBDA_DELTAS = tuple(10**k for k in (-2.5, -2, -1.5, -1, -0.5, 0, 0.5))
# 評価目標 end_round 到達後、シミュレータをこの分だけ延長（分岐合流の余裕）
SIMULATION_END_ROUND_BUFFER = 30

SUCCESS_MODE_DIFFICULTY = "difficulty"
SUCCESS_MODE_EPOCH = "epoch"


@dataclass(frozen=True)
class EpochSuccessParams:
    epoch_len: int
    rolling_window: int
    attacker_blocks_needed: int
    attacker_node_id: int
    skip_initial_epochs: int


def default_total_hashrate() -> int:
    return DEFAULT_TOTAL_HASHRATE


def delay_ms_for_lambda_delta(lambda_delta: float, protocol: str) -> int:
    """λΔ = Δ/λ とみなし、delay_ms = round(λΔ * target_block_time_ms)。"""
    if protocol != "bitcoin":
        raise ValueError("現在は --protocol bitcoin のみ対応")
    return int(round(lambda_delta * BITCOIN_TARGET_BLOCK_MS))


def ensure_profile(
    attacker_percent: float,
    total_hashrate: int,
    profile_dir: Path,
    *,
    selfish_timewarp: bool,
) -> Path:
    if not (0 <= attacker_percent <= 100):
        raise ValueError("attacker_percent は 0〜100")

    bps = int(round(attacker_percent * 100))
    attacker_hr = (total_hashrate * bps) // 10_000
    defender_hr = total_hashrate - attacker_hr
    if defender_hr < 0:
        raise ValueError("defender hashrate が負になりました")

    strategy_type = "selfish_timewarp" if selfish_timewarp else "timewarp"
    profile_dir.mkdir(parents=True, exist_ok=True)
    pct_tenths = int(round(attacker_percent * 10))
    profile_path = profile_dir / f"{strategy_type}_attacker_{pct_tenths:04d}pct.json"
    honest_a = defender_hr // 2
    honest_b = defender_hr - honest_a
    profile: dict[str, Any] = {
        "nodes": [
            {"hashrate": attacker_hr, "strategy": {"type": strategy_type}},
            {"hashrate": honest_a, "strategy": {"type": "honest"}},
            {"hashrate": honest_b, "strategy": {"type": "honest"}},
        ],
    }
    return write_profile_json(profile, profile_path)


def run_one_simulation(
    *,
    binary_path: Path,
    profile_path: Path,
    end_round: int,
    delay_ms: int,
    protocol: str,
    seed: int,
    output_csv: Path | None = None,
    metrics_csv: Path | None = None,
) -> None:
    if output_csv is None and metrics_csv is None:
        raise ValueError("output_csv と metrics_csv のどちらかは指定してください")
    cmd = [
        str(binary_path),
        f"--end-round={end_round}",
        f"--protocol={protocol}",
        f"--profile={profile_path}",
        f"--delay={delay_ms}",
        f"--seed={seed}",
    ]
    if output_csv is not None:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--output={output_csv}")
    if metrics_csv is not None:
        metrics_csv.parent.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--metrics={metrics_csv}")
    env = {**os.environ, "RUST_LOG": "info"}
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"シミュレーション失敗 (exit={result.returncode})\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def read_stale_rate_from_metrics(metrics_csv: Path) -> float:
    """シミュレータの --metrics（1 行 CSV）から ChainMetrics.stale_rate を読む。"""
    with metrics_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
    if row is None or "stale_rate" not in row:
        raise ValueError(f"metrics CSV に stale_rate がありません: {metrics_csv}")
    return float(row["stale_rate"])


def _single_stale_rate_job(
    args: tuple[
        Path,
        Path,
        Path,
        float,
        int,
        int,
        str,
        int,
        int,
        str,
        float,
    ],
) -> float:
    (
        binary_path,
        profile_path,
        results_dir,
        attacker_percent,
        run_index,
        end_round,
        protocol,
        delay_ms,
        seed,
        tag,
        lambda_delta,
    ) = args
    results_dir.mkdir(parents=True, exist_ok=True)
    pct_tenths = int(round(attacker_percent * 10))
    ld_tag = str(lambda_delta).replace(".", "p")
    metrics_path = (
        results_dir / f"{tag}_ld{ld_tag}_pct_{pct_tenths:04d}_metrics_{run_index:04d}.csv"
    )
    run_one_simulation(
        binary_path=binary_path,
        profile_path=profile_path,
        end_round=end_round,
        delay_ms=delay_ms,
        protocol=protocol,
        seed=seed,
        output_csv=None,
        metrics_csv=metrics_path,
    )
    sr = read_stale_rate_from_metrics(metrics_path)
    if not os.environ.get("KEEP_RAW"):
        metrics_path.unlink(missing_ok=True)
    return sr


def mean_stale_rate_at_percent(
    *,
    attacker_percent: float,
    trials: int,
    binary_path: Path,
    profile_path: Path,
    results_dir: Path,
    end_round: int,
    protocol: str,
    delay_ms: int,
    base_seed: int | None,
    parallel: int,
    tag: str,
    lambda_delta: float,
) -> float:
    """推定攻撃者割合で trials 本シミュレーションし、stale_rate の標本平均を返す。"""
    pct_i = int(round(attacker_percent * 10))

    def seed_for(r: int) -> int:
        if base_seed is not None:
            ld_i = int(round(lambda_delta * 1_000_000))
            st = 1 if tag == "selfish" else 0
            return (
                base_seed
                + st * 1_000_000_000
                + ld_i * 100_000
                + pct_i * 1_000
                + r
                + 50_000
            ) % (
                2**63
            )  # count_successes と被らないオフセット
        return int.from_bytes(os.urandom(8), "little") & ((1 << 63) - 1)

    jobs = [
        (
            binary_path,
            profile_path,
            results_dir,
            attacker_percent,
            r,
            end_round,
            protocol,
            delay_ms,
            seed_for(r),
            tag,
            lambda_delta,
        )
        for r in range(1, trials + 1)
    ]
    if parallel <= 1:
        rates = [_single_stale_rate_job(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_single_stale_rate_job, j) for j in jobs]
            rates = [f.result() for f in as_completed(futs)]
    return statistics.mean(rates)


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


def _read_main_chain_minters(csv_path: Path) -> dict[int, int]:
    """round(高さ) -> minter node id。大きい minter（ダミー）も int で保持。"""
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(
        csv_path,
        converters={"minter": lambda s: int(str(s).strip())},
    )
    if "round" not in df.columns or "minter" not in df.columns:
        raise ValueError(f"{csv_path} に round / minter 列がありません")
    df = df.sort_values("round").drop_duplicates(subset=["round"], keep="last")
    return {int(r): int(m) for r, m in zip(df["round"], df["minter"])}


def per_run_epoch_timewarp_success_rate(
    csv_path: Path,
    p: EpochSuccessParams,
) -> float:
    """
    評価対象エポックそれぞれが条件を満たせば 1、満たさなければ 0。
    戻り値 = 合格エポック数 / 評価対象エポック数（対象が 0 なら 0.0）。
    """
    by_h = _read_main_chain_minters(csv_path)
    if not by_h:
        return 0.0
    max_h = max(by_h)
    complete_epochs = max_h // p.epoch_len
    start_e = p.skip_initial_epochs
    if complete_epochs <= start_e:
        return 0.0

    L = p.epoch_len
    w = p.rolling_window
    need = p.attacker_blocks_needed
    aid = p.attacker_node_id

    passed = 0
    total = 0
    for e in range(start_e, complete_epochs):
        h_first = e * L + 1
        h_last = (e + 1) * L
        total += 1
        ok = True
        if by_h.get(h_first) != aid or by_h.get(h_last) != aid:
            ok = False
        else:
            for h in range(h_first + 1, h_last):
                window = [by_h.get(h - k) for k in range(1, w + 1)]
                if any(v is None for v in window):
                    ok = False
                    break
                if sum(1 for v in window if v == aid) < need:
                    ok = False
                    break
        if ok:
            passed += 1
    return passed / float(total) if total else 0.0


def _single_difficulty_trial_job(
    args: tuple[
        Path,
        Path,
        Path,
        float,
        int,
        int,
        str,
        float,
        int,
        int,
        int,
        str,
        float,
    ],
) -> bool:
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
        tag,
        lambda_delta,
    ) = args
    results_dir.mkdir(parents=True, exist_ok=True)
    pct_tenths = int(round(attacker_percent * 10))
    ld_tag = str(lambda_delta).replace(".", "p")
    out_csv = (
        results_dir / f"{tag}_ld{ld_tag}_pct_{pct_tenths:04d}_run_{run_index:04d}.csv"
    )
    run_one_simulation(
        binary_path=binary_path,
        profile_path=profile_path,
        end_round=end_round,
        delay_ms=delay_ms,
        protocol=protocol,
        output_csv=out_csv,
        seed=seed,
    )
    success = first_block_below_threshold(out_csv, thresh) != -1
    if not os.environ.get("KEEP_RAW"):
        out_csv.unlink(missing_ok=True)
    return success


def _single_epoch_rate_trial_job(
    args: tuple[
        Path,
        Path,
        Path,
        float,
        int,
        int,
        str,
        float,
        int,
        int,
        int,
        str,
        float,
        EpochSuccessParams,
    ],
) -> float:
    (
        binary_path,
        profile_path,
        results_dir,
        attacker_percent,
        run_index,
        end_round,
        protocol,
        _thresh,
        delay_ms,
        seed,
        _total_hashrate,
        tag,
        lambda_delta,
        epoch_params,
    ) = args
    results_dir.mkdir(parents=True, exist_ok=True)
    pct_tenths = int(round(attacker_percent * 10))
    ld_tag = str(lambda_delta).replace(".", "p")
    out_csv = (
        results_dir / f"{tag}_ld{ld_tag}_pct_{pct_tenths:04d}_run_{run_index:04d}.csv"
    )
    run_one_simulation(
        binary_path=binary_path,
        profile_path=profile_path,
        end_round=end_round,
        delay_ms=delay_ms,
        protocol=protocol,
        output_csv=out_csv,
        seed=seed,
    )
    rate = per_run_epoch_timewarp_success_rate(out_csv, epoch_params)
    if not os.environ.get("KEEP_RAW"):
        out_csv.unlink(missing_ok=True)
    return rate


def count_successes(
    *,
    attacker_percent: float,
    trials: int,
    binary_path: Path,
    profile_path: Path,
    results_dir: Path,
    end_round: int,
    protocol: str,
    thresh: float,
    delay_ms: int,
    total_hashrate: int,
    base_seed: int | None,
    parallel: int,
    tag: str,
    lambda_delta: float,
) -> int:
    pct_i = int(round(attacker_percent * 10))

    def seed_for(r: int) -> int:
        if base_seed is not None:
            ld_i = int(round(lambda_delta * 1_000_000))
            st = 1 if tag == "selfish" else 0
            return (
                base_seed
                + st * 1_000_000_000
                + ld_i * 100_000
                + pct_i * 1_000
                + r
            ) % (2**63)
        return int.from_bytes(os.urandom(8), "little") & ((1 << 63) - 1)

    jobs = [
        (
            binary_path,
            profile_path,
            results_dir,
            attacker_percent,
            r,
            end_round,
            protocol,
            thresh,
            delay_ms,
            seed_for(r),
            total_hashrate,
            tag,
            lambda_delta,
        )
        for r in range(1, trials + 1)
    ]
    if parallel <= 1:
        return sum(_single_difficulty_trial_job(j) for j in jobs)
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = [ex.submit(_single_difficulty_trial_job, j) for j in jobs]
        return sum(f.result() for f in as_completed(futs))


def mean_epoch_run_success_rates(
    *,
    attacker_percent: float,
    trials: int,
    binary_path: Path,
    profile_path: Path,
    results_dir: Path,
    end_round: int,
    protocol: str,
    thresh: float,
    delay_ms: int,
    total_hashrate: int,
    base_seed: int | None,
    parallel: int,
    tag: str,
    lambda_delta: float,
    epoch_params: EpochSuccessParams,
) -> float:
    """各 run のエポック合格率を求め、その平均を返す。"""
    pct_i = int(round(attacker_percent * 10))

    def seed_for(r: int) -> int:
        if base_seed is not None:
            ld_i = int(round(lambda_delta * 1_000_000))
            st = 1 if tag == "selfish" else 0
            return (
                base_seed
                + st * 1_000_000_000
                + ld_i * 100_000
                + pct_i * 1_000
                + r
            ) % (2**63)
        return int.from_bytes(os.urandom(8), "little") & ((1 << 63) - 1)

    jobs = [
        (
            binary_path,
            profile_path,
            results_dir,
            attacker_percent,
            r,
            end_round,
            protocol,
            thresh,
            delay_ms,
            seed_for(r),
            total_hashrate,
            tag,
            lambda_delta,
            epoch_params,
        )
        for r in range(1, trials + 1)
    ]
    if parallel <= 1:
        rates = [_single_epoch_rate_trial_job(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_single_epoch_rate_trial_job, j) for j in jobs]
            rates = [f.result() for f in as_completed(futs)]
    return statistics.mean(rates)


def binary_search_fifty_percent(
    *,
    min_pct: float,
    max_pct: float,
    trials: int,
    tol_pct: float,
    max_iter: int,
    profile_cache: dict[float, Path],
    get_profile: Any,
    run_probe: Any,
    success_mode: str,
    epoch_median_target: float,
    progress: bool = False,
) -> float:
    lo, hi = min_pct, max_pct
    for iter_num in range(1, max_iter + 1):
        if hi - lo <= tol_pct:
            if progress:
                print(
                    f"  Binary search: stopping (interval width "
                    f"{hi - lo:.2f}% <= tolerance {tol_pct}%).",
                    flush=True,
                )
            return round((lo + hi) / 2 * 10) / 10.0
        mid = round((lo + hi) / 2 * 10) / 10.0
        if mid <= lo:
            mid = min(hi, round((lo + 0.1) * 10) / 10.0)
        if mid >= hi:
            mid = max(lo, round((hi - 0.1) * 10) / 10.0)
        if mid <= lo or mid >= hi:
            if progress:
                print(
                    f"  Binary search: cannot split interval further "
                    f"[{lo:.1f}%, {hi:.1f}%]; returning midpoint.",
                    flush=True,
                )
            return round((lo + hi) / 2 * 10) / 10.0
        if mid not in profile_cache:
            profile_cache[mid] = get_profile(mid)
        if progress:
            print(
                f"  Binary search step {iter_num}/{max_iter}: "
                f"running {trials} simulations at attacker_share={mid}% "
                f"(search interval [{lo:.1f}%, {hi:.1f}%]) ...",
                flush=True,
            )
        stat = run_probe(mid, profile_cache[mid])
        if success_mode == SUCCESS_MODE_DIFFICULTY:
            k = stat
            if progress:
                emp = k / float(trials)
                if k * 2 > trials:
                    decision = (
                        f"empirical success rate {emp:.2f} > 0.5 — "
                        f"try lower share (hi := {mid}%)"
                    )
                elif k * 2 < trials:
                    decision = (
                        f"empirical success rate {emp:.2f} < 0.5 — "
                        f"try higher share (lo := {mid}%)"
                    )
                else:
                    decision = "empirical success rate exactly 0.5 — done."
                print(
                    f"  Binary search step {iter_num}: outcomes {k}/{trials} "
                    f"({emp:.2%}); {decision}",
                    flush=True,
                )
            if k * 2 > trials:
                hi = mid
            elif k * 2 < trials:
                lo = mid
            else:
                return mid
        elif success_mode == SUCCESS_MODE_EPOCH:
            m = stat
            tgt = epoch_median_target
            if progress:
                if m > tgt:
                    decision = (
                        f"mean per-run epoch rate {m:.4f} > {tgt} — "
                        f"try lower share (hi := {mid}%)"
                    )
                elif m < tgt:
                    decision = (
                        f"mean per-run epoch rate {m:.4f} < {tgt} — "
                        f"try higher share (lo := {mid}%)"
                    )
                else:
                    decision = f"mean per-run epoch rate == {tgt} — done."
                print(
                    f"  Binary search step {iter_num}: mean(run epoch rates)={m:.4f}; "
                    f"{decision}",
                    flush=True,
                )
            if m > tgt:
                hi = mid
            elif m < tgt:
                lo = mid
            else:
                return mid
        else:
            raise ValueError(f"unknown success_mode: {success_mode!r}")
    if progress:
        print(
            f"  Binary search: reached max_iter={max_iter}; "
            f"returning midpoint of [{lo:.1f}%, {hi:.1f}%].",
            flush=True,
        )
    return round((lo + hi) / 2 * 10) / 10.0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "strategy × λΔ ごとに、攻撃成功確率が約 0.5 となる攻撃者割合を二分探索で求める。"
        )
    )
    p.add_argument(
        "--lambda-deltas",
        type=str,
        default=",".join(str(x) for x in DEFAULT_LAMBDA_DELTAS),
        help=(
            "カンマ区切りの λΔ（=Δ/λ。bitcoin では delay_ms = λΔ×600000）。"
            "省略時は 10^-2.5 … 10^0.5（0.5 刻みの指数）"
        ),
    )
    p.add_argument(
        "--trials",
        type=int,
        default=40,
        help="二分探索の各探索点での試行回数（デフォルト: 30）",
    )
    p.add_argument(
        "--min-pct",
        type=float,
        default=None,
        help=(
            "両戦略共通の探索下限 [%%]（省略時は戦略別: timewarp=--min-pct-timewarp, "
            "selfish=--min-pct-selfish）"
        ),
    )
    p.add_argument(
        "--max-pct",
        type=float,
        default=None,
        help=(
            "両戦略共通の探索上限 [%%]（省略時は戦略別デフォルト。timewarp と selfish で区間が異なる）"
        ),
    )
    p.add_argument(
        "--min-pct-timewarp",
        type=float,
        default=0.1,
        help="timewarp の探索下限 [%%]（--min-pct 指定時はそちらが両方に優先）",
    )
    p.add_argument(
        "--max-pct-timewarp",
        type=float,
        default=99.9,
        help="timewarp の探索上限 [%%]",
    )
    p.add_argument(
        "--min-pct-selfish",
        type=float,
        default=0.1,
        help="selfish_timewarp の探索下限 [%%]",
    )
    p.add_argument(
        "--max-pct-selfish",
        type=float,
        default=49.9,
        help="selfish_timewarp の探索上限 [%%]（README の 47〜50%% 付近を想定しやや広め）",
    )
    p.add_argument(
        "--tol-pct",
        type=float,
        default=0.1,
        help="区間幅がこの値以下になったら打ち切り [%%]（デフォルト: 0.1）",
    )
    p.add_argument(
        "--max-iter",
        type=int,
        default=10,
        help="二分探索の最大イテレーション",
    )
    p.add_argument(
        "--end-round",
        type=int,
        default=None,
        help=(
            "シミュレーションの --end-round。省略時は difficulty モードで "
            f"{DEFAULT_END_ROUND_DIFFICULTY}、epoch モードで "
            f"{DEFAULT_SIM_EPOCHS_EPOCH_MODE}×--epoch-len（既定 {BITCOIN_DAA_EPOCH_LEN}）"
        ),
    )
    p.add_argument("--protocol", type=str, default="bitcoin", help="--protocol")
    p.add_argument(
        "--total-hashrate",
        type=int,
        default=None,
        help="ネットワーク総ハッシュレート（省略時はデフォルト値）",
    )
    p.add_argument(
        "--difficulty-threshold",
        type=float,
        default=1024.0,
        help=(
            "攻撃成功とみなす難易度閾値 d_th（CSV の difficulty < d_th、デフォルト: 1024）"
        ),
    )
    p.add_argument(
        "--success-mode",
        type=str,
        choices=(SUCCESS_MODE_DIFFICULTY, SUCCESS_MODE_EPOCH),
        default=SUCCESS_MODE_DIFFICULTY,
        help=(
            "試行の成功判定: difficulty=難易度閾値、epoch=2016 ブロック単位の timewarp 維持条件 "
            f"（デフォルト: {SUCCESS_MODE_DIFFICULTY}）"
        ),
    )
    p.add_argument(
        "--epoch-len",
        type=int,
        default=BITCOIN_DAA_EPOCH_LEN,
        help=f"epoch モードのエポック長（高さの区切り、既定 {BITCOIN_DAA_EPOCH_LEN}）",
    )
    p.add_argument(
        "--rolling-window",
        type=int,
        default=11,
        help="epoch モード: 各中間ブロックで見る直前ブロック数（既定: 11）",
    )
    p.add_argument(
        "--attacker-blocks-in-window",
        type=int,
        default=6,
        help="epoch モード: rolling-window 内に必要な攻撃者ブロック数（既定: 6）",
    )
    p.add_argument(
        "--attacker-node-id",
        type=int,
        default=0,
        help="epoch モード: 攻撃者ノード ID（本実験の profile では先頭が 0）",
    )
    p.add_argument(
        "--skip-initial-epochs",
        type=int,
        default=1,
        help="epoch モード: 先頭からこの数のエポックを評価から除外（既定: 1 = 最初のエポックのみ除外）",
    )
    p.add_argument(
        "--epoch-median-target",
        type=float,
        default=0.5,
        help=(
            "epoch モード: 各探索点で trials 本の run 合格率の平均と比較する目標値（既定: 0.5）"
        ),
    )
    p.add_argument(
        "--binary",
        type=Path,
        default=None,
        help="blockchain-sim バイナリ",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="集約 CSV（省略時: results/required_hashrate_fifty_percent.csv）",
    )
    p.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="中間 run のベースディレクトリ",
    )
    p.add_argument("--parallel", type=int, default=1, help="各探索点の試行を並列実行する数")
    p.add_argument(
        "--base-seed",
        type=int,
        default=None,
        help="再現用の基底シード",
    )
    p.add_argument("--skip-build", action="store_true", help="cargo build をスキップ")
    p.add_argument(
        "--quiet",
        action="store_true",
        help="スケールに関する注意を出さない",
    )
    p.add_argument(
        "--no-progress",
        action="store_true",
        help="Do not print English progress messages",
    )
    p.add_argument(
        "--keep-raw-csv",
        action="store_true",
        help="Keep per-trial raw CSV outputs (also set env KEEP_RAW=1)",
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
    if args.trials <= 0:
        raise ValueError("--trials は正である必要があります")
    if args.difficulty_threshold <= 0:
        raise ValueError("--difficulty-threshold は正である必要があります")

    epoch_params: EpochSuccessParams | None = None
    if args.success_mode == SUCCESS_MODE_EPOCH:
        if args.epoch_len <= 0:
            raise ValueError("--epoch-len は正である必要があります")
        if args.rolling_window < 1:
            raise ValueError("--rolling-window は 1 以上である必要があります")
        if not (1 <= args.attacker_blocks_in_window <= args.rolling_window):
            raise ValueError(
                "--attacker-blocks-in-window は 1 以上 --rolling-window 以下である必要があります"
            )
        if args.skip_initial_epochs < 0:
            raise ValueError("--skip-initial-epochs は 0 以上である必要があります")
        if not (0.0 <= args.epoch_median_target <= 1.0):
            raise ValueError("--epoch-median-target は 0〜1 である必要があります")
        epoch_params = EpochSuccessParams(
            epoch_len=args.epoch_len,
            rolling_window=args.rolling_window,
            attacker_blocks_needed=args.attacker_blocks_in_window,
            attacker_node_id=args.attacker_node_id,
            skip_initial_epochs=args.skip_initial_epochs,
        )

    if args.end_round is not None:
        end_round = args.end_round
    elif args.success_mode == SUCCESS_MODE_EPOCH:
        end_round = args.epoch_len * DEFAULT_SIM_EPOCHS_EPOCH_MODE
    else:
        end_round = DEFAULT_END_ROUND_DIFFICULTY
    if end_round <= 0:
        raise ValueError("--end-round は正である必要があります")
    sim_end_round = end_round + SIMULATION_END_ROUND_BUFFER
    tw_lo = args.min_pct if args.min_pct is not None else args.min_pct_timewarp
    tw_hi = args.max_pct if args.max_pct is not None else args.max_pct_timewarp
    sf_lo = args.min_pct if args.min_pct is not None else args.min_pct_selfish
    sf_hi = args.max_pct if args.max_pct is not None else args.max_pct_selfish
    if tw_lo >= tw_hi:
        raise ValueError("timewarp: 探索区間は min < max にしてください（現在の下限・上限を確認）")
    if sf_lo >= sf_hi:
        raise ValueError("selfish_timewarp: 探索区間は min < max にしてください")

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
        else base_dir / "results" / "required_hashrate_fifty_percent.csv"
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []

    total_phases = 2 * len(lambda_deltas)
    phase_num = 0
    prog = not args.no_progress

    if prog:
        print(
            "=== Required hashrate (≈50% attack success): starting ===",
            flush=True,
        )
        cfg_extra = ""
        if args.success_mode == SUCCESS_MODE_EPOCH:
            cfg_extra = (
                f", success_mode=epoch (L={args.epoch_len}, window={args.rolling_window}, "
                f"need={args.attacker_blocks_in_window}, attacker_id={args.attacker_node_id}, "
                f"skip_epochs={args.skip_initial_epochs}, mean_target={args.epoch_median_target})"
            )
        print(
            f"Configuration: lambda_deltas={lambda_deltas}, trials_per_probe={args.trials}, "
            f"success_mode={args.success_mode}"
            + (
                f", d_th={args.difficulty_threshold}"
                if args.success_mode == SUCCESS_MODE_DIFFICULTY
                else ""
            )
            + cfg_extra
            + f", parallel={args.parallel}, end_round={end_round} "
            f"(simulator --end-round={sim_end_round}, +{SIMULATION_END_ROUND_BUFFER}), "
            f"protocol={args.protocol}",
            flush=True,
        )
        print(
            f"Phases: {total_phases} total (strategies: timewarp, selfish_timewarp × "
            f"{len(lambda_deltas)} lambda_delta value(s)). "
            "Each phase: bracket check (2 batches of simulations) + binary search batches.",
            flush=True,
        )
        print("", flush=True)

    for selfish in (True, False):
        strategy = "selfish_timewarp" if selfish else "timewarp"
        lo_p, hi_p = (sf_lo, sf_hi) if selfish else (tw_lo, tw_hi)
        for lambda_delta in lambda_deltas:
            phase_num += 1
            delay_ms = delay_ms_for_lambda_delta(lambda_delta, args.protocol)
            thresh = float(args.difficulty_threshold)
            if prog:
                dline = (
                    f"d_th={thresh:.6g}"
                    if args.success_mode == SUCCESS_MODE_DIFFICULTY
                    else f"epoch maintenance (mean target={args.epoch_median_target})"
                )
                print(
                    f"[Phase {phase_num}/{total_phases}] strategy={strategy!r} "
                    f"lambda_delta={lambda_delta} delay_ms={delay_ms} {dline}",
                    flush=True,
                )
                print(
                    f"  Search bounds: attacker_share in [{lo_p}%, {hi_p}%] "
                    f"(timewarp: [{tw_lo}, {tw_hi}], selfish: [{sf_lo}, {sf_hi}]).",
                    flush=True,
                )
                if args.success_mode == SUCCESS_MODE_DIFFICULTY:
                    act = (
                        "count per-trial successes where main-chain difficulty drops "
                        "below threshold."
                    )
                else:
                    act = (
                        "take mean of per-run epoch success rates vs target "
                        f"({args.epoch_median_target})."
                    )
                print(f"  Action: run blockchain-sim batches; {act}", flush=True)
            results_base = (
                args.results_dir
                if args.results_dir is not None
                else base_dir / "results" / "runs_fifty_percent"
            )
            tag = "selfish" if selfish else "tw"
            results_dir = results_base / f"{tag}_ld{str(lambda_delta).replace('.', 'p')}"
            t = args.trials

            profile_cache: dict[float, Path] = {}

            def get_profile(pct: float) -> Path:
                return ensure_profile(pct, total_hr, profile_dir, selfish_timewarp=selfish)

            def run_probe(pct: float, prof: Path) -> int | float:
                if args.success_mode == SUCCESS_MODE_DIFFICULTY:
                    return count_successes(
                        attacker_percent=pct,
                        trials=args.trials,
                        binary_path=binary_path,
                        profile_path=prof,
                        results_dir=results_dir,
                        end_round=sim_end_round,
                        protocol=args.protocol,
                        thresh=thresh,
                        delay_ms=delay_ms,
                        total_hashrate=total_hr,
                        base_seed=args.base_seed,
                        parallel=args.parallel,
                        tag=tag,
                        lambda_delta=lambda_delta,
                    )
                assert epoch_params is not None
                return mean_epoch_run_success_rates(
                    attacker_percent=pct,
                    trials=args.trials,
                    binary_path=binary_path,
                    profile_path=prof,
                    results_dir=results_dir,
                    end_round=sim_end_round,
                    protocol=args.protocol,
                    thresh=thresh,
                    delay_ms=delay_ms,
                    total_hashrate=total_hr,
                    base_seed=args.base_seed,
                    parallel=args.parallel,
                    tag=tag,
                    lambda_delta=lambda_delta,
                    epoch_params=epoch_params,
                )

            if lo_p not in profile_cache:
                profile_cache[lo_p] = get_profile(lo_p)
            if hi_p not in profile_cache:
                profile_cache[hi_p] = get_profile(hi_p)
            if prog:
                print(
                    f"  Bracket: running {args.trials} simulations at lower bound "
                    f"attacker_share={lo_p}% ...",
                    flush=True,
                )
            stat_lo = run_probe(lo_p, profile_cache[lo_p])
            if prog:
                if args.success_mode == SUCCESS_MODE_DIFFICULTY:
                    k_lo = stat_lo
                    print(
                        f"  Bracket lower: successes={k_lo}/{t} "
                        f"({k_lo / float(t):.2%} empirical).",
                        flush=True,
                    )
                else:
                    print(
                        f"  Bracket lower: mean(run epoch rates)={stat_lo:.4f} "
                        f"(target {args.epoch_median_target}).",
                        flush=True,
                    )
                print(
                    f"  Bracket: running {args.trials} simulations at upper bound "
                    f"attacker_share={hi_p}% ...",
                    flush=True,
                )
            stat_hi = run_probe(hi_p, profile_cache[hi_p])
            if prog:
                if args.success_mode == SUCCESS_MODE_DIFFICULTY:
                    k_hi = stat_hi
                    print(
                        f"  Bracket upper: successes={k_hi}/{t} "
                        f"({k_hi / float(t):.2%} empirical).",
                        flush=True,
                    )
                else:
                    print(
                        f"  Bracket upper: mean(run epoch rates)={stat_hi:.4f} "
                        f"(target {args.epoch_median_target}).",
                        flush=True,
                    )
            if args.success_mode == SUCCESS_MODE_DIFFICULTY:
                k_lo, k_hi = stat_lo, stat_hi
                if k_lo * 2 >= t:
                    hint = (
                        "--min-pct-selfish" if selfish else "--min-pct-timewarp"
                    )
                    if args.min_pct is not None:
                        hint = "--min-pct"
                    raise RuntimeError(
                        f"{strategy} λΔ={lambda_delta}: 下限 {lo_p}% で成功 {k_lo}/{t}（既に ≥0.5）。"
                        f" {hint} を下げるか区間を見直してください。"
                    )
                if k_hi * 2 <= t:
                    hint = (
                        "--max-pct-selfish" if selfish else "--max-pct-timewarp"
                    )
                    if args.max_pct is not None:
                        hint = "--max-pct"
                    raise RuntimeError(
                        f"{strategy} λΔ={lambda_delta}: 上限 {hi_p}% で成功 {k_hi}/{t}（まだ ≤0.5）。"
                        f" {hint} を上げるか区間を見直してください。"
                    )
            else:
                m_lo, m_hi = stat_lo, stat_hi
                tgt = args.epoch_median_target
                if m_lo >= tgt:
                    hint = (
                        "--min-pct-selfish" if selfish else "--min-pct-timewarp"
                    )
                    if args.min_pct is not None:
                        hint = "--min-pct"
                    raise RuntimeError(
                        f"{strategy} λΔ={lambda_delta}: 下限 {lo_p}% で合格率の平均が "
                        f"既に ≥ {tgt}。{hint} を下げるか区間を見直してください。"
                    )
                if m_hi <= tgt:
                    hint = (
                        "--max-pct-selfish" if selfish else "--max-pct-timewarp"
                    )
                    if args.max_pct is not None:
                        hint = "--max-pct"
                    raise RuntimeError(
                        f"{strategy} λΔ={lambda_delta}: 上限 {hi_p}% で合格率の平均が "
                        f"まだ ≤ {tgt}。{hint} を上げるか区間を見直してください。"
                    )

            if prog:
                print("  Bracket OK. Starting binary search for ~50% empirical success ...", flush=True)

            estimate = binary_search_fifty_percent(
                min_pct=lo_p,
                max_pct=hi_p,
                trials=args.trials,
                tol_pct=args.tol_pct,
                max_iter=args.max_iter,
                profile_cache=profile_cache,
                get_profile=get_profile,
                run_probe=run_probe,
                success_mode=args.success_mode,
                epoch_median_target=args.epoch_median_target,
                progress=prog,
            )
            prof_est = ensure_profile(
                estimate, total_hr, profile_dir, selfish_timewarp=selfish
            )
            if prog:
                print(
                    f"  stale_rate: running {args.trials} simulation(s) at "
                    f"attacker_share≈{estimate}% (--metrics 平均) ...",
                    flush=True,
                )
            stale_rate_mean = mean_stale_rate_at_percent(
                attacker_percent=estimate,
                trials=args.trials,
                binary_path=binary_path,
                profile_path=prof_est,
                results_dir=results_dir,
                end_round=sim_end_round,
                protocol=args.protocol,
                delay_ms=delay_ms,
                base_seed=args.base_seed,
                parallel=args.parallel,
                tag=tag,
                lambda_delta=lambda_delta,
            )
            rows.append(
                {
                    "strategy": strategy,
                    "lambda_delta": lambda_delta,
                    "attacker_percent": estimate,
                    "stale_rate": stale_rate_mean,
                }
            )
            if prog:
                print(
                    f"[Phase {phase_num}/{total_phases}] finished: strategy={strategy!r} "
                    f"lambda_delta={lambda_delta} -> attacker_share ≈ {estimate}% "
                    f"(saved to row {len(rows)}/{total_phases} in output table).",
                    flush=True,
                )
                print("", flush=True)
            else:
                print(
                    f"{strategy} λΔ={lambda_delta} (delay_ms={delay_ms}) -> "
                    f"attacker_percent≈{estimate}",
                    flush=True,
                )

    fieldnames = ["strategy", "lambda_delta", "attacker_percent", "stale_rate"]
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    if prog:
        print("=== All phases complete. ===", flush=True)
    print(f"Wrote aggregate CSV: {output_csv}", flush=True)


if __name__ == "__main__":
    main()
