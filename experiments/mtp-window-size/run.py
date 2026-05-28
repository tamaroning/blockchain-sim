"""
λΔ = 10^-2 の attacker favorable な状況下で、MTP ウィンドウサイズ W と
攻撃者ハッシュレート割合 α を変えたときの Selfish Time Warp 攻撃成功率を
シミュレーションし、CSV と PNG を出力する。

- strategy: selfish_timewarp
- propagation delay mode: attacker-favorable (H→* は Δ、A→* は 0)
- 攻撃成功率は run_required_hashrate_fifty_percent.py と同じ
  「エポックごとの合格率」を trials 本平均したもの
  （合格判定: エポック先頭・末尾ブロックが攻撃者で、中間ブロックの直前 rolling_window 本のうち
   attacker_blocks_in_window 本以上が攻撃者ノード id=0）

各 (W, α) で --trials 本シミュレーションし、その平均を timewarp_success_rate とする。

出力:
- results/mtp_window_size_sweep.csv
- results/plots/mtp_window_size_sweep.png
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = next(
    c for c in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents] if (c / "Cargo.toml").exists()
)
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(
    0,
    str(PROJECT_ROOT / "experiments" / "determine_required_hashrate" / "scripts"),
)

from experiments.utils import (
    ensure_release_binary,
    find_project_root,
    run_cargo_build_release,
    write_profile_json,
)
from run_required_hashrate_fifty_percent import (  # type: ignore
    BITCOIN_DAA_EPOCH_LEN,
    DEFAULT_SIM_EPOCHS,
    EpochSuccessParams,
    I64_MAX,
    README_TOTAL_HASHRATE_EH,
    SIMULATION_END_ROUND_BUFFER,
    default_total_hashrate,
    delay_ms_for_lambda_delta,
    per_run_epoch_timewarp_success_rate,
    split_n_equal,
)

DEFAULT_LAMBDA_DELTA = 1e-2
# α の格子点は端点とステップで指定（両端を含む）
DEFAULT_ALPHA_START = 0.47
DEFAULT_ALPHA_STOP = 0.52
DEFAULT_ALPHA_STEP = 0.005
DEFAULT_ALPHAS: tuple[float, ...] = tuple(
    round(DEFAULT_ALPHA_START + i * DEFAULT_ALPHA_STEP, 10)
    for i in range(round((DEFAULT_ALPHA_STOP - DEFAULT_ALPHA_START) / DEFAULT_ALPHA_STEP) + 1)
)
DEFAULT_WINDOW_SIZES: tuple[int, ...] = (15, 11, 7, 3)
PROPAGATION_DELAY_MODE = "attacker-favorable"

CSV_FIELDNAMES = [
    "mtp_window_size",
    "lambda_delta",
    "alpha",
    "attacker_percent",
    "timewarp_success_rate",
    "trials",
]


def ensure_selfish_timewarp_profile(
    *,
    alpha: float,
    mtp_window_size: int,
    total_hashrate: int,
    profile_dir: Path,
    num_honest_nodes: int,
) -> Path:
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha は 0〜1 である必要があります: {alpha}")
    if mtp_window_size < 1:
        raise ValueError(f"mtp_window_size は 1 以上: {mtp_window_size}")
    if num_honest_nodes < 1:
        raise ValueError(f"num_honest_nodes は 1 以上: {num_honest_nodes}")

    bps = int(round(alpha * 10_000))
    attacker_hr = (total_hashrate * bps) // 10_000
    defender_hr = total_hashrate - attacker_hr
    if defender_hr < num_honest_nodes:
        raise ValueError(
            f"defender hashrate ({defender_hr}) が honest ノード数 ({num_honest_nodes}) 未満"
        )

    profile_dir.mkdir(parents=True, exist_ok=True)
    pct_thousandths = int(round(alpha * 100_000))
    profile_path = profile_dir / (
        f"selfish_timewarp_w{mtp_window_size:02d}"
        f"_a{pct_thousandths:06d}_n{num_honest_nodes}.json"
    )
    honest_parts = split_n_equal(defender_hr, num_honest_nodes)
    nodes: list[dict[str, Any]] = [
        {
            "hashrate": attacker_hr,
            "strategy": {
                "type": "selfish_timewarp",
                "mtp_window_size": mtp_window_size,
            },
        }
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
    output_csv: Path,
) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(binary_path),
        f"--end-round={end_round}",
        f"--protocol={protocol}",
        f"--profile={profile_path}",
        f"--delay={delay_ms}",
        f"--propagation-delay-mode={PROPAGATION_DELAY_MODE}",
        f"--seed={seed}",
        f"--output={output_csv}",
    ]
    env = {**os.environ, "RUST_LOG": "info"}
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"シミュレーション失敗 (exit={result.returncode})\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _trial_job(
    args: tuple[
        Path,
        Path,
        Path,
        int,
        int,
        int,
        str,
        int,
        int,
        str,
        EpochSuccessParams,
    ],
) -> float:
    (
        binary_path,
        profile_path,
        results_dir,
        window_size,
        run_index,
        end_round,
        protocol,
        delay_ms,
        seed,
        tag,
        epoch_params,
    ) = args
    results_dir.mkdir(parents=True, exist_ok=True)
    out_csv = (
        results_dir
        / f"{tag}_w{window_size:02d}_run_{run_index:04d}.csv"
    )
    run_one_simulation(
        binary_path=binary_path,
        profile_path=profile_path,
        end_round=end_round,
        delay_ms=delay_ms,
        protocol=protocol,
        seed=seed,
        output_csv=out_csv,
    )
    rate = per_run_epoch_timewarp_success_rate(out_csv, epoch_params)
    if not os.environ.get("KEEP_RAW"):
        out_csv.unlink(missing_ok=True)
    return rate


def mean_success_rate(
    *,
    binary_path: Path,
    profile_path: Path,
    results_dir: Path,
    window_size: int,
    alpha: float,
    trials: int,
    end_round: int,
    protocol: str,
    delay_ms: int,
    base_seed: int | None,
    parallel: int,
    tag: str,
    lambda_delta: float,
    epoch_params: EpochSuccessParams,
) -> float:
    alpha_int = int(round(alpha * 100_000))
    ld_int = int(round(lambda_delta * 1_000_000))

    def seed_for(r: int) -> int:
        if base_seed is not None:
            return (
                base_seed
                + window_size * 10_000_000_000
                + ld_int * 100_000_000
                + alpha_int * 1_000
                + r
            ) % (2**63)
        return int.from_bytes(os.urandom(8), "little") & ((1 << 63) - 1)

    jobs = [
        (
            binary_path,
            profile_path,
            results_dir,
            window_size,
            r,
            end_round,
            protocol,
            delay_ms,
            seed_for(r),
            tag,
            epoch_params,
        )
        for r in range(1, trials + 1)
    ]
    if parallel <= 1:
        rates = [_trial_job(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(_trial_job, j) for j in jobs]
            rates = [f.result() for f in as_completed(futs)]
    return statistics.mean(rates)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def plot_results(
    csv_path: Path,
    png_path: Path,
    *,
    figsize: tuple[float, float],
    show: bool,
) -> None:
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV が見つかりません: {csv_path}")
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError(f"CSV が空です: {csv_path}")
    for col in ("mtp_window_size", "alpha", "timewarp_success_rate", "lambda_delta"):
        if col not in df.columns:
            raise ValueError(f"CSV に列 '{col}' がありません: {csv_path}")

    lambda_deltas = sorted(df["lambda_delta"].unique())
    if len(lambda_deltas) != 1:
        # 通常は 1 つだけ。複数あるときは凡例表記のため最初の値を採用。
        lambda_delta = lambda_deltas[0]
    else:
        lambda_delta = lambda_deltas[0]

    window_sizes = sorted(df["mtp_window_size"].unique(), reverse=True)
    cmap = plt.get_cmap("viridis")
    colors = (
        [cmap(0.85)] if len(window_sizes) == 1
        else [cmap(i / max(len(window_sizes) - 1, 1)) for i in range(len(window_sizes))]
    )

    fig, ax = plt.subplots(figsize=figsize, layout="constrained")

    for color, w in zip(colors, window_sizes):
        sub = df[df["mtp_window_size"] == w].sort_values("alpha")
        ax.plot(
            sub["alpha"],
            sub["timewarp_success_rate"],
            marker="o",
            linestyle="-",
            color=color,
            linewidth=1.8,
            label=f"W = {int(w)}",
        )

    ax.set_xlabel(r"attacker hashrate share $\alpha$")
    ax.set_ylabel("Selfish Time Warp success rate")
    ax.set_title(
        f"Selfish Time Warp success vs α "
        f"(attacker-favorable, λΔ = {lambda_delta:g})"
    )
    ax.set_ylim(-0.02, 1.02)
    ax.grid(True, which="both", linestyle="-", alpha=0.4)
    ax.legend(title="MTP window size", loc="best")

    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=150)
    print(f"プロットを保存しました: {png_path}", flush=True)
    if show:
        plt.show()
    else:
        plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--lambda-delta",
        type=float,
        default=DEFAULT_LAMBDA_DELTA,
        help=f"λΔ (= Δ/λ)（既定: {DEFAULT_LAMBDA_DELTA}）",
    )
    p.add_argument(
        "--alphas",
        type=str,
        default=",".join(str(a) for a in DEFAULT_ALPHAS),
        help=(
            "カンマ区切りの α（攻撃者ハッシュレート割合）。"
            f"既定: {','.join(str(a) for a in DEFAULT_ALPHAS)}"
        ),
    )
    p.add_argument(
        "--window-sizes",
        type=str,
        default=",".join(str(w) for w in DEFAULT_WINDOW_SIZES),
        help=(
            "カンマ区切りの MTP ウィンドウサイズ W。"
            f"既定: {','.join(str(w) for w in DEFAULT_WINDOW_SIZES)}"
        ),
    )
    p.add_argument("--trials", type=int, default=40, help="各 (W, α) の試行回数")
    p.add_argument(
        "--end-round",
        type=int,
        default=None,
        help=(
            "評価対象 end_round。省略時は "
            f"{DEFAULT_SIM_EPOCHS}×--epoch-len（既定 {BITCOIN_DAA_EPOCH_LEN}）"
        ),
    )
    p.add_argument("--protocol", type=str, default="bitcoin")
    p.add_argument("--total-hashrate", type=int, default=None)
    p.add_argument(
        "--num-honest-nodes",
        type=int,
        default=1,
        help="honest ノード数（defender hashrate を等分、既定 1）",
    )
    p.add_argument("--epoch-len", type=int, default=BITCOIN_DAA_EPOCH_LEN)
    p.add_argument(
        "--rolling-window",
        type=int,
        default=11,
        help="エポック合格判定で各中間ブロックを見る直前ブロック数（既定 11）",
    )
    p.add_argument(
        "--attacker-blocks-in-window",
        type=int,
        default=6,
        help="rolling-window 内に必要な攻撃者ブロック数（既定 6）",
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
        help="評価から除外する先頭エポック数（既定 1）",
    )
    p.add_argument("--binary", type=Path, default=None)
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力 CSV（既定 results/mtp_window_size_sweep.csv）",
    )
    p.add_argument(
        "--plot-output",
        type=Path,
        default=None,
        help="出力 PNG（既定 results/plots/mtp_window_size_sweep.png）",
    )
    p.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="trial ごと metrics の中間ディレクトリ",
    )
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--base-seed", type=int, default=None)
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--skip-run", action="store_true", help="既存 CSV からプロットだけ生成")
    p.add_argument("--show", action="store_true", help="プロットを画面表示")
    p.add_argument(
        "--figsize",
        type=float,
        nargs=2,
        default=(8.0, 5.0),
        metavar=("W", "H"),
    )
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--keep-raw-csv", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    base_dir = SCRIPT_PATH.parent

    if args.keep_raw_csv:
        os.environ["KEEP_RAW"] = "1"

    output_csv = (
        args.output
        if args.output is not None
        else base_dir / "results" / "mtp_window_size_sweep.csv"
    )
    plot_png = (
        args.plot_output
        if args.plot_output is not None
        else base_dir / "results" / "plots" / "mtp_window_size_sweep.png"
    )

    if args.skip_run:
        plot_results(
            output_csv,
            plot_png,
            figsize=(args.figsize[0], args.figsize[1]),
            show=args.show,
        )
        return

    alphas = tuple(float(x.strip()) for x in args.alphas.split(",") if x.strip())
    if not alphas:
        raise ValueError("--alphas が空です")
    for a in alphas:
        if not (0.0 <= a <= 1.0):
            raise ValueError(f"alpha は 0〜1 である必要があります: {a}")

    window_sizes = tuple(
        int(x.strip()) for x in args.window_sizes.split(",") if x.strip()
    )
    if not window_sizes:
        raise ValueError("--window-sizes が空です")
    for w in window_sizes:
        if w < 1:
            raise ValueError(f"window size は 1 以上である必要があります: {w}")

    if args.lambda_delta <= 0:
        raise ValueError("--lambda-delta は正である必要があります")
    if args.trials <= 0:
        raise ValueError("--trials は正である必要があります")
    if args.epoch_len <= 0:
        raise ValueError("--epoch-len は正である必要があります")
    if args.rolling_window < 1:
        raise ValueError("--rolling-window は 1 以上である必要があります")
    if not (1 <= args.attacker_blocks_in_window <= args.rolling_window):
        raise ValueError(
            "--attacker-blocks-in-window は 1 以上 --rolling-window 以下"
        )
    if args.skip_initial_epochs < 0:
        raise ValueError("--skip-initial-epochs は 0 以上")
    if args.num_honest_nodes < 1:
        raise ValueError("--num-honest-nodes は 1 以上")

    epoch_params = EpochSuccessParams(
        epoch_len=args.epoch_len,
        rolling_window=args.rolling_window,
        attacker_blocks_needed=args.attacker_blocks_in_window,
        attacker_node_id=args.attacker_node_id,
        skip_initial_epochs=args.skip_initial_epochs,
    )

    end_round = (
        args.end_round if args.end_round is not None else args.epoch_len * DEFAULT_SIM_EPOCHS
    )
    if end_round <= 0:
        raise ValueError("--end-round は正である必要があります")
    sim_end_round = end_round + SIMULATION_END_ROUND_BUFFER

    total_hr = (
        args.total_hashrate if args.total_hashrate is not None else default_total_hashrate()
    )
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

    delay_ms = delay_ms_for_lambda_delta(args.lambda_delta, args.protocol)
    profile_dir = base_dir / "profiles"
    results_base = (
        args.results_dir
        if args.results_dir is not None
        else base_dir / "results" / "runs"
    )
    prog = not args.no_progress

    total_cells = len(window_sizes) * len(alphas)
    cell_num = 0
    rows: list[dict[str, Any]] = []

    if prog:
        print("=== MTP window size sweep (selfish_timewarp) ===", flush=True)
        print(
            f"lambda_delta={args.lambda_delta}, delay_ms={delay_ms}, "
            f"propagation={PROPAGATION_DELAY_MODE}",
            flush=True,
        )
        print(f"window_sizes ({len(window_sizes)}): {window_sizes}", flush=True)
        print(f"alphas ({len(alphas)}): {alphas}", flush=True)
        print(
            f"trials={args.trials}, parallel={args.parallel}, "
            f"end_round={end_round} (sim --end-round={sim_end_round})",
            flush=True,
        )
        print(f"Total grid cells: {total_cells}", flush=True)
        print("", flush=True)

    for window_size in window_sizes:
        for alpha in alphas:
            cell_num += 1
            profile_path = ensure_selfish_timewarp_profile(
                alpha=alpha,
                mtp_window_size=window_size,
                total_hashrate=total_hr,
                profile_dir=profile_dir,
                num_honest_nodes=args.num_honest_nodes,
            )
            tag = f"w{window_size:02d}"
            results_dir = results_base / f"alpha_{int(round(alpha * 100_000)):06d}"
            # 並列ジョブ間の mkdir 競合（WSL2 等で稀に起きる）を避けるため、
            # 並列投入前にメインスレッドで先に作成しておく。
            results_dir.mkdir(parents=True, exist_ok=True)

            if prog:
                print(
                    f"[{cell_num}/{total_cells}] W={window_size} α={alpha:.4f} "
                    f"({args.trials} trial(s)) ...",
                    flush=True,
                )

            rate = mean_success_rate(
                binary_path=binary_path,
                profile_path=profile_path,
                results_dir=results_dir,
                window_size=window_size,
                alpha=alpha,
                trials=args.trials,
                end_round=sim_end_round,
                protocol=args.protocol,
                delay_ms=delay_ms,
                base_seed=args.base_seed,
                parallel=args.parallel,
                tag=tag,
                lambda_delta=args.lambda_delta,
                epoch_params=epoch_params,
            )

            rows.append(
                {
                    "mtp_window_size": window_size,
                    "lambda_delta": args.lambda_delta,
                    "alpha": round(alpha, 10),
                    "attacker_percent": round(alpha * 100.0, 6),
                    "timewarp_success_rate": rate,
                    "trials": args.trials,
                }
            )
            # セルが終わるたびに CSV を上書き保存しておき、途中で失敗してもそこまでは残る。
            write_csv(output_csv, rows)

            if prog:
                print(
                    f"  -> mean timewarp_success_rate = {rate:.4f}",
                    flush=True,
                )

    write_csv(output_csv, rows)
    if prog:
        print("", flush=True)
        print(
            f"=== Done. Wrote {len(rows)} row(s) to {output_csv} ===",
            flush=True,
        )
    else:
        print(f"Wrote CSV: {output_csv} ({len(rows)} rows)", flush=True)

    plot_results(
        output_csv,
        plot_png,
        figsize=(args.figsize[0], args.figsize[1]),
        show=args.show,
    )


if __name__ == "__main__":
    main()
