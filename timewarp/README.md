# timewarp実験

timewarpとhonestの割合を変えながら、DAAの推移を比較する。

```sh
ROUND=40000
RUST_LOG="info" cargo run --release -- --end-round $ROUND --protocol bitcoin --profile profiles/honest.json --output results/honest.csv
for TW_HASH in 50 60 70 80 90; do
  RUST_LOG="info" cargo run --release -- --end-round $ROUND --protocol bitcoin --profile profiles/timewarp${TW_HASH}.json --output results/timewarp${TW_HASH}.csv
done
uv run scripts/main.py
```

