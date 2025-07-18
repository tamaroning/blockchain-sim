My blockchain simulator

```sh
RUST_LOG="debug" cargo run
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
uv run plot-time.py data/bitcoin-0.1.csv
uv run plot-time.py data/ethereum-0.1.csv
```

<!--
uv run main.py --protocol=ethereum
uv run plot-difficulty.py --protocol=ethereum
uv run plot-time.py data/ethereum-0.1.csv
-->
