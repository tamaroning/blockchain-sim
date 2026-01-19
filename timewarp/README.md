# timewarp実験

実験

```sh
ROUND=40000
RUST_LOG="info" cargo run --release -- --end-round $ROUND --protocol bitcoin --profile profiles/honest.json --output results/honest.csv
for TW_HASH in 50 60 70 80 90; do
  RUST_LOG="info" cargo run --release -- --end-round $ROUND --protocol bitcoin --profile profiles/timewarp${TW_HASH}.json --output results/timewarp${TW_HASH}.csv
done
uv run scripts/main.py
```





## ゴミ

```sh
cd timewarp

RUST_LOG="info" cargo run --release -- --end-round 40000 --protocol bitcoin --profile profiles/timewarp.json --output results/timewarp.csv
RUST_LOG="info" cargo run --release -- --end-round 40000 --protocol bitcoin --profile profiles/honest.json --output results/honest.csv
RUST_LOG="info" cargo run --release -- --end-round 40000 --protocol bitcoin --profile profiles/test.json --output results/test.csv

uv run scripts/main.py
```


```sh
RUST_LOG="info" cargo run --release -- --end-round 40000 --protocol bitcoin --profile profiles/timewarp.json --output results/timewarp.csv && uv run scripts/main.py
```

