"""
required_hashrate_sweep.csv（run_required_hashrate_sweep.py の出力）を読み、
攻撃者ハッシュレート割合ごとの閾値到達率をプロットする。
blocks_to_threshold == -1 はシミュレーション終了まで未到達。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
BASE_DIR = SCRIPT_PATH.parents[1]
DEFAULT_CSV = BASE_DIR / "results" / "required_hashrate_sweep.csv"
DEFAULT_PNG = BASE_DIR / "results" / "plots" / "required_hashrate_sweep.png"
# README のスイープ範囲（70〜100%）に合わせる
X_AXIS_PCT_MIN = 70
X_AXIS_PCT_MAX = 100


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_CSV,
        help=f"集約 CSV（デフォルト: {DEFAULT_CSV}）",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PNG,
        help=f"出力 PNG（デフォルト: {DEFAULT_PNG}）",
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="保存に加えてウィンドウで表示する（GUI バックエンドが必要）",
    )
    p.add_argument("--figsize", type=float, nargs=2, default=(10.0, 5.0), metavar=("W", "H"))
    return p


def load_sweep_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"CSV が見つかりません: {path}")
    df = pd.read_csv(path)
    required = {
        "attacker_percent",
        "run_index",
        "blocks_to_threshold",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} に必要な列がありません: {sorted(missing)}")
    return df


def summarize_by_percent(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("attacker_percent", sort=True)
    return g.agg(
        success_rate=("blocks_to_threshold", lambda s: float((s != -1).mean())),
    ).reset_index()


def main() -> None:
    args = build_parser().parse_args()

    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = load_sweep_csv(args.input.resolve())
    summary = summarize_by_percent(df)

    fig, ax = plt.subplots(figsize=(args.figsize[0], args.figsize[1]), layout="constrained")

    ax.plot(
        summary["attacker_percent"],
        summary["success_rate"] * 100.0,
        marker="o",
        color="#4C72B0",
        linewidth=1.5,
    )
    ax.set_xlabel("Attacker hashrate share [%]")
    ax.set_ylabel("Success rate [%]")
    ax.set_xlim(X_AXIS_PCT_MIN, X_AXIS_PCT_MAX)
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3)
    ax.set_title(
        "Timewarp sweep: attacker share vs. reaching D_th (run_required_hashrate_sweep.csv)"
    )

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"保存しました: {out}")

    if args.show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)
