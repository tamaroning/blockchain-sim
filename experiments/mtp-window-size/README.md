# MTP Window Size Sweep (Selfish Time Warp)

λΔ = 10⁻² の **attacker favorable** な状況下で、Bitcoin の MTP（Median Time Past）
算出に使う直近ブロック数 W を 3〜13 の奇数で振り、攻撃者ハッシュレート割合 α を
0.40〜0.55 で 0.01 刻みに変えたときの **Selfish Time Warp 攻撃成功率** を計測する。

## Scripts

- `run.py`
  - `selfish_timewarp` 戦略の MTP ウィンドウサイズ W と攻撃者割合 α を二重ループで
    スイープし、各セルで `--trials` 本のシミュレーションを実行する。
  - 攻撃成功率は `experiments/determine_required_hashrate/scripts/run_required_hashrate_fifty_percent.py`
    と同じ「エポックごとの合格率」（先頭・末尾ブロックが攻撃者かつ中間ブロックの
    直前 rolling_window 本のうち attacker_blocks_in_window 本以上が攻撃者）を
    trials 本平均したもの。
  - 出力:
    - `results/mtp_window_size_sweep.csv`
    - `results/plots/mtp_window_size_sweep.png`

## Parameters (defaults)

- propagation delay mode: `attacker-favorable` (H→\* は Δ、A→\* は 0)
- λΔ = 0.01 → `--delay 6000` (ms)
- α: 0.40, 0.41, …, 0.55（0.01 刻み、計 16 点）
- MTP window size W: 13, 11, 9, 7, 5, 3
- protocol: `bitcoin`
- end_round: 2×2016（DAA 2 エポック相当）
- honest ノード数: 1（defender hashrate を 1 ノードに集約）
- 攻撃成功エポック判定: rolling_window=11, attacker_blocks_in_window=6,
  skip_initial_epochs=1（既定値）

## 実行例

通常実行（既定パラメータ、各セル 40 試行、並列 10）:

```bash
uv run python experiments/mtp-window-size/run.py --trials 40 --parallel 10
```

既存 CSV からプロットだけ生成:

```bash
uv run python experiments/mtp-window-size/run.py --skip-run
```

α や W、λΔ を変える例:

```bash
uv run python experiments/mtp-window-size/run.py \
    --alphas 0.40,0.45,0.50,0.55 \
    --window-sizes 13,11,9,7,5,3,1 \
    --lambda-delta 0.01 \
    --trials 50 --parallel 16
```

## Rust 側の対応

本実験のために `src/mining_strategy/timewarp.rs` と
`src/mining_strategy/selfish_timewarp.rs` に MTP ウィンドウサイズの設定機能を追加し、
プロファイル JSON から指定できるようにしている。

```json
{
  "nodes": [
    {
      "hashrate": 320000000000000000,
      "strategy": {
        "type": "selfish_timewarp",
        "mtp_window_size": 13
      }
    },
    {
      "hashrate": 480000000000000000,
      "strategy": { "type": "honest" }
    }
  ]
}
```

`mtp_window_size` を省略した場合は Bitcoin 既定の 11 が使われる（既存プロファイルとの後方互換）。
