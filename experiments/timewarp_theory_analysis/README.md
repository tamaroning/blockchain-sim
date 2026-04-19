# timewarp_theory_analysis

timewarp の理論面（漸化式・確率計算など）を検証するための補助スクリプト群です。

## ディレクトリ構成

- `scripts/`: 理論検証スクリプト
- `results/`: 生成画像などの出力先

## 使い方（例）

```sh
cd <repo-root>
uv run python experiments/timewarp_theory_analysis/scripts/plot_success_prob.py
uv run python experiments/timewarp_theory_analysis/scripts/plot_success_prob_selfish.py
```

### 単一時点の捕獲確率（`plot_temporal_success_prob.py`）

```sh
# 通常（selfish なし）→ results/temporal_success_prob.png
uv run python experiments/timewarp_theory_analysis/scripts/plot_temporal_success_prob.py --mode honest

# Selfish 考慮 → results/temporal_success_prob_selfish.png
uv run python experiments/timewarp_theory_analysis/scripts/plot_temporal_success_prob.py --mode selfish

# 同一図で比較（出力は results/temporal_success_prob_compare.png）
uv run python experiments/timewarp_theory_analysis/scripts/plot_temporal_success_prob.py --mode both --plot-max
```

`--help` で `--windows` や `--gamma` などのオプション一覧を確認できます。後方互換のため `scripts/plot_temporal_success_prob_selfish.py` から実行しても `--mode selfish` と同じです。

## Pythonスクリプト

- `scripts/plot_success_prob.py`
  - **説明**: 通常モデルの `alpha` に対する成功確率曲線を計算し、`results/success_prob.png` に保存します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/plot_success_prob.py
    ```

- `scripts/plot_success_prob_selfish.py`
  - **説明**: Selfish Mining を考慮した成功確率曲線を計算し、`results/success_prob_selfish.png` に保存します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/plot_success_prob_selfish.py
    ```

- `scripts/plot_temporal_success_prob.py`
  - **説明**: 単一観測での多数派捕獲確率を `--mode honest|selfish|both` で描画します。`--mode both --plot-max` では各窓 W ごとに honest と selfish の点ごとの最大 `max(honest, selfish)` を重ねます（単独モードでは窓間の最大を 1 本追加）。
  - **実行例**: 上記「単一時点の捕獲確率」を参照。
