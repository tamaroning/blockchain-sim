from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import pandas as pd


def ensure_profile(attacker_hashrate: int, base_dir: Path) -> Path:
    """
    与えられたハッシュレートに対応する timewarp プロファイル JSON を
    timewarp_fix_hashrate/profiles/ 以下に生成（または上書き）してパスを返す。
    """
    if not (0 <= attacker_hashrate <= 100):
        raise ValueError("--hashrate は 0〜100 の整数で指定してください")

    defender_hashrate = 100 - attacker_hashrate

    profile_dir = base_dir / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_path = profile_dir / f"timewarp{attacker_hashrate}.json"

    profile = {
        "nodes": [
            {
                "hashrate": attacker_hashrate,
                "strategy": {"type": "timewarp"},
            },
            {
                "hashrate": defender_hashrate,
                "strategy": {"type": "honest"},
            },
        ]
    }

    with profile_path.open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    return profile_path


def run_one_simulation(
    run_index: int,
    attacker_hashrate: int,
    end_round: int,
    delay: int | None,
    protocol: str,
    binary_path: Path,
    profile_path: Path,
    results_dir: Path,
) -> Path:
    """
    1 回分のシミュレーションを実行し、結果 CSV のパスを返す。
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    output_csv = results_dir / f"timewarp{attacker_hashrate}_run{run_index:03d}.csv"

    cmd = [
        str(binary_path),
        f"--end-round={end_round}",
        f"--protocol={protocol}",
        f"--profile={profile_path}",
        f"--output={output_csv}",
    ]
    if delay is not None:
        cmd.append(f"--delay={delay}")

    print(f"[run {run_index}] 実行コマンド: {' '.join(cmd)}")

    env = {"RUST_LOG": "info"}

    result = subprocess.run(
        cmd,
        env=env,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"run {run_index} でエラーが発生しました (exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
        )

    return output_csv


def load_difficulty_series(csv_path: Path) -> tuple[pd.Series, pd.Series]:
    if not csv_path.exists():
        raise FileNotFoundError(f"結果 CSV が見つかりません: {csv_path}")

    df = pd.read_csv(csv_path)
    if "round" not in df.columns or "difficulty" not in df.columns:
        raise ValueError(f"{csv_path} に round / difficulty 列が存在しません")

    df = df.sort_values("round")
    return df["round"], df["difficulty"]


def plot_runs(
    csv_paths: List[Path],
    attacker_hashrate: int,
    output_path: Path | None,
    show: bool,
    log_y: bool,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))

    for i, csv_path in enumerate(csv_paths, start=1):
        x, y = load_difficulty_series(csv_path)
        ax.plot(
            x,
            y,
            label=f"run {i}",
            alpha=0.4,
        )

    ax.set_xlabel("Block height")
    ax.set_ylabel("Difficulty")
    ax.set_title(f"Difficulty over block height (timewarp hashrate={attacker_hashrate}%)")
    if log_y:
        ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)
        print(f"プロットを保存しました: {output_path}")

    if show:
        plt.show()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "timewarp のハッシュレートを固定して同じ条件で複数回シミュレーションを実行し、"
            "difficulty の推移をまとめて可視化します。"
        )
    )

    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="同じ条件で実行する回数（デフォルト: 10）",
    )
    parser.add_argument(
        "--hashrate",
        type=int,
        default=90,
        help="timewarp ノードのハッシュレート [%]（0〜100、デフォルト: 90）",
    )
    parser.add_argument(
        "--end-round",
        type=int,
        default=40000,
        help="Rust シミュレータの --end-round に渡す値（デフォルト: 40000）",
    )
    parser.add_argument(
        "--protocol",
        type=str,
        default="bitcoin",
        help="Rust シミュレータの --protocol に渡す値（デフォルト: bitcoin）",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=None,
        help="Rust シミュレータの --delay に渡す値（ms）。省略時は Rust 側のデフォルトを使用",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        default=None,
        help="blockchain-sim バイナリのパス（省略時は ../target/release/blockchain-sim を使用）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="プロット画像の保存先パス（省略時は timewarp_fix_hashrate/results/difficulty_timewarp{HASH}_runs.png）",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="プロットを画面表示する場合に指定します。",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="グラフ描画をスキップし、シミュレーション実行だけ行います。",
    )
    parser.add_argument(
        "--linear-y",
        action="store_true",
        help="縦軸を線形スケールにします（デフォルトは対数スケール）。",
    )

    return parser


def main() -> None:
    script_path = Path(__file__).resolve()
    base_dir = script_path.parents[1]  # timewarp_fix_hashrate/
    project_root = script_path.parents[2]  # リポジトリルート

    parser = build_parser()
    args = parser.parse_args()

    if args.runs <= 0:
        raise ValueError("--runs は 1 以上を指定してください")

    attacker_hashrate: int = args.hashrate

    # プロファイル生成
    profile_path = ensure_profile(attacker_hashrate, base_dir)
    print(f"使用プロファイル: {profile_path}")

    # 実行バイナリの決定
    if args.binary is not None:
        binary_path = args.binary
    else:
        binary_path = project_root / "target/release/blockchain-sim"

    if not binary_path.exists():
        raise FileNotFoundError(
            f"blockchain-sim バイナリが見つかりません: {binary_path}\n"
            "先に `cargo build --release` を実行してください。"
        )

    results_dir = base_dir / "results"

    # シミュレーションを複数回実行
    csv_paths: List[Path] = []
    for i in range(1, args.runs + 1):
        csv_path = run_one_simulation(
            run_index=i,
            attacker_hashrate=attacker_hashrate,
            end_round=args.end_round,
            delay=args.delay,
            protocol=args.protocol,
            binary_path=binary_path,
            profile_path=profile_path,
            results_dir=results_dir,
        )
        csv_paths.append(csv_path)
        print(f"[run {i}] 完了: {csv_path}")

    if args.no_plot:
        print("`--no-plot` が指定されているため、グラフ描画はスキップします。")
        return

    default_output = (
        base_dir
        / "results"
        / f"difficulty_timewarp{attacker_hashrate}_runs.png"
    )
    output_path = args.output or default_output

    log_y = not args.linear_y

    plot_runs(
        csv_paths=csv_paths,
        attacker_hashrate=attacker_hashrate,
        output_path=output_path,
        show=args.show,
        log_y=log_y,
    )


if __name__ == "__main__":
    main()

