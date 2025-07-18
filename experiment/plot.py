#!/usr/bin/env python3
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import glob
import os


def plot_csv_files(csv_pattern="*.csv", output_file="plot.png"):
    """
    指定されたパターンのCSVファイルをプロットする

    Args:
        csv_pattern (str): CSVファイルのパターン（例: "*.csv", "0.*.csv"）
        output_file (str): 出力画像ファイル名
    """
    # CSVファイルを検索
    csv_files = glob.glob(csv_pattern)

    if not csv_files:
        print(
            f"エラー: パターン '{csv_pattern}' に一致するCSVファイルが見つかりません。"
        )
        return

    # delta値でソート（ファイル名から抽出）
    def extract_delta(filename):
        try:
            basename = os.path.basename(filename)
            delta_str = basename.replace(".csv", "")
            return float(delta_str)
        except ValueError:
            return 0.0

    csv_files.sort(key=extract_delta)

    # プロットの設定
    plt.figure(figsize=(12, 8))

    # カラーマップを設定（視覚的に区別しやすい色）
    colors = plt.cm.tab10(np.linspace(0, 1, len(csv_files)))

    for i, csv_file in enumerate(csv_files):
        try:
            # CSVファイルを読み込み
            df = pd.read_csv(csv_file)

            # カラム名を確認・調整
            if "round" in df.columns and "difficulty" in df.columns:
                x_col, y_col = "round", "difficulty"
            elif len(df.columns) >= 2:
                x_col, y_col = df.columns[0], df.columns[1]
                print(
                    f"警告: {csv_file} のカラム名が期待と異なります。{x_col}, {y_col} を使用します。"
                )
            else:
                print(f"エラー: {csv_file} に十分なカラムがありません。")
                continue

            # delta値を抽出
            delta = extract_delta(csv_file)

            # プロット
            plt.plot(
                df[x_col],
                df[y_col],
                color=colors[i],
                label=f"delta={delta}",
                linewidth=2,
                alpha=0.8,
            )

            print(
                f"✓ {csv_file} をプロットしました (delta={delta}, データ数={len(df)})"
            )

        except Exception as e:
            print(f"✗ {csv_file} の読み込みでエラーが発生しました: {e}")

    # グラフの設定
    plt.xlabel("Round", fontsize=12)
    plt.ylabel("Difficulty", fontsize=12)
    plt.title("Difficulty vs Round for Different Delta Values", fontsize=14)
    plt.legend(loc="best", fontsize=10)
    plt.grid(True, alpha=0.3)

    # レイアウトを調整
    plt.tight_layout()

    # 保存と表示
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    print(f"グラフを {output_file} に保存しました。")
    plt.show()


def plot_specific_deltas(delta_values=None, output_file="plot.png"):
    """
    特定のdelta値のCSVファイルのみをプロットする

    Args:
        delta_values (list): プロットするdelta値のリスト
        output_file (str): 出力画像ファイル名
    """
    if delta_values is None:
        delta_values = [0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0]

    plt.figure(figsize=(12, 8))
    colors = plt.cm.tab10(np.linspace(0, 1, len(delta_values)))

    plotted_count = 0

    for i, delta in enumerate(delta_values):
        csv_file = f"data/{delta}.csv"

        if not os.path.exists(csv_file):
            print(f"警告: {csv_file} が見つかりません。")
            continue

        try:
            # CSVファイルを読み込み
            df = pd.read_csv(csv_file)

            # カラム名を確認・調整
            if "round" in df.columns and "difficulty" in df.columns:
                x_col, y_col = "round", "difficulty"
            elif len(df.columns) >= 2:
                x_col, y_col = df.columns[0], df.columns[1]
            else:
                print(f"エラー: {csv_file} に十分なカラムがありません。")
                continue

            # プロット
            plt.plot(
                df[x_col],
                df[y_col],
                color=colors[i],
                label=f"Δ/T={delta}",
                linewidth=2,
                alpha=0.8,
            )

            plotted_count += 1
            print(f"✓ {csv_file} をプロットしました (データ数={len(df)})")

        except Exception as e:
            print(f"✗ {csv_file} の読み込みでエラーが発生しました: {e}")

    if plotted_count == 0:
        print("エラー: プロットできるCSVファイルが見つかりませんでした。")
        return

    # グラフの設定
    plt.xlabel("Round", fontsize=12)
    plt.ylabel("Difficulty", fontsize=12)
    plt.title("Difficulty vs Round for Different Delta Values", fontsize=14)
    plt.legend(loc="best", fontsize=10)
    plt.grid(True, alpha=0.3)

    # レイアウトを調整
    plt.tight_layout()

    # 保存と表示
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    print(f"グラフを {output_file} に保存しました。")
    plt.show()


def main():
    print("CSV プロットスクリプトを実行中...")

    # 方法1: 特定のdelta値のCSVファイルをプロット
    print("\n=== 特定のdelta値でプロット ===")
    plot_specific_deltas()

    # 方法2: 全てのCSVファイルをプロット（コメントアウト）
    # print("\n=== 全CSVファイルをプロット ===")
    # plot_csv_files()


if __name__ == "__main__":
    main()
