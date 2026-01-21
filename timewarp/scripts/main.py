from __future__ import annotations

import argparse
import itertools
from pathlib import Path
from typing import Iterable, List, Tuple

import matplotlib.pyplot as plt
import pandas as pd


def parse_inputs(
    raw_inputs: Iterable[str] | None, base_dir: Path
) -> List[Tuple[str, Path]]:
    """
    raw_inputs expects items like "label=/abs/path.csv" or "label=relative/path.csv".
    If none are provided, fall back to the default two datasets.
    """
    if not raw_inputs:
        return [
            ("honest", base_dir / "results/honest.csv"),
            ("timewarp50", base_dir / "results/timewarp50.csv"),
            ("timewarp60", base_dir / "results/timewarp60.csv"),
            ("timewarp70", base_dir / "results/timewarp70.csv"),
            ("timewarp80", base_dir / "results/timewarp80.csv"),
            ("timewarp90", base_dir / "results/timewarp90.csv"),
            ("timewarp100", base_dir / "results/timewarp100.csv"),
        ]

    parsed: List[Tuple[str, Path]] = []
    for item in raw_inputs:
        if "=" not in item:
            raise ValueError(f"--input の形式は label=path で指定してください: {item}")
        label, path_str = item.split("=", maxsplit=1)
        path = Path(path_str)
        path = path if path.is_absolute() else base_dir / path
        parsed.append((label, path))
    return parsed


def load_series(label: str, csv_path: Path) -> Tuple[pd.Series, pd.Series, pd.Series]:
    if not csv_path.exists():
        raise FileNotFoundError(f"{label} のCSVが見つかりません: {csv_path}")

    df = pd.read_csv(csv_path)
    for col in ("round", "difficulty", "mining_time"):
        if col not in df.columns:
            raise ValueError(f"{csv_path} に必要な列 '{col}' がありません")

    df = df.sort_values("round")
    # 最初のブロックのgeneration timeは初期条件の影響が大きいので無視する
    if not df.empty:
        df.loc[df.index[0], "mining_time"] = pd.NA
    # msを分に換算し、1000ブロック移動平均を取る
    mining_time_avg_min = (
        df["mining_time"].rolling(window=1000, min_periods=1).mean() / 60000.0
    )
    return df["round"], df["difficulty"], mining_time_avg_min


def plot_difficulty(
    datasets: Iterable[Tuple[str, Path]],
    output_path: Path | None,
    show: bool,
    log_y: bool,
    show_mining_time: bool,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax2 = ax.twinx() if show_mining_time else None

    colors = itertools.cycle(
        plt.rcParams.get("axes.prop_cycle", plt.cycler(color=["C0"]))
        .by_key()
        .get("color", ["C0"])
    )

    for label, csv_path in datasets:
        x, difficulty, mining_time = load_series(label, csv_path)
        color = next(colors)
        ax.plot(x, difficulty, label=label, color=color)
        if ax2 is not None:
            ax2.plot(
                x,
                mining_time,
                label="_nolegend_",
                color=color,
                linestyle="--",
                alpha=0.35,
            )

    ax.set_xlabel("Block height")
    ax.set_ylabel("Difficulty")
    ax.set_title("Difficulty over block height")
    if ax2 is not None:
        ax2.set_ylabel("Mining time [min] (1000-block avg)")
        ax2.set_ylim(0, 50)  # 右軸を0〜50に固定
    if log_y:
        ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    handles1, labels1 = ax.get_legend_handles_labels()
    ax.legend(handles1, labels1, loc="best")
    fig.tight_layout()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)

    if show:
        plt.show()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "複数のシナリオ結果CSVを読み込み、block height を横軸、difficulty を縦軸にプロットします。"
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        action="append",
        metavar="LABEL=PATH",
        help="追加で描画するCSVを label=path 形式で指定（複数可）。未指定ならデフォルト2種を使用。",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="保存先ファイルパス（省略時は timewarp/results/difficulty.png に保存）。",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="プロットを画面表示する場合に指定します。",
    )
    parser.add_argument(
        "--log-y",
        action="store_true",
        help="縦軸を対数スケールにします。",
        default=True,
    )
    parser.add_argument(
        "--show-mining-time",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="右軸に generation time(mining_time) の移動平均を表示します（デフォルト: 表示）。",
    )
    return parser


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]  # timewarp/
    parser = build_parser()
    args = parser.parse_args()

    datasets = parse_inputs(args.input, base_dir)

    default_output = base_dir / "results/difficulty.png"
    output_path = args.output or default_output

    plot_difficulty(
        datasets,
        output_path=output_path,
        show=args.show,
        log_y=args.log_y,
        show_mining_time=args.show_mining_time,
    )


if __name__ == "__main__":
    main()