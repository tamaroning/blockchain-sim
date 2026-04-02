# timewarp_theory_analysis

timewarp の理論面（漸化式・確率計算など）を検証するための補助スクリプト群です。

## ディレクトリ構成

- `scripts/`: 理論検証スクリプト
- `results/`: 生成画像などの出力先

## 使い方（例）

```sh
cd /Users/raikitamura/work/blockchain-sim
uv run python experiments/timewarp_theory_analysis/scripts/plot_window_success_probability.py
```

## Pythonスクリプト

- `scripts/calc_window_success_probability.py`
  - **説明**: 「直近11ブロックでAが6回以上」を満たし続ける確率 `P(N, alpha)` を計算します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/calc_window_success_probability.py 2016 0.9
    ```
- `scripts/plot_alpha_probability_curve.py`
  - **説明**: `alpha * P(N, alpha)` の曲線をサンプリング・補間してプロットします。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/plot_alpha_probability_curve.py --samples 40 --target 0.5 --N 2016
    ```
- `scripts/plot_window_success_probability.py`
  - **説明**: `alpha` に対する確率曲線を計算し、`results/kuji.png` に保存します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/plot_window_success_probability.py
    ```
- `scripts/analyze_daa_convergence.py`
  - **説明**: timewarp の漸化式を反復計算し、difficulty と見かけ時間の収束挙動を可視化します。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/analyze_daa_convergence.py
    ```
- `scripts/simulate_simple_timewarp.py`
  - **説明**: 簡易モデルで epoch ごとの difficulty/clock の変化をシミュレーションします。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_theory_analysis/scripts/simulate_simple_timewarp.py
    ```
