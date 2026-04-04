# Determining Required Attacker Hashrate by Simulation

シミュレーション実行:
```sh
uv run python experiments/determine_required_hashrate/scripts/run_required_hashrate_sweep.py \
  --parallel 10 --runs 10 --min-pct 84 --max-pct 90 --quiet
```

plot:
```
uv run python experiments/determine_required_hashrate/scripts/plot_required_hashrate_sweep.py
```

300エポックのシミュレーションを行い、time warp攻撃により難易度が無限降下するのに必要な攻撃者のハッシュレート割合を調べる

## Parameters

- ネットワーク遅延: 1.5s
- ターゲットブロック生成時間: 600s
- 総ハッシュレート: 800エクサハッシュ/s
- 期間: 300*2016ブロック

## Method

各ハッシュレートに対して70~100%の範囲で攻撃者のハッシュレート割合を1%ずつ変化させ、各100回のシミュレーションを行う。

最終状態で$D \eq 279,396,772,384.62 / 4$ を下回っていれば、難易度が1に到達したとみなす。
279,396,772,384.62はT_gen=T_propとなる難易度である。

## Results

results/以下にCSVとして、攻撃者のハッシュレート割合と、難易度が1に到達するまでのブロック数を記録したファイルが保存されている。
難易度が1に到達しない場合は-1が記録されている。

