from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DEFAULT_NETWORK_DELAY_MS = 600
DEFAULT_SCENARIO_FILES = [
    "honest.csv",
    "selfish_timewarp.csv",
    "timewarp85.csv",
    "timewarp90.csv",
    "timewarp100.csv",
]


def parse_inputs(
    raw_inputs: Iterable[str] | None, base_dir: Path
) -> List[Tuple[str, Path]]:
    """
    raw_inputs expects items like "label=/abs/path.csv" or "label=relative/path.csv".
    If none are provided, fall back to the default datasets (honest, selfish-timewarp, timewarp sweeps).
    """
    if not raw_inputs:
        results_dir = base_dir / "results"
        profiles_dir = base_dir / "profiles"
        parsed_defaults: List[Tuple[str, Path]] = []
        # run_timewarp_scenarios.py の run_full() で生成する系列と順序を揃える。
        for filename in DEFAULT_SCENARIO_FILES:
            csv_path = results_dir / filename
            profile_path = profiles_dir / f"{Path(filename).stem}.json"
            label = _label_from_profile(profile_path, fallback_label=Path(filename).stem)
            parsed_defaults.append((label, csv_path))
        return parsed_defaults

    parsed: List[Tuple[str, Path]] = []
    for item in raw_inputs:
        if "=" not in item:
            raise ValueError(f"--input の形式は label=path で指定してください: {item}")
        label, path_str = item.split("=", maxsplit=1)
        path = Path(path_str)
        path = path if path.is_absolute() else base_dir / path
        parsed.append((label, path))
    return parsed


def _label_from_profile(profile_path: Path, fallback_label: str) -> str:
    """
    profile JSON から「攻撃戦略(type!=honest)のハッシュレート比率」を凡例ラベルとして組み立てる。
    例:
      - selfish_timewarp.json (49/51) -> selfish-timewarp-49%
      - timewarp90.json (90/10)       -> timewarp-90%
      - honest.json (all honest)      -> honest-100%
    """
    if not profile_path.exists():
        return fallback_label.replace("_", "-")

    try:
        with profile_path.open("r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return fallback_label.replace("_", "-")

    nodes = profile.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return fallback_label.replace("_", "-")

    total_hashrate = 0.0
    attacker_shares: dict[str, float] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        hashrate = node.get("hashrate", 0)
        if not isinstance(hashrate, (int, float)):
            continue
        total_hashrate += float(hashrate)
        strategy = node.get("strategy", {})
        if isinstance(strategy, dict):
            strategy_type = strategy.get("type", "unknown")
        else:
            strategy_type = "unknown"
        if strategy_type != "honest":
            attacker_shares[str(strategy_type)] = (
                attacker_shares.get(str(strategy_type), 0.0) + float(hashrate)
            )

    if total_hashrate <= 0:
        return fallback_label.replace("_", "-")

    if not attacker_shares:
        return "honest-100%"

    parts: list[str] = []
    for strategy_type in sorted(attacker_shares.keys()):
        pct = attacker_shares[strategy_type] / total_hashrate * 100.0
        pct_str = f"{pct:.1f}".rstrip("0").rstrip(".")
        parts.append(f"{strategy_type.replace('_', '-')}-{pct_str}%")

    return "+".join(parts)


def load_series(label: str, csv_path: Path) -> Tuple[pd.Series, pd.Series, pd.Series]:
    if not csv_path.exists():
        raise FileNotFoundError(f"{label} のCSVが見つかりません: {csv_path}")

    df = pd.read_csv(csv_path)
    for col in ("round", "difficulty", "mining_time"):
        if col not in df.columns:
            raise ValueError(f"{csv_path} に必要な列 '{col}' がありません")

    df = df.sort_values("round")
    # 最初のブロックのgeneration timeは初期条件の影響が大きいので無視する
    if not df.empty:
        df.loc[df.index[0], "mining_time"] = pd.NA
    # msを分に換算し、1000ブロック移動平均を取る
    mining_time_avg_min = (
        df["mining_time"].rolling(window=1000, min_periods=1).mean() / 60000.0
    )
    return df["round"], df["difficulty"], mining_time_avg_min


def _load_total_hashrate(profile_path: Path) -> float | None:
    if not profile_path.exists():
        return None
    try:
        with profile_path.open("r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return None
    nodes = profile.get("nodes")
    if not isinstance(nodes, list):
        return None
    total = 0.0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        hashrate = node.get("hashrate")
        if isinstance(hashrate, (int, float)):
            total += float(hashrate)
    return total if total > 0 else None


def _target_difficulty_for_delay(delay_ms: int, total_hashrate: float) -> float:
    # Bitcoin model: E[mining_time] = difficulty * 2^32 / hashrate
    # E[mining_time] = delay_ms を満たす difficulty。
    return delay_ms * total_hashrate / (2**32)


def _fit_trendline(
    x: pd.Series,
    y: pd.Series,
    *,
    use_log_y: bool,
    start: int | None,
    end: int | None,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """
    x を説明変数、y を目的変数として一次回帰を行い、傾き・切片と描画用のフィット値を返す。
    - use_log_y=True の場合は log10(y) に対して回帰し、描画時は 10** で元スケールへ戻す。
    - start/end は x の範囲（block height）指定。None は無制限。
    """
    x_np = x.to_numpy(dtype=float)
    y_np = y.to_numpy(dtype=float)

    mask = np.isfinite(x_np) & np.isfinite(y_np)
    if start is not None:
        mask &= x_np >= float(start)
    if end is not None:
        mask &= x_np <= float(end)

    x_fit = x_np[mask]
    y_fit_src = y_np[mask]
    if x_fit.size < 2:
        raise ValueError("回帰に必要なデータ点が不足しています（2点以上必要）")

    if use_log_y:
        # difficulty が 0 以下だと対数が取れないため除外
        pos = y_fit_src > 0
        x_fit = x_fit[pos]
        y_fit_src = y_fit_src[pos]
        if x_fit.size < 2:
            raise ValueError(
                "log回帰に必要なデータ点が不足しています（difficulty>0 かつ 2点以上必要）"
            )
        y_reg = np.log10(y_fit_src)
    else:
        y_reg = y_fit_src

    slope, intercept = np.polyfit(x_fit, y_reg, 1)

    # 描画用：元の x 全体に対して予測値を生成（補助線として見やすい）
    y_hat_reg = slope * x_np + intercept
    if use_log_y:
        y_hat = np.power(10.0, y_hat_reg)
    else:
        y_hat = y_hat_reg

    return float(slope), float(intercept), x_np, y_hat


def _find_descending_step_segments(
    difficulty: pd.Series, *, min_steps: int
) -> list[tuple[int, int, int]]:
    """
    difficulty が「増えない(diff<=0)」状態が連続する区間のうち、
    「下がる段差(diff<0)」が min_steps 回以上含まれる区間を返す。
    ただし、区間末尾で最小値に張り付く横ばい（例: difficulty=1 の張り付き）は
    回帰対象から除外する。

    戻り値: (start_idx, end_idx, step_count)
      - start_idx/end_idx は difficulty のインデックス位置（0-based, 両端含む）
      - step_count はその区間内の diff<0 の回数
    """
    if min_steps <= 0:
        raise ValueError("min_steps は 1 以上で指定してください")

    y = difficulty.to_numpy(dtype=float)
    n = y.size
    if n < 2:
        return []

    diffs = np.diff(y)  # length n-1
    non_increasing = diffs <= 0
    decreasing = diffs < 0

    segments: list[tuple[int, int, int]] = []
    i = 0
    while i < non_increasing.size:
        if not non_increasing[i]:
            i += 1
            continue
        # start of a non-increasing run in diffs
        run_start = i
        j = i
        while j < non_increasing.size and non_increasing[j]:
            j += 1
        run_end = j - 1

        step_count = int(decreasing[run_start : run_end + 1].sum())
        if step_count >= min_steps:
            # diffs[k] corresponds to transition y[k] -> y[k+1]
            start_idx = run_start
            end_idx = run_end + 1
            # 回帰は「下降している区間のみ」を対象にしたいので、
            # 区間末尾で最小値に張り付く横ばい（difficulty=1 付近）を落とす。
            # 浮動小数誤差を考慮して isclose を使う。
            floor = y[end_idx]
            while end_idx > start_idx and np.isclose(y[end_idx], floor, rtol=0.0, atol=1e-12):
                end_idx -= 1
            if end_idx > start_idx:
                segments.append((start_idx, end_idx, step_count))

        i = j

    return segments


def plot_difficulty(
    datasets: Iterable[Tuple[str, Path]],
    profiles_dir: Path,
    delay_ms: int,
    output_path: Path | None,
    show: bool,
    log_y: bool,
    show_mining_time: bool,
    show_regression: bool,
    regression_log_y: bool | None,
    regression_start: int | None,
    regression_end: int | None,
    regression_mode: str,
    min_descending_steps: int,
    epoch_len: int,
) -> None:
    datasets = list(datasets)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax2 = ax.twinx() if show_mining_time else None

    colors = itertools.cycle(
        plt.rcParams.get("axes.prop_cycle", plt.cycler(color=["C0"]))
        .by_key()
        .get("color", ["C0"])
    )
    # 先頭系列に依存せず、読める profile が1つでもあれば基準線を描く。
    threshold_drawn = False
    for _label, csv_path in datasets:
        profile_path = profiles_dir / f"{csv_path.stem}.json"
        total_hashrate = _load_total_hashrate(profile_path)
        if total_hashrate is not None:
            target_difficulty = _target_difficulty_for_delay(delay_ms, total_hashrate)
            ax.axhline(
                target_difficulty,
                linestyle="--",
                linewidth=1.8,
                color="black",
                alpha=0.8,
                label=f"E[T]=delay ({delay_ms} ms), D={target_difficulty:.3g}",
            )
            threshold_drawn = True
            break

    for label, csv_path in datasets:
        x, difficulty, mining_time = load_series(label, csv_path)
        color = next(colors)
        ax.plot(x, difficulty, label=label, color=color)

        if show_regression:
            use_log = regression_log_y if regression_log_y is not None else log_y
            if regression_mode == "global":
                try:
                    slope, _intercept, x_line, y_line = _fit_trendline(
                        x,
                        difficulty,
                        use_log_y=use_log,
                        start=regression_start,
                        end=regression_end,
                    )
                    if use_log:
                        ratio_epoch = 10.0 ** (slope * float(epoch_len))
                        pct_epoch = (ratio_epoch - 1.0) * 100.0
                        trend_label = f"{label} trend {pct_epoch:+.2f}%/epoch"
                    else:
                        delta_epoch = slope * float(epoch_len)
                        trend_label = f"{label} trend Δ{delta_epoch:+.3g}/epoch"
                    ax.plot(
                        x_line,
                        y_line,
                        label=trend_label,
                        color=color,
                        linestyle=":",
                        linewidth=2.0,
                        alpha=0.9,
                    )
                except Exception as e:
                    print(f"[warn] {label}: 回帰の描画に失敗しました: {e}")
            elif regression_mode == "descending_segments":
                # 「段差が min_descending_steps 回以上、増えずに連続」する区間だけ回帰線を引く
                try:
                    segs = _find_descending_step_segments(
                        difficulty, min_steps=min_descending_steps
                    )
                    if not segs:
                        print(
                            f"[info] {label}: 条件（段差>= {min_descending_steps}）を満たす連続下降区間がありません"
                        )
                    for (start_i, end_i, step_cnt) in segs:
                        x_seg = x.iloc[start_i : end_i + 1]
                        y_seg = difficulty.iloc[start_i : end_i + 1]
                        slope, _intercept, x_line, y_line = _fit_trendline(
                            x_seg,
                            y_seg,
                            use_log_y=use_log,
                            start=regression_start,
                            end=regression_end,
                        )
                        if use_log:
                            ratio_epoch = 10.0 ** (slope * float(epoch_len))
                            pct_epoch = (ratio_epoch - 1.0) * 100.0
                            trend_label = f"{label} trend {pct_epoch:+.2f}%/epoch"
                        else:
                            delta_epoch = slope * float(epoch_len)
                            trend_label = f"{label} trend Δ{delta_epoch:+.3g}/epoch"
                        ax.plot(
                            x_line,
                            y_line,
                            label=trend_label,
                            color=color,
                            linestyle=":",
                            linewidth=2.0,
                            alpha=0.9,
                        )
                except Exception as e:
                    print(f"[warn] {label}: 下降区間回帰の描画に失敗しました: {e}")
            else:
                raise ValueError(
                    f"未知の regression_mode: {regression_mode}（global / descending_segments）"
                )
        if ax2 is not None:
            ax2.plot(
                x,
                mining_time,
                label="_nolegend_",
                color=color,
                linestyle="--",
                alpha=0.35,
            )
    if not threshold_drawn:
        print("[warn] 基準線用の profile を読めなかったため、E[T]=delay 線は描画されませんでした。")

    ax.set_xlabel("Block height")
    ax.set_ylabel("Difficulty")
    ax.set_title("Difficulty over block height")
    if ax2 is not None:
        ax2.set_ylabel("Mining time [min] (1000-block avg)")
        ax2.set_ylim(0, 50)  # 右軸を0〜50に固定
    if log_y:
        ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    handles1, labels1 = ax.get_legend_handles_labels()
    ax.legend(handles1, labels1, loc="best")
    fig.tight_layout()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)

    if show:
        plt.show()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "複数のシナリオ結果CSVを読み込み、block height を横軸、difficulty を縦軸にプロットします。"
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        action="append",
        metavar="LABEL=PATH",
        help="追加で描画するCSVを label=path 形式で指定（複数可）。未指定ならデフォルトの複数系列を使用。",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="保存先ファイルパス（省略時は experiments/timewarp_attack_scenarios/results/difficulty_timewarp_scenarios.png に保存）。",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="プロットを画面表示する場合に指定します。",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=DEFAULT_NETWORK_DELAY_MS,
        help="ネットワーク遅延 [ms]。E[T]=delay となる難易度の基準線描画に使用（デフォルト: 600）。",
    )
    parser.add_argument(
        "--log-y",
        action=argparse.BooleanOptionalAction,
        help="縦軸を対数スケールにします。",
        default=True,
    )
    parser.add_argument(
        "--show-mining-time",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="右軸に generation time(mining_time) の移動平均を表示します（デフォルト: 表示）。",
    )
    parser.add_argument(
        "--show-regression",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="difficulty の一次回帰（傾き算出）を補助線として描画します（デフォルト: 表示）。",
    )
    parser.add_argument(
        "--regression-log-y",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "回帰を log10(difficulty) に対して行うかを明示します。"
            "未指定(None)なら --log-y の設定に追従します。"
        ),
    )
    parser.add_argument(
        "--regression-start",
        type=int,
        default=None,
        help="回帰に使う block height の開始（inclusive）。未指定なら先頭から。",
    )
    parser.add_argument(
        "--regression-end",
        type=int,
        default=None,
        help="回帰に使う block height の終了（inclusive）。未指定なら末尾まで。",
    )
    parser.add_argument(
        "--regression-mode",
        choices=("descending_segments", "global"),
        default="descending_segments",
        help=(
            "回帰線の引き方を指定します。"
            "descending_segments: 連続下降（増えない）かつ段差が一定回数以上の区間だけ。"
            "global: 系列全体（または start/end 指定範囲）に対して1本。"
        ),
    )
    parser.add_argument(
        "--min-descending-steps",
        type=int,
        default=5,
        help="descending_segments モードで、区間として採用する最小の段差回数（diff<0 の回数）。",
    )
    parser.add_argument(
        "--epoch-len",
        type=int,
        default=2016,
        help="1epoch のブロック数（Bitcoin想定のデフォルト: 2016）。凡例の「/epoch」換算に使用します。",
    )
    return parser


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]  # timewarp_attack_scenarios/
    parser = build_parser()
    args = parser.parse_args()

    datasets = parse_inputs(args.input, base_dir)

    default_output = base_dir / "results/difficulty_timewarp_scenarios.png"
    output_path = args.output or default_output

    plot_difficulty(
        datasets,
        profiles_dir=base_dir / "profiles",
        delay_ms=args.delay,
        output_path=output_path,
        show=args.show,
        log_y=args.log_y,
        show_mining_time=args.show_mining_time,
        show_regression=args.show_regression,
        regression_log_y=args.regression_log_y,
        regression_start=args.regression_start,
        regression_end=args.regression_end,
        regression_mode=args.regression_mode,
        min_descending_steps=args.min_descending_steps,
        epoch_len=args.epoch_len,
    )


if __name__ == "__main__":
    main()