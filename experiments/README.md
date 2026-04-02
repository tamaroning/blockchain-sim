# Experiments Workspace

このディレクトリは、シミュレーション本体 (`src/`) とは独立した実験・可視化用の資材をまとめています。

## 共通構成

各実験フォルダは次の構成を基本とします。

- `README.md`: 実験の目的と実行手順
- `scripts/`: 実行・可視化スクリプト
- `results/`: 出力物（CSVや画像）
- `profiles/`: シミュレーション設定（必要な実験のみ）

## 個別フォルダ

- `network_delay/`
  - 旧 `experiment/`。ネットワーク遅延比 (`Δ/T`) を変えた実験と可視化。
- `timewarp_attack_scenarios/`
  - timewarp 攻撃シナリオの実行プロファイル、CSV 結果、プロットスクリプト。
- `timewarp_fix_hashrate/`
  - 攻撃者ハッシュレート固定で複数回実行する補助ツール。
- `timewarp_theory_analysis/`
  - timewarp の解析・理論検証用の補助スクリプト群。

## READMEポリシー

各実験フォルダの `README.md` には次を必ず記載します。

- 配下の Python スクリプト一覧
- 各スクリプトの役割（何を計算・出力するか）
- 実行コマンド例（`uv run python ...`）

## 運用ルール

- 実験データは `results/` 配下に保存する。
- `experiments` 配下の `*.csv` は Git で追跡しない（コミットしない）。
- 画像（`*.png`）は必要に応じてコミットしてよい。
- 新しい実験テーマは `experiments/<topic>/` を作成して追加する。
- Rust の本体コード (`src/`) と実験スクリプトは混在させない。
