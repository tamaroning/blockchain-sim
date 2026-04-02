#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="results/test.csv を読み取り、縦軸=timestamp(分)、横軸=ブロック高さの折れ線グラフを作成します。",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "results" / "test.csv",
        help="入力CSVへのパス (デフォルト: experiments/timewarp_attack_scenarios/results/test.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "results" / "block_time.png",
        help="出力するPNGファイルパス",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="Block Timestamp (minutes)",
        help="グラフタイトル",
    )
    parser.add_argument(
        "--log-scale",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="縦軸を対数スケールにする (デフォルト: 有効)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    df = pd.read_csv(args.csv)
    if not {"round", "timestamp"} <= set(df.columns):
        raise ValueError("CSVに round と timestamp 列が必要です。")

    x = df["round"]
    # timestampをms→分に変換
    y = df["timestamp"] / 60_000

    plt.figure(figsize=(12, 6))
    plt.plot(x, y, color="#4C72B0", linewidth=1.3)
    plt.xlabel("Block Height (round)")
    plt.ylabel("Timestamp (minutes)")
    plt.title(args.title)
    if args.log_scale:
        plt.yscale("log")
    else:
        plt.ylim(0, None)
    plt.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=200)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()