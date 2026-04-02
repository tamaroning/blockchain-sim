# timewarp実験

timewarp と honest の割合を変えながら DAA の推移を比較する。加えて selfish+timewarp（攻撃者ハッシュレート 48.7%）の結果を `results/selfish_timewarp.csv` に出し、同じグラフに重ね描画する。

```sh
cd experiments/timewarp_attack_scenarios
ROUND=400000
RUST_LOG="info" cargo run --release --manifest-path ../../Cargo.toml -- --end-round $ROUND --protocol bitcoin --profile profiles/honest.json --output results/honest.csv
RUST_LOG="info" cargo run --release --manifest-path ../../Cargo.toml -- --end-round $ROUND --protocol bitcoin --profile profiles/selfish_timewarp.json --output results/selfish_timewarp.csv
for TW_HASH in 85 90 100; do
  RUST_LOG="debug" cargo run --release --manifest-path ../../Cargo.toml -- --end-round $ROUND --protocol bitcoin --profile profiles/timewarp${TW_HASH}.json --output results/timewarp${TW_HASH}.csv
done
uv run scripts/plot_timewarp_scenarios.py
```


```sh
cd experiments/timewarp_attack_scenarios
RUST_LOG="debug" cargo run --release --manifest-path ../../Cargo.toml -- --end-round 400000 --protocol bitcoin --profile profiles/test.json
```

## Pythonスクリプト

- `scripts/plot_timewarp_scenarios.py`
  - **説明**: `results/` 内の複数CSV（honest / selfish+timewarp / timewarp比率）を重ねて difficulty グラフを作成します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_attack_scenarios/scripts/plot_timewarp_scenarios.py
    ```
- `scripts/plot_block_timestamps.py`
  - **説明**: `timestamp` 列を使って、ブロック高さに対するブロック時刻の推移を可視化します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_attack_scenarios/scripts/plot_block_timestamps.py --csv experiments/timewarp_attack_scenarios/results/test.csv
    ```
