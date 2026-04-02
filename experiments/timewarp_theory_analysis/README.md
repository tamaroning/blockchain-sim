# timewarp_theory_analysis

timewarp の理論面（漸化式・確率計算など）を検証するための補助スクリプト群です。

## ディレクトリ構成

- `scripts/`: 理論検証スクリプト
- `results/`: 生成画像などの出力先

## 使い方（例）

```sh
cd /Users/raikitamura/work/blockchain-sim
uv run python experiments/timewarp_theory_analysis/scripts/plot_success_prob.py
uv run python experiments/timewarp_theory_analysis/scripts/plot_success_prob_selfish.py
```

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
