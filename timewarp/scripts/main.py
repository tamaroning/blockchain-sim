from __future__ import annotations

import argparse
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
            ("honest-honest", base_dir / "results/honest.csv"),
            ("honest-timewarp", base_dir / "results/timewarp.csv"),
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


def load_series(label: str, csv_path: Path) -> Tuple[pd.Series, pd.Series]:
    if not csv_path.exists():
        raise FileNotFoundError(f"{label} のCSVが見つかりません: {csv_path}")

    df = pd.read_csv(csv_path)
    for col in ("round", "difficulty"):
        if col not in df.columns:
            raise ValueError(f"{csv_path} に必要な列 '{col}' がありません")

    df = df.sort_values("round")
    return df["round"], df["difficulty"]


def plot_difficulty(
    datasets: Iterable[Tuple[str, Path]], output_path: Path | None, show: bool
) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))

    for label, csv_path in datasets:
        x, y = load_series(label, csv_path)
        ax.plot(x, y, label=label)

    ax.set_xlabel("Block height")
    ax.set_ylabel("Difficulty")
    ax.set_title("Difficulty over block height")
    ax.grid(True, alpha=0.3)
    ax.legend()
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
    return parser


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]  # timewarp/
    parser = build_parser()
    args = parser.parse_args()

    datasets = parse_inputs(args.input, base_dir)

    default_output = base_dir / "results/difficulty.png"
    output_path = args.output or default_output

    plot_difficulty(datasets, output_path=output_path, show=args.show)


if __name__ == "__main__":
    main()