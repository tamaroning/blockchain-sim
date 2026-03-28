# timewarp実験

timewarp と honest の割合を変えながら DAA の推移を比較する。加えて selfish+timewarp（攻撃者ハッシュレート 48.7%）の結果を `results/selfish_timewarp.csv` に出し、同じグラフに重ね描画する。

```sh
cd timewarp
ROUND=400000
RUST_LOG="info" cargo run --release --manifest-path ../Cargo.toml -- --end-round $ROUND --protocol bitcoin --profile profiles/honest.json --output results/honest.csv
RUST_LOG="info" cargo run --release --manifest-path ../Cargo.toml -- --end-round $ROUND --protocol bitcoin --profile profiles/selfish_timewarp.json --output results/selfish_timewarp.csv
for TW_HASH in 85 90 100; do
  RUST_LOG="debug" cargo run --release --manifest-path ../Cargo.toml -- --end-round $ROUND --protocol bitcoin --profile profiles/timewarp${TW_HASH}.json --output results/timewarp${TW_HASH}.csv
done
uv run scripts/main.py
```


```sh
cd timewarp
RUST_LOG="debug" cargo run --release --manifest-path ../Cargo.toml -- --end-round 400000 --protocol bitcoin --profile profiles/test.json
```
