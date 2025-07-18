#!/usr/bin/env python3
import subprocess
import sys

def run_cargo_command(delta, generation_time=600000, end_round=200000):
    """
    指定されたdelta値に基づいてcargoコマンドを実行する

    Args:
        delta (float): delta値 (delay/generation-time)
        generation_time (int): 固定のgeneration-time値
        end_round (int): 固定のend-round値
    """
    # delayを計算 (delta = delay / generation_time)
    delay = int(delta * generation_time)

    # 出力ファイル名を設定
    output_file = f"data/{delta}.csv"

    cmd = [
        "../target/release/blockchain-sim",
        f"--end-round={end_round}",
        f"--delay={delay}",
        f"--generation-time={generation_time}",
        f"--output={output_file}",
    ]

    # 環境変数を設定
    env = {"RUST_LOG": "info"}

    print(f"実行中: delta={delta}, delay={delay}, output={output_file}")
    print(f"コマンド: RUST_LOG=info {' '.join(cmd)}")

    try:
        # コマンドを実行
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✓ delta={delta} の実行が完了しました")
            if result.stdout:
                print(f"出力: {result.stdout}")
        else:
            print(f"✗ delta={delta} の実行でエラーが発生しました")
            print(f"エラー: {result.stderr}")

    except Exception as e:
        print(f"✗ delta={delta} の実行中に例外が発生しました: {e}")

    print("-" * 50)


def main():
    # 指定されたdelta値のリスト
    delta_values = [0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0]

    print("Cargo コマンドの一括実行を開始します...")
    print(f"実行予定のdelta値: {delta_values}")
    print("=" * 50)

    # 各delta値に対してコマンドを実行
    for delta in delta_values:
        run_cargo_command(delta)

    print("全てのコマンドの実行が完了しました。")


if __name__ == "__main__":
    main()
