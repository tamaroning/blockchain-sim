"""
required_hashrate_fifty_percent.csv（run_required_hashrate_fifty_percent.py の出力）を読み、
lambda_delta ごとの 50% 成功に必要な攻撃者ハッシュレート割合と
honest_only_stale_rate を 2 段プロットする（下段。旧 CSV は stale_rate 列を流用）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
BASE_DIR = SCRIPT_PATH.parents[1]
DEFAULT_CSV = BASE_DIR / "results" / "required_hashrate_fifty_percent.csv"
DEFAULT_PNG = BASE_DIR / "results" / "plots" / "required_hashrate_fifty_percent.png"

REQUIRED_COLUMNS = frozenset(
    {
        "strategy",
        "lambda_delta",
        "attacker_percent",
        "stale_rate",
    }
)
STRATEGY_ORDER = ("selfish_timewarp", "timewarp")
STRATEGY_COLORS = {
    "selfish_timewarp": "#1f77b4",
    "timewarp": "#ff7f0e",
}
FIG_TITLE = "Required attacker hashrate at 50% success"
FOOTER = "Unbracketed points are not threshold estimates"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_CSV,
        help=f"集約 CSV（既定: {DEFAULT_CSV.relative_to(BASE_DIR.parents[1])}）",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PNG,
        help=f"出力 PNG（既定: {DEFAULT_PNG.relative_to(BASE_DIR.parents[1])}）",
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="保存に加えてウィンドウで表示する（GUI バックエンドが必要）",
    )
    p.add_argument(
        "--figsize",
        type=float,
        nargs=2,
        default=(9.0, 5.5),
        metavar=("W", "H"),
    )
    return p


def load_fifty_percent_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"CSV が見つかりません: {path}")
    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{path} に必要な列がありません: {sorted(missing)}")
    df = df.copy()
    df["lambda_delta"] = pd.to_numeric(df["lambda_delta"], errors="raise")
    df["attacker_percent"] = pd.to_numeric(df["attacker_percent"], errors="raise")
    if "honest_only_stale_rate" in df.columns:
        df["honest_only_stale_rate"] = pd.to_numeric(
            df["honest_only_stale_rate"], errors="raise"
        )
        stale_col = "honest_only_stale_rate"
    else:
        df["stale_rate"] = pd.to_numeric(df["stale_rate"], errors="raise")
        stale_col = "stale_rate"
    if "honest_hashrate_percent" in df.columns:
        df["honest_hashrate_percent"] = pd.to_numeric(
            df["honest_hashrate_percent"], errors="raise"
        )
    else:
        df["honest_hashrate_percent"] = 100.0 - df["attacker_percent"]
    if (df["lambda_delta"] <= 0).any():
        raise ValueError("lambda_delta は正の値である必要があります（対数軸）")
    return df, stale_col


def _strategy_sort_key(strategy: str) -> tuple[int, str]:
    try:
        return (STRATEGY_ORDER.index(strategy), strategy)
    except ValueError:
        return (len(STRATEGY_ORDER), strategy)


def plot_fifty_percent(
    df: pd.DataFrame, *, stale_col: str, figsize: tuple[float, float]
):
    import matplotlib.pyplot as plt

    strategies = sorted(df["strategy"].unique(), key=_strategy_sort_key)

    fig, (ax_pct, ax_stale) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=figsize,
        layout="constrained",
    )
    fig.suptitle(FIG_TITLE, fontsize=12)

    for strategy in strategies:
        sub = df.loc[df["strategy"] == strategy].sort_values("lambda_delta")
        color = STRATEGY_COLORS.get(strategy, None)
        label = strategy
        if "status" in sub.columns:
            statuses = sub["status"].dropna().unique()
            if len(statuses) == 1:
                label = f"{strategy} / {statuses[0]}"
            elif len(statuses) > 1:
                label = strategy
        ax_pct.plot(
            sub["lambda_delta"],
            sub["attacker_percent"],
            marker="o",
            linestyle="-",
            color=color,
            label=label,
            linewidth=1.5,
        )
        ax_stale.plot(
            sub["honest_hashrate_percent"],
            sub[stale_col],
            marker="o",
            linestyle="-",
            color=color,
            label=label,
            linewidth=1.5,
        )

    ax_pct.set_xscale("log")
    ax_stale.grid(True, which="both", linestyle="-", alpha=0.5)
    ax_pct.grid(True, which="both", linestyle="-", alpha=0.5)
    for ax in (ax_pct, ax_stale):
        ax.legend(title="strategy / status", loc="best")

    ax_pct.set_ylabel("attacker_percent [%]")
    ax_pct.set_xlabel("lambda_delta")
    ax_stale.set_ylabel(stale_col)
    ax_stale.set_xlabel("honest_hashrate_percent [%]")

    fig.text(0.01, 0.01, FOOTER, fontsize=8, ha="left", va="bottom", color="0.35")
    return fig


def main() -> None:
    args = build_parser().parse_args()

    import matplotlib

    if not args.show:
        matplotlib.use("Agg")

    csv_path = args.input.resolve()
    png_path = args.output.resolve()

    df, stale_col = load_fifty_percent_csv(csv_path)
    fig = plot_fifty_percent(
        df, stale_col=stale_col, figsize=(args.figsize[0], args.figsize[1])
    )

    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=150)
    print(f"保存しました: {png_path}")

    if args.show:
        import matplotlib.pyplot as plt

        plt.show()
    else:
        import matplotlib.pyplot as plt

        plt.close(fig)


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)
