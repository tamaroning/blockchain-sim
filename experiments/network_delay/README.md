# network_delay

ネットワーク遅延比 (`Δ/T`) を変えた実験です。

## ディレクトリ構成

- `scripts/`: 実験実行・可視化スクリプト
- `results/data/`: シミュレーション結果CSV（Git管理外）
- `results/plots/`: 生成した画像（Git管理対象）

## 使い方

```sh
cd /Users/raikitamura/work/blockchain-sim
cargo build --release

# CSVを生成
uv run python experiments/network_delay/scripts/run_delay_sweep.py --protocol=bitcoin
uv run python experiments/network_delay/scripts/run_delay_sweep.py --protocol=ethereum

# 難易度プロット
uv run python experiments/network_delay/scripts/plot_difficulty_curves.py --protocol=bitcoin
uv run python experiments/network_delay/scripts/plot_difficulty_curves.py --protocol=ethereum

# 時間推移プロット
uv run python experiments/network_delay/scripts/plot_mining_time_series.py experiments/network_delay/results/data/bitcoin-0.1.csv
```

## Pythonスクリプト

- `scripts/run_delay_sweep.py`
  - **説明**: `Δ/T` の複数条件で Rust シミュレータを実行し、CSV を `results/data/` に出力します。
  - **実行例**:
    ```sh
    uv run python experiments/network_delay/scripts/run_delay_sweep.py --protocol bitcoin --delta-T-values 0.001,0.01,0.1
    ```
- `scripts/plot_difficulty_curves.py`
  - **説明**: `results/data/` の CSV を読み、difficulty 推移を比較した画像を `results/plots/` に保存します。
  - **実行例**:
    ```sh
    uv run python experiments/network_delay/scripts/plot_difficulty_curves.py --protocol bitcoin --deltas 0.001,0.01,0.1
    ```
- `scripts/plot_mining_time_series.py`
  - **説明**: 単一CSVから mining time と difficulty の時系列グラフを生成します。
  - **実行例**:
    ```sh
    uv run python experiments/network_delay/scripts/plot_mining_time_series.py experiments/network_delay/results/data/bitcoin-0.1.csv
    ```
