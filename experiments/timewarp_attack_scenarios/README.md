# timewarp実験

timewarp と honest の割合を変えながら DAA の推移を比較する。加えて selfish+timewarp（攻撃者ハッシュレート 48.7%）の結果を `results/selfish_timewarp.csv` に出し、同じグラフに重ね描画する。

プロファイル JSON は `experiments.utils.write_profile_json` 経由で `scripts/generate_profiles.py` が生成する。比率を変えたい場合はスクリプト内の定義を編集してから次を実行する。

```sh
uv run python experiments/timewarp_attack_scenarios/scripts/run_timewarp_scenarios.py --end-round 100000
```

このコマンドで以下をまとめて実行する。

- `profiles/` の生成（`scripts/generate_profiles.py`）
- `honest / selfish_timewarp / timewarp85 / timewarp90 / timewarp100` のシミュレーション（並列実行）
- difficulty の比較グラフ生成（デフォルト有効、`--no-with-plot` で無効化）

## Pythonスクリプト

- `scripts/generate_profiles.py`
  - **説明**: `profiles/*.json` を `experiments.utils.write_profile_json` で書き出す（手編集の重複を避ける）。
  - **実行例**: `uv run python experiments/timewarp_attack_scenarios/scripts/generate_profiles.py`
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
    uv run python experiments/timewarp_attack_scenarios/scripts/plot_block_timestamps.py --csv experiments/timewarp_attack_scenarios/results/timewarp90.csv
    ```
- `scripts/run_timewarp_scenarios.py`
  - **説明**: simulator（`cargo run ...`）の実行をまとめる。複数シナリオを並列で一括実行し、必要なら difficulty グラフ生成まで行う。
  - **実行例**:
    ```sh
    uv run python experiments/timewarp_attack_scenarios/scripts/run_timewarp_scenarios.py --end-round 200000
    uv run python experiments/timewarp_attack_scenarios/scripts/run_timewarp_scenarios.py --end-round 200000 --no-with-plot
    ```
