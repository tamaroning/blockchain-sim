#!/usr/bin/env python3
import argparse
import subprocess
import sys


def run_cargo_command(
    delta, num_nodes=100, generation_time=600000, end_round=80000, protocol="ethereum"
):
    """
    指定されたdelta値に基づいてcargoコマンドを実行する

    Args:
        delta (float): delta値 (delay/generation-time)
        num_nodes (int): ノード数
        generation_time (int): 固定のgeneration-time値
        end_round (int): 固定のend-round値
        protocol (str): プロトコル名
    """
    # delayを計算 (delta = delay / generation_time)
    delay = int(delta * generation_time)

    # 出力ファイル名を設定
    output_file = f"data/{protocol}-{delta}.csv"

    cmd = [
        "../target/release/blockchain-sim",
        f"--num-nodes={num_nodes}",
        f"--end-round={end_round}",
        f"--delay={delay}",
        f"--generation-time={generation_time}",
        f"--protocol={protocol}",
        f"--output={output_file}",
    ]

    # 環境変数を設定
    env = {"RUST_LOG": "info"}

    print(
        f"実行中: delta={delta}, delay={delay}, protocol={protocol}, output={output_file}"
    )
    print(f"コマンド: RUST_LOG=info {' '.join(cmd)}")

    try:
        # コマンドを実行
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✓ Δ/T={delta} (protocol={protocol}) の実行が完了しました")
            if result.stdout:
                print(f"出力: {result.stdout}")
        else:
            print(f"✗ Δ/T={delta} (protocol={protocol}) の実行でエラーが発生しました")
            print(f"エラー: {result.stderr}")

    except Exception as e:
        print(f"✗ Δ/T={delta} (protocol={protocol}) の実行中に例外が発生しました: {e}")

    print("-" * 50)


def parse_delta_values(delta_str):
    """
    コンマ区切りのdelta値文字列をfloatのリストに変換する
    """
    try:
        return [float(x.strip()) for x in delta_str.split(",")]
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid delta values: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="ブロックチェーンシミュレーションのCargoコマンドを一括実行します",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  %(prog)s --protocol ethereum
  %(prog)s --protocol bitcoin --delta-values 0.1,0.5,1.0
  %(prog)s --protocol ethereum --num-nodes 200 --end-round 100000
        """,
    )

    parser.add_argument(
        "--protocol",
        type=str,
        default="ethereum",
        help="使用するプロトコル (デフォルト: ethereum)",
    )

    parser.add_argument(
        "--delta-values",
        type=parse_delta_values,
        default=[0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0],
        help="実行するdelta値のリスト（コンマ区切り）(デフォルト: 0.001,0.01,0.05,0.1,0.25,0.5,0.75,1.0)",
    )

    parser.add_argument(
        "--num-nodes", type=int, default=100, help="ノード数 (デフォルト: 100)"
    )

    parser.add_argument(
        "--generation-time",
        type=int,
        default=600000,
        help="generation-time値 (デフォルト: 600000)",
    )

    parser.add_argument(
        "--end-round", type=int, default=80000, help="end-round値 (デフォルト: 80000)"
    )

    args = parser.parse_args()

    print("Cargo コマンドの一括実行を開始します...")
    print(f"プロトコル: {args.protocol}")
    print(f"実行予定のdelta値: {args.delta_values}")
    print(f"ノード数: {args.num_nodes}")
    print(f"Generation Time: {args.generation_time}")
    print(f"End Round: {args.end_round}")
    print("=" * 50)

    # 各delta値に対してコマンドを実行
    for delta in args.delta_values:
        run_cargo_command(
            delta,
            num_nodes=args.num_nodes,
            generation_time=args.generation_time,
            end_round=args.end_round,
            protocol=args.protocol,
        )

    print("全てのコマンドの実行が完了しました。")


if __name__ == "__main__":
    main()
