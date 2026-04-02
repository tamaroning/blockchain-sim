## timewarp_fix_hashrate

`timewarp` 実験をベースに、「攻撃ノードのハッシュレート（例: 90%）」を固定したまま同じ条件でシミュレーションを複数回実行し、その結果をまとめて可視化するための補助スクリプトです。

### 事前準備

```sh
cd <repo-root>
uv sync  # まだであれば
```

### 使い方

```sh
cd experiments/timewarp_fix_hashrate
uv run scripts/run_fixed_hashrate_experiments.py \
  --runs 10 \
  --hashrate 90 \
  --end-round 80000 \
  --protocol bitcoin \
  --show
```

- **`--runs`**: 同じ条件で何回シミュレーションを回すか（デフォルト: 10）
- **`--hashrate`**: `timewarp` ノードのハッシュレート [%]（デフォルト: 90）。残りは `honest` ノードに割り当てられます。
- **`--end-round`**: シミュレーションの `--end-round` に渡す値（デフォルト: 40000）
- **`--protocol`**: Rust 側の `--protocol` 引数（デフォルト: `bitcoin`）

実行すると:

- `experiments/timewarp_fix_hashrate/profiles/timewarp{HASH}.json` が自動生成されます（例: `timewarp90.json`）
- 各試行の結果が `experiments/timewarp_fix_hashrate/results/timewarp_hashrate_{HASH}_run_XXX.csv` として保存されます
- 全試行の difficulty 曲線をまとめて描いたグラフが
  `experiments/timewarp_fix_hashrate/results/difficulty_timewarp_hashrate_{HASH}_runs.png` に保存されます

ハッシュレートを変えたい場合は `--hashrate` の値だけ変えて再実行すれば OK です。

### Pythonスクリプト

- `scripts/run_fixed_hashrate_experiments.py`
  - **説明**: 指定ハッシュレートの `timewarp` プロファイルを生成し、同条件で複数回シミュレーションして結果を重ね描画します（実行前に `cargo build --release` を自動実行）。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_fix_hashrate/scripts/run_fixed_hashrate_experiments.py \
      --runs 10 \
      --hashrate 90 \
      --end-round 80000 \
      --protocol bitcoin \
      --show
    ```

