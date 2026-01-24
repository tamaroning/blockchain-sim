## timewarp_fix_hashrate

`timewarp` 実験をベースに、「攻撃ノードのハッシュレート（例: 90%）」を固定したまま同じ条件でシミュレーションを複数回実行し、その結果をまとめて可視化するための補助スクリプトです。

### 事前準備

```sh
cd /Users/raikitamura/work/blockchain-sim
cargo build --release
uv sync  # まだであれば
```

### 使い方

```sh
cd timewarp_fix_hashrate
cargo build --release
uv run scripts/main.py \
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

- `timewarp_fix_hashrate/profiles/timewarp{HASH}.json` が自動生成されます（例: `timewarp90.json`）
- 各試行の結果が `timewarp_fix_hashrate/results/timewarp{HASH}_runXXX.csv` として保存されます
- 全試行の difficulty 曲線をまとめて描いたグラフが
  `timewarp_fix_hashrate/results/difficulty_timewarp{HASH}_runs.png` に保存されます

ハッシュレートを変えたい場合は `--hashrate` の値だけ変えて再実行すれば OK です。

