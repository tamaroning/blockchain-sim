"""
required_hashrate_sweep*.csv（run_required_hashrate_sweep.py の出力）を読み、
攻撃者ハッシュレート割合ごとの閾値到達率をプロットする。
blocks_to_threshold == -1 はシミュレーション終了まで未到達。
--selfish-timewarp で selfish スイープ用のデフォルト入出力に切り替え可能。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
BASE_DIR = SCRIPT_PATH.parents[1]
DEFAULT_CSV = BASE_DIR / "results" / "required_hashrate_sweep.csv"
DEFAULT_CSV_SELFISH = BASE_DIR / "results" / "required_hashrate_sweep_selfish_timewarp.csv"
DEFAULT_PNG = BASE_DIR / "results" / "plots" / "required_hashrate_sweep.png"
DEFAULT_PNG_SELFISH = BASE_DIR / "results" / "plots" / "required_hashrate_sweep_selfish_timewarp.png"
# README のスイープ範囲（70〜100%）に合わせる
X_AXIS_PCT_MIN = 84
X_AXIS_PCT_MAX = 91


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            "集約 CSV（省略時: timewarp 用または --selfish-timewarp 用のデフォルト）"
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力 PNG（省略時: timewarp 用または --selfish-timewarp 用のデフォルト）",
    )
    p.add_argument(
        "--selfish-timewarp",
        action="store_true",
        help=(
            "デフォルトの入出力を selfish_timewarp スイープ用 "
            f"（{DEFAULT_CSV_SELFISH.name} / {DEFAULT_PNG_SELFISH.name}）にする"
        ),
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="保存に加えてウィンドウで表示する（GUI バックエンドが必要）",
    )
    p.add_argument(
        "--min",
        type=float,
        default=None,
        dest="pct_min",
        metavar="PCT",
        help=f"x 軸（攻撃者ハッシュレート [%%]）の下限（省略時: {X_AXIS_PCT_MIN}）",
    )
    p.add_argument(
        "--max-pct",
        type=float,
        default=None,
        dest="pct_max",
        metavar="PCT",
        help=f"x 軸（攻撃者ハッシュレート [%%]）の上限（省略時: {X_AXIS_PCT_MAX}）",
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

    csv_path = (
        args.input
        if args.input is not None
        else (DEFAULT_CSV_SELFISH if args.selfish_timewarp else DEFAULT_CSV)
    )
    png_path = (
        args.output
        if args.output is not None
        else (DEFAULT_PNG_SELFISH if args.selfish_timewarp else DEFAULT_PNG)
    )

    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = load_sweep_csv(csv_path.resolve())
    summary = summarize_by_percent(df)

    x_min = X_AXIS_PCT_MIN if args.pct_min is None else args.pct_min
    x_max = X_AXIS_PCT_MAX if args.pct_max is None else args.pct_max
    if x_min >= x_max:
        raise ValueError(f"--min ({x_min}) は --max-pct ({x_max}) より小さい必要があります")

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
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3)
    title = (
        "Selfish timewarp sweep: attacker share vs. reaching D_th"
        if args.selfish_timewarp
        else "Timewarp sweep: attacker share vs. reaching D_th"
    )
    ax.set_title(title)

    out = png_path.resolve()
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
