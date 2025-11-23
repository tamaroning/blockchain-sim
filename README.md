My blockchain simulator

ネットワークトポロジ:
- 完全グラフ
- 定数ネットワーク遅延


k-lead selfish mining
```bash
RUST_LOG="info" cargo run --release -- --profile ../examples/k_lead_effective.json --end-round 1000000
```


```sh
# Run with default settings
RUST_LOG="debug" cargo run --release

# Run Ethereum protocol with 100 nodes for 10,000 rounds
RUST_LOG="info" cargo run --release -- --end-round 10000 --protocol ethereum --num-nodes 100
```

実験:
```bash
cargo build --release
cd experiment

# 実行
uv run main.py --protocol=ethereum
uv run main.py --protocol=bitcoin

# 難易度のプロット
uv run plot-difficulty.py --protocol=ethereum
uv run plot-difficulty.py --protocol=bitcoin

# 難易度とブロック生成時間の変化のプロット
uv run plot-time.py data/bitcoin-0.001.csv
uv run plot-time.py data/bitcoin-0.01.csv
uv run plot-time.py data/bitcoin-0.1.csv
uv run plot-time.py data/bitcoin-0.5.csv
uv run plot-time.py data/bitcoin-1.0.csv
uv run plot-time.py data/ethereum-0.001.csv
uv run plot-time.py data/ethereum-0.01.csv
uv run plot-time.py data/ethereum-0.1.csv
uv run plot-time.py data/ethereum-0.5.csv
uv run plot-time.py data/ethereum-1.0.csv
```

<!--
uv run main.py --protocol=ethereum
uv run plot-difficulty.py --protocol=ethereum
uv run plot-time.py data/ethereum-0.1.csv
-->
