"""
timewarp / selfish_timewarp それぞれについて、λΔ (= 伝播遅延 Δ / 目標ブロック間隔 λ) を変えながら、
二分探索で「攻撃成功」の経験確率が約 50% となる攻撃者ハッシュレート割合を求める。

Bitcoin 風の 2016 ブロックを 1 エポックとみなし、各 run で合格率（合格エポック数 / 評価対象エポック数）を出し、
複数 run のその値の平均を --epoch-median-target（既定 0.5）と比較して二分探索する。
--end-round 省略時は 2×epoch_len ブロックのみシミュレーションする（DAA により実効 λΔ が長尺で初期から乖離しやすいため）。
長い run が必要なら --end-round を明示する。

合格条件（エポック index e >= --skip-initial-epochs で、かつチェーンが当該エポック末端まで到達）:
  - 当該エポックの先頭・末尾ブロック（高さ e*L と (e+1)*L-1；Bitcoin DAA の 2016 ブロック区間と整合）の minter が攻撃者ノード
  - エポック内の中間ブロック（高さ h_first+1 .. h_last-1）について、それぞれ直前 11 ブロック
    （高さ h-1, …, h-11）のうち攻撃者生成が --attacker-blocks-in-window 本以上

最初のエポック（e=0）は直前エポックがないため評価対象外（デフォルト skip=1）。

λ は Bitcoin プロトコル上 600s 相当（600_000 ms）固定。遅延は delay_ms = λΔ * 600_000。
伝播遅延は攻撃者不利仮定（--propagation-delay-mode attacker-unfavorable: A→* のみ Δ）。
メインチェーン CSV には minter が含まれる（profile 先頭ノードが攻撃者なら id=0）。
defender の hashrate は `--num-honest-nodes`（既定 2）個の honest ノードに等分する。

シミュレータには --end-round として（評価目標の end_round + SIMULATION_END_ROUND_BUFFER）を渡す。
私有分岐の公開・メインチェーン合流の余裕をとる（判定ロジックの対象エポック／高さは変えない）。

出力 CSV 列: strategy, lambda_delta, attacker_percent, honest_hashrate_percent,
stale_rate, honest_only_stale_rate, attacker_only_stale_rate
（いずれも 50% 成功点の attacker_percent で trials 本実行し集約。
 stale_rate は全採掘ブロック、honest_only_stale_rate / attacker_only_stale_rate は
 それぞれ honest / 攻撃者採掘のみ。集計高さは skip_initial_epochs 以降の評価エポック区間に限定。
 --stale-stat median_run 時は stale_rate が trials 中央値に最も近い 1 run の3指標を採用）

固定 λΔ では honest_hashrate_percent に対して honest_only_stale_rate は単調減少になるのが自然。
λΔ も同時に変える本 CSV の行を honest シェアだけで並べると非単調になり得る（遅延効果）。
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
# 何 DAA エポック分だけチェーンを伸ばすか（--end-round 省略時）
DEFAULT_SIM_EPOCHS = 2
README_TOTAL_HASHRATE_EH = 800
I64_MAX = 2**63 - 1
DEFAULT_TOTAL_HASHRATE = 800_000_000_000_000_000
BITCOIN_TARGET_BLOCK_MS = 600_000
# デフォルト λΔ: 10^k（k = ±POINT を STEP 刻みで対称スイープ、降順）
DEFAULT_LAMBDA_DELTA_EXP_POINT = 2.5
DEFAULT_LAMBDA_DELTA_EXP_STEP = 0.25


def default_lambda_deltas(
    exp_point: float = DEFAULT_LAMBDA_DELTA_EXP_POINT,
    step: float = DEFAULT_LAMBDA_DELTA_EXP_STEP,
) -> tuple[float, ...]:
    """λΔ = 10^k の列。k は -exp_point から +exp_point を step 刻み（降順）。"""
    if step <= 0:
        raise ValueError("step は正である必要があります")
    if exp_point < 0:
        raise ValueError("exp_point は非負である必要があります")
    n = int(round(exp_point / step))
    if abs(n * step - exp_point) > 1e-9:
        raise ValueError(
            f"exp_point ({exp_point}) は step ({step}) の整数倍である必要があります"
        )
    exps = tuple(i * step for i in range(-n, n + 1))
    return tuple(10**k for k in reversed(exps))


DEFAULT_LAMBDA_DELTAS = default_lambda_deltas()
# 評価目標 end_round 到達後、シミュレータをこの分だけ延長（分岐合流の余裕）
SIMULATION_END_ROUND_BUFFER = 30
# H→* は 0、A→* は Δ（攻撃者不利仮定）
PROPAGATION_DELAY_MODE = "attacker-unfavorable"

@dataclass(frozen=True)
class StaleRates:
    """--metrics 1 行から読み取った stale 指標。"""

    stale_rate: float
    honest_only_stale_rate: float
    attacker_only_stale_rate: float


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


def split_n_equal(total: int, n: int) -> list[int]:
    """total を n 個の非負整数にほぼ等分（余りは先頭から 1 ずつ配分）。"""
    if n < 1:
        raise ValueError("n は 1 以上である必要があります")
    base = total // n
    rem = total % n
    return [base + (1 if i < rem else 0) for i in range(n)]


def ensure_profile(
    attacker_percent: float,
    total_hashrate: int,
    profile_dir: Path,
    *,
    strategy_type: str = "timewarp",
    selfish_timewarp: bool | None = None,
    num_honest_nodes: int = 2,
) -> Path:
    if not (0 <= attacker_percent <= 100):
        raise ValueError("attacker_percent は 0〜100")
    if num_honest_nodes < 1:
        raise ValueError("num_honest_nodes は 1 以上である必要があります")

    bps = int(round(attacker_percent * 100))
    attacker_hr = (total_hashrate * bps) // 10_000
    defender_hr = total_hashrate - attacker_hr
    if defender_hr < 0:
        raise ValueError("defender hashrate が負になりました")
    if defender_hr < num_honest_nodes:
        raise ValueError(
            f"defender hashrate ({defender_hr}) が honest ノード数 ({num_honest_nodes}) 未満です。"
            "total_hashrate を増やすか --num-honest-nodes を減らしてください。"
        )

    if selfish_timewarp is not None:
        strategy_type = "selfish_timewarp" if selfish_timewarp else "timewarp"
    allowed = ("timewarp", "selfish_timewarp", "private_attack")
    if strategy_type not in allowed:
        raise ValueError(f"strategy_type は {allowed} のいずれかである必要があります: {strategy_type}")
    profile_dir.mkdir(parents=True, exist_ok=True)
    pct_tenths = int(round(attacker_percent * 10))
    profile_path = (
        profile_dir
        / f"{strategy_type}_attacker_{pct_tenths:04d}pct_n{num_honest_nodes}.json"
    )
    honest_parts = split_n_equal(defender_hr, num_honest_nodes)
    nodes: list[dict[str, Any]] = [
        {"hashrate": attacker_hr, "strategy": {"type": strategy_type}},
    ]
    nodes.extend(
        {"hashrate": hr, "strategy": {"type": "honest"}} for hr in honest_parts
    )
    return write_profile_json({"nodes": nodes}, profile_path)


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
    metrics_min_height: int | None = None,
    metrics_max_height: int | None = None,
) -> None:
    if output_csv is None and metrics_csv is None:
        raise ValueError("output_csv と metrics_csv のどちらかは指定してください")
    cmd = [
        str(binary_path),
        f"--end-round={end_round}",
        f"--protocol={protocol}",
        f"--profile={profile_path}",
        f"--delay={delay_ms}",
        f"--propagation-delay-mode={PROPAGATION_DELAY_MODE}",
        f"--seed={seed}",
    ]
    if output_csv is not None:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--output={output_csv}")
    if metrics_csv is not None:
        metrics_csv.parent.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--metrics={metrics_csv}")
        if metrics_min_height is not None:
            cmd.append(f"--metrics-min-height={metrics_min_height}")
        if metrics_max_height is not None:
            cmd.append(f"--metrics-max-height={metrics_max_height}")
    env = {**os.environ, "RUST_LOG": "info"}
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"シミュレーション失敗 (exit={result.returncode})\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def read_stale_rates_from_metrics(metrics_csv: Path) -> StaleRates:
    """シミュレータの --metrics（1 行 CSV）から stale 指標を読む。"""
    with metrics_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
    if row is None:
        raise ValueError(f"metrics CSV が空です: {metrics_csv}")
    if "stale_rate" not in row:
        raise ValueError(f"metrics CSV に stale_rate がありません: {metrics_csv}")
    honest_key = next(
        (k for k in ("honest_stale_rate", "honest_only_stale_rate") if k in row),
        None,
    )
    if honest_key is None:
        raise ValueError(
            f"metrics CSV に honest_stale_rate がありません: {metrics_csv}"
        )
    attacker_key = next(
        (k for k in ("attacker_stale_rate", "attacker_only_stale_rate") if k in row),
        None,
    )
    if attacker_key is None:
        raise ValueError(
            f"metrics CSV に attacker_stale_rate がありません: {metrics_csv}"
        )
    return StaleRates(
        stale_rate=float(row["stale_rate"]),
        honest_only_stale_rate=float(row[honest_key]),
        attacker_only_stale_rate=float(row[attacker_key]),
    )


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
        int | None,
        int | None,
    ],
) -> StaleRates:
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
        metrics_min_height,
        metrics_max_height,
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
        metrics_min_height=metrics_min_height,
        metrics_max_height=metrics_max_height,
    )
    rates = read_stale_rates_from_metrics(metrics_path)
    if not os.environ.get("KEEP_RAW"):
        metrics_path.unlink(missing_ok=True)
    return rates


def _aggregate_stale_rates(rates: list[StaleRates], stale_stat: str) -> StaleRates:
    if not rates:
        raise ValueError("rates が空です")
    if stale_stat == "median_run":
        stale_vals = [r.stale_rate for r in rates]
        med = statistics.median(stale_vals)
        idx = min(
            range(len(rates)),
            key=lambda i: (abs(rates[i].stale_rate - med), i),
        )
        return rates[idx]
    stale_vals = [r.stale_rate for r in rates]
    honest_vals = [r.honest_only_stale_rate for r in rates]
    attacker_vals = [r.attacker_only_stale_rate for r in rates]
    if stale_stat == "median_high":
        agg = statistics.median_high
    elif stale_stat == "median":
        agg = statistics.median
    elif stale_stat == "mean":
        return StaleRates(
            stale_rate=statistics.mean(stale_vals),
            honest_only_stale_rate=statistics.mean(honest_vals),
            attacker_only_stale_rate=statistics.mean(attacker_vals),
        )
    else:
        raise ValueError(
            "stale_stat は mean, median, median_high, median_run のいずれか: "
            f"{stale_stat!r}"
        )
    return StaleRates(
        stale_rate=agg(stale_vals),
        honest_only_stale_rate=agg(honest_vals),
        attacker_only_stale_rate=agg(attacker_vals),
    )


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
    metrics_min_height: int | None,
    metrics_max_height: int | None,
    stale_stat: str,
) -> StaleRates:
    """推定攻撃者割合で trials 本シミュレーションし、stale 指標を集約して返す。"""
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
            )  # 探索試行のシードと被らないオフセット
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
            metrics_min_height,
            metrics_max_height,
        )
        for r in range(1, trials + 1)
    ]
    if parallel <= 1:
        trial_rates = [_single_stale_rate_job(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_single_stale_rate_job, j) for j in jobs]
            trial_rates = [f.result() for f in as_completed(futs)]
    return _aggregate_stale_rates(trial_rates, stale_stat)


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
    L = p.epoch_len
    # エポック e のブロック高さは e*L .. (e+1)*L-1（Bitcoin DAA の retarget 区間と整合）
    complete_epochs = (max_h + 1) // L
    start_e = p.skip_initial_epochs
    if complete_epochs <= start_e:
        return 0.0

    w = p.rolling_window
    need = p.attacker_blocks_needed
    aid = p.attacker_node_id

    passed = 0
    total = 0
    for e in range(start_e, complete_epochs):
        h_first = e * L
        h_last = (e + 1) * L - 1
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


@dataclass(frozen=True)
class PrivateAttackSuccessParams:
    attacker_node_id: int = 0
    min_height: int = 0
    max_height: int = I64_MAX


def read_private_attack_success_from_metrics(metrics_csv: Path) -> float:
    """--metrics CSV の private_attack_reorg_success（評価区間のメインチェーン tip が攻撃者）を 0/1 で返す。"""
    with metrics_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
    if row is None:
        raise ValueError(f"metrics CSV が空です: {metrics_csv}")
    if "private_attack_reorg_success" not in row:
        raise ValueError(
            f"metrics CSV に private_attack_reorg_success がありません: {metrics_csv}"
        )
    return 1.0 if str(row["private_attack_reorg_success"]).lower() in ("true", "1") else 0.0


def _single_epoch_rate_trial_job(
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
        delay_ms,
        seed,
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


def mean_epoch_run_success_rates(
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
            delay_ms,
            seed_for(r),
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


def _single_private_attack_rate_trial_job(
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
        PrivateAttackSuccessParams,
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
        private_params,
    ) = args
    results_dir.mkdir(parents=True, exist_ok=True)
    pct_tenths = int(round(attacker_percent * 10))
    ld_tag = str(lambda_delta).replace(".", "p")
    metrics_csv = (
        results_dir
        / f"{tag}_ld{ld_tag}_pct_{pct_tenths:04d}_run_{run_index:04d}_metrics.csv"
    )
    run_one_simulation(
        binary_path=binary_path,
        profile_path=profile_path,
        end_round=end_round,
        delay_ms=delay_ms,
        protocol=protocol,
        metrics_csv=metrics_csv,
        metrics_min_height=private_params.min_height,
        metrics_max_height=private_params.max_height,
        seed=seed,
    )
    rate = read_private_attack_success_from_metrics(metrics_csv)
    if not os.environ.get("KEEP_RAW"):
        metrics_csv.unlink(missing_ok=True)
    return rate


def mean_private_attack_run_success_rates(
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
    private_params: PrivateAttackSuccessParams,
) -> float:
    """各 run の reorg 成功（0/1）の平均を返す。"""
    pct_i = int(round(attacker_percent * 10))

    def seed_for(r: int) -> int:
        if base_seed is not None:
            ld_i = int(round(lambda_delta * 1_000_000))
            st = {"timewarp": 0, "selfish": 1, "private": 2}.get(tag, 0)
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
            delay_ms,
            seed_for(r),
            tag,
            lambda_delta,
            private_params,
        )
        for r in range(1, trials + 1)
    ]
    if parallel <= 1:
        rates = [_single_private_attack_rate_trial_job(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_single_private_attack_rate_trial_job, j) for j in jobs]
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
        m = run_probe(mid, profile_cache[mid])
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
            f"省略時は 10^{DEFAULT_LAMBDA_DELTA_EXP_POINT} … "
            f"10^{-DEFAULT_LAMBDA_DELTA_EXP_POINT}（指数 STEP={DEFAULT_LAMBDA_DELTA_EXP_STEP}）"
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
        default=99.99,
        help="timewarp の探索上限 [%%]",
    )
    p.add_argument(
        "--min-pct-selfish",
        type=float,
        default=0.01,
        help="selfish_timewarp の探索下限 [%%]",
    )
    p.add_argument(
        "--max-pct-selfish",
        type=float,
        default=55.00,
        help="selfish_timewarp の探索上限 [%%]（README の 47〜50%% 付近を想定しやや広め）",
    )
    p.add_argument(
        "--tol-pct",
        type=float,
        default=0.01,
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
            "シミュレーションの --end-round。省略時は "
            f"{DEFAULT_SIM_EPOCHS}×--epoch-len（既定 {BITCOIN_DAA_EPOCH_LEN}）"
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
        "--num-honest-nodes",
        type=int,
        default=2,
        help="攻撃者以外の honest ノード数（defender hashrate を N 等分、既定: 2）",
    )
    p.add_argument(
        "--epoch-len",
        type=int,
        default=BITCOIN_DAA_EPOCH_LEN,
        help=f"エポック長（高さの区切り、既定 {BITCOIN_DAA_EPOCH_LEN}）",
    )
    p.add_argument(
        "--rolling-window",
        type=int,
        default=11,
        help="各中間ブロックで見る直前ブロック数（既定: 11）",
    )
    p.add_argument(
        "--attacker-blocks-in-window",
        type=int,
        default=6,
        help="rolling-window 内に必要な攻撃者ブロック数（既定: 6）",
    )
    p.add_argument(
        "--attacker-node-id",
        type=int,
        default=0,
        help="攻撃者ノード ID（本実験の profile では先頭が 0）",
    )
    p.add_argument(
        "--skip-initial-epochs",
        type=int,
        default=1,
        help="先頭からこの数のエポックを評価から除外（既定: 1 = 最初のエポックのみ除外）",
    )
    p.add_argument(
        "--epoch-median-target",
        type=float,
        default=0.5,
        help="各探索点で trials 本の run 合格率の平均と比較する目標値（既定: 0.5）",
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
    p.add_argument(
        "--stale-stat",
        choices=("mean", "median", "median_high", "median_run"),
        default="median_high",
        help=(
            "trials 集約方法（既定: median_high）。"
            "median_run: stale_rate が trials 中央値に最も近い 1 run の3指標をそのまま採用。"
            "median / median_high / mean: 各指標を個別に集約"
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
    if args.trials <= 0:
        raise ValueError("--trials は正である必要があります")
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
    if args.num_honest_nodes < 1:
        raise ValueError("--num-honest-nodes は 1 以上である必要があります")
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
    else:
        end_round = args.epoch_len * DEFAULT_SIM_EPOCHS
    if end_round <= 0:
        raise ValueError("--end-round は正である必要があります")
    sim_end_round = end_round + SIMULATION_END_ROUND_BUFFER
    metrics_min_height = epoch_params.skip_initial_epochs * epoch_params.epoch_len
    metrics_max_height = end_round - 1
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
        print(
            f"Configuration: lambda_deltas={lambda_deltas}, trials_per_probe={args.trials}, "
            f"epoch (L={args.epoch_len}, window={args.rolling_window}, "
            f"need={args.attacker_blocks_in_window}, attacker_id={args.attacker_node_id}, "
            f"skip_epochs={args.skip_initial_epochs}, mean_target={args.epoch_median_target}, "
            f"num_honest_nodes={args.num_honest_nodes}), "
            f"parallel={args.parallel}, end_round={end_round} "
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
            if prog:
                print(
                    f"[Phase {phase_num}/{total_phases}] strategy={strategy!r} "
                    f"lambda_delta={lambda_delta} delay_ms={delay_ms} "
                    f"epoch maintenance (mean target={args.epoch_median_target})",
                    flush=True,
                )
                print(
                    f"  Search bounds: attacker_share in [{lo_p}%, {hi_p}%] "
                    f"(timewarp: [{tw_lo}, {tw_hi}], selfish: [{sf_lo}, {sf_hi}]).",
                    flush=True,
                )
                print(
                    f"  Action: run blockchain-sim batches; take mean of per-run epoch "
                    f"success rates vs target ({args.epoch_median_target}).",
                    flush=True,
                )
            results_base = (
                args.results_dir
                if args.results_dir is not None
                else base_dir / "results" / "runs_fifty_percent"
            )
            tag = "selfish" if selfish else "tw"
            results_dir = results_base / f"{tag}_ld{str(lambda_delta).replace('.', 'p')}"

            profile_cache: dict[float, Path] = {}

            def get_profile(pct: float) -> Path:
                return ensure_profile(
                    pct,
                    total_hr,
                    profile_dir,
                    selfish_timewarp=selfish,
                    num_honest_nodes=args.num_honest_nodes,
                )

            def run_probe(pct: float, prof: Path) -> float:
                return mean_epoch_run_success_rates(
                    attacker_percent=pct,
                    trials=args.trials,
                    binary_path=binary_path,
                    profile_path=prof,
                    results_dir=results_dir,
                    end_round=sim_end_round,
                    protocol=args.protocol,
                    delay_ms=delay_ms,
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
                print(
                    f"  Bracket upper: mean(run epoch rates)={stat_hi:.4f} "
                    f"(target {args.epoch_median_target}).",
                    flush=True,
                )
            m_lo, m_hi = stat_lo, stat_hi
            tgt = args.epoch_median_target
            if m_lo >= tgt:
                hint = "--min-pct-selfish" if selfish else "--min-pct-timewarp"
                if args.min_pct is not None:
                    hint = "--min-pct"
                raise RuntimeError(
                    f"{strategy} λΔ={lambda_delta}: 下限 {lo_p}% で合格率の平均が "
                    f"既に ≥ {tgt}。{hint} を下げるか区間を見直してください。"
                )
            if m_hi <= tgt:
                hint = "--max-pct-selfish" if selfish else "--max-pct-timewarp"
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
                epoch_median_target=args.epoch_median_target,
                progress=prog,
            )
            prof_est = ensure_profile(
                estimate,
                total_hr,
                profile_dir,
                selfish_timewarp=selfish,
                num_honest_nodes=args.num_honest_nodes,
            )
            if prog:
                print(
                    f"  stale_rate / honest_only_stale_rate / attacker_only_stale_rate: "
                    f"running {args.trials} "
                    f"simulation(s) at attacker_share≈{estimate}% (--metrics 集約) ...",
                    flush=True,
                )
            honest_pct = 100.0 - estimate
            stale_rates_agg = mean_stale_rate_at_percent(
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
                metrics_min_height=metrics_min_height,
                metrics_max_height=metrics_max_height,
                stale_stat=args.stale_stat,
            )
            rows.append(
                {
                    "strategy": strategy,
                    "lambda_delta": lambda_delta,
                    "attacker_percent": estimate,
                    "honest_hashrate_percent": honest_pct,
                    "stale_rate": stale_rates_agg.stale_rate,
                    "honest_only_stale_rate": stale_rates_agg.honest_only_stale_rate,
                    "attacker_only_stale_rate": stale_rates_agg.attacker_only_stale_rate,
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

    fieldnames = [
        "strategy",
        "lambda_delta",
        "attacker_percent",
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
        print("=== All phases complete. ===", flush=True)
    print(f"Wrote aggregate CSV: {output_csv}", flush=True)


if __name__ == "__main__":
    main()
