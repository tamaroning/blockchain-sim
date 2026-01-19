# timewarp実験

```sh
cd timewarp

RUST_LOG="info" cargo run --release -- --end-round 1000000 --protocol bitcoin --profile profiles/timewarp.json --output results/timewarp.csv
RUST_LOG="info" cargo run --release -- --end-round 1000000 --protocol bitcoin --profile profiles/honest.json --output results/honest.csv
```
