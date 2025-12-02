#!/usr/bin/env python3
import argparse
import subprocess
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


def run_cargo_command(delta_T, num_nodes, end_round, protocol):
    """
    指定されたdelta値に基づいてcargoコマンドを実行する

    Args:
        delta_T: Δ/T値 (ネットワーク遅延 / ブロック生成時間)
        num_nodes (int): ノード数
        end_round (int): 固定のend-round値
        protocol (str): プロトコル名

    Returns:
        tuple: (delta, success, message)
    """
    if protocol == "bitcoin":
        generation_time = 600_000
    elif protocol == "ethereum":
        generation_time = 15_000
    else:
        raise ValueError(f"Invalid protocol: {protocol}")
    
    delta = int(delta_T * generation_time)

    output_file = f"data/{protocol}-{delta_T}.csv"
    cmd = [
        "../target/release/blockchain-sim",
        f"--num-nodes={num_nodes}",
        f"--end-round={end_round}",
        f"--delay={delta}",
        f"--protocol={protocol}",
        f"--output={output_file}",
    ]

    # 環境変数を設定
    env = {"RUST_LOG": "info"}

    thread_id = threading.current_thread().ident
    print(f"[Thread {thread_id}] Δ/T={delta_T} command: {' '.join(cmd)}")

    try:
        # コマンドを実行
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode == 0:
            message = f"✓ Δ/T={delta_T} (protocol={protocol}) の実行が完了しました"
            if result.stdout:
                message += f"\n出力: {result.stdout}"
            return (delta_T, True, message)
        else:
            message = f"✗ Δ/T={delta_T} (protocol={protocol}) の実行でエラーが発生しました\nエラー: {result.stderr}"
            return (delta_T, False, message)

    except Exception as e:
        message = (
            f"✗ Δ/T={delta_T} (protocol={protocol}) の実行中に例外が発生しました: {e}"
        )
        return (delta_T, False, message)


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
        description="ブロックチェーンシミュレーションのCargoコマンドを並列実行します",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  %(prog)s --protocol ethereum
  %(prog)s --protocol bitcoin --delta-values 0.1,0.5,1.0
  %(prog)s --protocol ethereum --num-nodes 200 --end-round 100000
  %(prog)s --protocol ethereum --max-workers 4  # 最大4スレッドで実行
        """,
    )

    parser.add_argument(
        "--protocol",
        type=str,
        default="ethereum",
        help="使用するプロトコル (デフォルト: ethereum)",
    )

    parser.add_argument(
        "--delta-T-values",
        type=parse_delta_values,
        default=[0.001, 0.01, 0.05, 0.1, 0.25, 0.5],
        help="実行するΔ/T値のリスト（コンマ区切り）(デフォルト: 0.001,0.01,0.05,0.1,0.25,0.5)",
    )

    parser.add_argument(
        "--num-nodes", type=int, default=10, help="ノード数 (デフォルト: 10)"
    )

    parser.add_argument(
        "--end-round", type=int, default=80000, help="end-round値 (デフォルト: 80000)"
    )

    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="最大並列実行数 (デフォルト: CPUコア数、0で順次実行)",
    )

    parser.add_argument(
        "--serial",
        action="store_true",
        help="順次実行モード（並列実行を無効化）",
    )

    args = parser.parse_args()

    # 最大ワーカー数を決定
    if args.serial or args.max_workers == 0:
        max_workers = 1
    elif args.max_workers is None:
        max_workers = min(os.cpu_count(), len(args.delta_T_values))
    else:
        max_workers = min(args.max_workers, len(args.delta_T_values))

    print("Cargo コマンドの一括実行を開始します...")
    print(f"プロトコル: {args.protocol}")
    print(f"実行予定のΔ/T値: {args.delta_T_values}")
    print(f"ノード数: {args.num_nodes}")
    print(f"End Round: {args.end_round}")
    print(f"最大並列実行数: {max_workers}")
    print("=" * 50)

    # dataディレクトリを作成（存在しない場合）
    os.makedirs("data", exist_ok=True)

    if max_workers == 1:
        # 順次実行
        print("順次実行モードで実行中...")
        results = []
        for delta_T in args.delta_T_values:
            result = run_cargo_command(
                delta_T,
                num_nodes=args.num_nodes,
                end_round=args.end_round,
                protocol=args.protocol,
            )
            results.append(result)
            print(result[2])  # メッセージを表示
            print("-" * 50)
    else:
        # 並列実行
        print(f"並列実行モードで実行中（最大{max_workers}スレッド）...")
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 全てのタスクを投入
            future_to_delta_T = {
                executor.submit(
                    run_cargo_command,
                    delta_T,
                    num_nodes=args.num_nodes,
                    end_round=args.end_round,
                    protocol=args.protocol,
                ): delta_T
                for delta_T in args.delta_T_values
            }

            # 完了したタスクの結果を収集
            for future in as_completed(future_to_delta_T):
                delta_T = future_to_delta_T[future]
                try:
                    result = future.result()
                    results.append(result)
                    print(f"[完了] {result[2]}")
                    print("-" * 50)
                except Exception as exc:
                    error_msg = f"✗ Δ/T={delta_T} でエラーが発生しました: {exc}"
                    results.append((delta, False, error_msg))
                    print(f"[エラー] {error_msg}")
                    print("-" * 50)

    # 結果のサマリーを表示
    print("\n" + "=" * 50)
    print("実行結果サマリー:")
    print("=" * 50)

    successful = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]

    print(f"成功: {len(successful)}/{len(results)} 件")
    print(f"失敗: {len(failed)}/{len(results)} 件")

    if successful:
        print(f"\n成功したdelta値: {[r[0] for r in successful]}")

    if failed:
        print(f"\n失敗したdelta値: {[r[0] for r in failed]}")

    print("\n全てのコマンドの実行が完了しました。")


if __name__ == "__main__":
    main()
