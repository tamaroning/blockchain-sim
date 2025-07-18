My blockchain simulator

```sh
RUST_LOG="debug" cargo run
```

実験:
```
cargo build --release
cd experiment
uv run main.py
uv run plot.py --protocol=ethereum
uv run plot.py --protocol=bitcoin
```