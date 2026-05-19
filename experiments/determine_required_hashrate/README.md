# Determining Required Attacker Hashrate by Simulation

実行

```bash
uv run python experiments/determine_required_hashrate/scripts/run_required_hashrate_fifty_percent.py --trials 100 --parallel 20
```

プロット
```bash
uv run python experiments/determine_required_hashrate/scripts/plot_required_hashrate_fifty_percent.py
```

<!--

シミュレーション実行:
```sh
uv run python experiments/determine_required_hashrate/scripts/run_required_hashrate_sweep.py \
  --parallel 10 --runs 30 --min-pct 86 --max-pct 90 --quiet --step 0.5

uv run python experiments/determine_required_hashrate/scripts/run_required_hashrate_sweep.py \
  --parallel 10 --runs 30 --min-pct 47 --max-pct 50 --quiet --selfish-timewarp --step 0.5
```

plot:
```bash
uv run python experiments/determine_required_hashrate/scripts/plot_required_hashrate_sweep.py --min 86 --max 89

uv run python experiments/determine_required_hashrate/scripts/plot_required_hashrate_sweep.py --min 47 --max 50 --selfish-timewarp
```

300エポックのシミュレーションを行い、time warp攻撃により難易度が無限降下するのに必要な攻撃者のハッシュレート割合を調べる

## Parameters

- ネットワーク遅延: 1.5s
- ターゲットブロック生成時間: 600s
- 総ハッシュレート: 800エクサハッシュ/s
- 期間: 300*2016ブロック

## Method

各ハッシュレートに対して70~100%の範囲で攻撃者のハッシュレート割合を1%ずつ変化させ、各100回のシミュレーションを行う。

最終チェーン上でいずれかのブロックの `difficulty` が閾値 `d_th` 未満になった最初の高さまでのブロック数を記録する（`run_required_hashrate_fifty_percent.py` の difficulty モード既定は `d_th=1024`。`--difficulty-threshold` で変更。ジェネシスは `round > 0` のみ評価）。
到達しない場合は -1 が記録される。

## Results

results/以下にCSVとして、攻撃者のハッシュレート割合と、閾値 `d_th` 未満の難易度に達するまでのブロック数を記録したファイルが保存されている（未到達なら -1）。


-->
