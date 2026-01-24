import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

STATES = 1 << 10  # last 10 bits (L=11 のとき)
PC = np.array([bin(i).count("1") for i in range(STATES)], dtype=np.int16)

def prob_all_windows_ge6(
    alpha: float,
    N: int = 2016,
    L: int = 11,
    K: int = 6,
    verbose: bool = False,
) -> float:
    if verbose:
        print(f"prob_all_windows_ge6(alpha={alpha}, N={N}, L={L}, K={K})")
    assert L == 11 and K == 6, "この実装は L=11, K=6 用（一般化も可能）"

    a = float(alpha)
    v = np.zeros(STATES, dtype=np.float64)

    # 初期分布：最初の10回は自由
    for s in range(STATES):
        c = PC[s]
        v[s] = (a ** c) * ((1 - a) ** (10 - c))

    steps = N - 10  # 11回目..N回目
    for _ in range(steps):
        nv = np.zeros_like(v)
        for s in range(STATES):
            ps = v[s]
            if ps == 0.0:
                continue
            c = PC[s]

            # b=0 (外れ)
            if c >= K:
                s2 = ((s << 1) & (STATES - 1)) | 0
                nv[s2] += ps * (1 - a)

            # b=1 (当たり)
            if c + 1 >= K:
                s2 = ((s << 1) & (STATES - 1)) | 1
                nv[s2] += ps * a

        v = nv

    return float(v.sum())

def _prob_worker(args: tuple[float, int, int, int]) -> float:
    alpha, N, L, K = args
    return prob_all_windows_ge6(alpha, N=N, L=L, K=K, verbose=True)

def _eval_probs(
    alphas: list[float],
    *,
    N: int,
    L: int,
    K: int,
    parallel: bool,
    max_workers: int | None,
) -> list[float]:
    if not alphas:
        return []
    if parallel and len(alphas) >= 8:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_prob_worker, [(a, N, L, K) for a in alphas]))
    return [prob_all_windows_ge6(a, N=N, L=L, K=K, verbose=False) for a in alphas]

def adaptive_sample_probs(
    *,
    N: int,
    L: int,
    K: int,
    alpha_min: float,
    alpha_max: float,
    max_points: int,
    initial_points: int = 21,
    rounds: int = 6,
    parallel: bool = True,
    max_workers: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    曲率（非線形性）が大きい区間を優先して点を増やす。
    具体的には、各区間の中点での「直線補間誤差」が大きい区間を優先して細分化する。
    """
    initial_points = max(2, min(int(initial_points), int(max_points)))

    alphas = np.linspace(alpha_min, alpha_max, initial_points, dtype=np.float64)
    a_list = [float(a) for a in alphas]
    p_list = _eval_probs(a_list, N=N, L=L, K=K, parallel=parallel, max_workers=max_workers)

    # float の同値判定を安定させるために丸めたキーで管理（0..1なのでスケール固定でOK）
    def key(a: float) -> int:
        return int(round(a * 10**15))

    prob_by_a: dict[int, tuple[float, float]] = {key(a): (a, p) for a, p in zip(a_list, p_list)}

    for _ in range(max(0, int(rounds))):
        cur = sorted(prob_by_a.values(), key=lambda t: t[0])
        a_sorted = [a for a, _ in cur]
        p_sorted = [p for _, p in cur]

        if len(a_sorted) >= max_points:
            break

        # 全区間の中点を候補にして、一括評価 → 誤差の大きい区間から追加
        mids: list[float] = []
        mid_meta: list[tuple[int, float, float, float]] = []  # (idx, a0, a1, p_lin_mid)
        for i in range(len(a_sorted) - 1):
            a0, a1 = a_sorted[i], a_sorted[i + 1]
            p0, p1 = p_sorted[i], p_sorted[i + 1]
            am = 0.5 * (a0 + a1)
            km = key(am)
            if km in prob_by_a:
                continue
            p_lin = 0.5 * (p0 + p1)
            mids.append(am)
            mid_meta.append((i, a0, a1, p_lin))

        if not mids:
            break

        pmids = _eval_probs(mids, N=N, L=L, K=K, parallel=parallel, max_workers=max_workers)

        # 誤差（=曲率の強さ）で優先度を付ける
        candidates: list[tuple[float, float, float]] = []  # (priority, am, pm)
        for am, pm, (_, a0, a1, p_lin) in zip(mids, pmids, mid_meta):
            err = abs(pm - p_lin)
            width = (a1 - a0)
            priority = err * width  # 幅も加味（狭い区間の微小誤差を過剰に優先しない）
            candidates.append((priority, am, pm))

        candidates.sort(reverse=True, key=lambda t: t[0])
        remaining = max_points - len(prob_by_a)
        for _, am, pm in candidates[:remaining]:
            prob_by_a[key(am)] = (am, pm)

        if len(prob_by_a) >= max_points:
            break

    final = sorted(prob_by_a.values(), key=lambda t: t[0])
    alphas_out = np.array([a for a, _ in final], dtype=np.float64)
    probs_out = np.array([p for _, p in final], dtype=np.float64)
    return alphas_out, probs_out

def plot_prob_vs_alpha(
    N: int = 2016,
    L: int = 11,
    K: int = 6,
    alpha_min: float = 0.0,
    alpha_max: float = 1.0,
    points: int = 50,
    out_path: str | Path = "results/kuji.png",
    show: bool = False,
    adaptive: bool = True,
    initial_points: int = 21,
    rounds: int = 6,
    parallel: bool = True,
    max_workers: int | None = None,
) -> None:
    # matplotlib は「描画する時だけ」import（確率計算だけ回したい時に依存しないようにする）
    import matplotlib
    matplotlib.use("Agg")  # ヘッドレス環境でも保存できるようにする
    import matplotlib.pyplot as plt

    if adaptive:
        alphas, probs = adaptive_sample_probs(
            N=N,
            L=L,
            K=K,
            alpha_min=alpha_min,
            alpha_max=alpha_max,
            max_points=int(points),
            initial_points=int(initial_points),
            rounds=int(rounds),
            parallel=parallel,
            max_workers=max_workers,
        )
    else:
        alphas = np.linspace(alpha_min, alpha_max, int(points), dtype=np.float64)
        probs = np.array(
            _eval_probs(
                [float(a) for a in alphas],
                N=N,
                L=L,
                K=K,
                parallel=parallel,
                max_workers=max_workers,
            ),
            dtype=np.float64,
        )

    plt.figure(figsize=(7, 4))
    plt.plot(alphas, probs, lw=2)
    plt.title(f"P(all windows >= {K} successes in last {L}) vs alpha (N={N})")
    plt.xlabel("alpha")
    plt.ylabel("probability")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    out_path = Path(out_path)
    if not out_path.is_absolute():
        # timewarp_analysis/ を基準に保存する（scripts/ の1つ上が timewarp_analysis/）
        timewarp_analysis_dir = Path(__file__).resolve().parents[1]
        out_path = timewarp_analysis_dir / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)

    if show:
        plt.show()
    plt.close()


if __name__ == "__main__":
    plot_prob_vs_alpha(show=False)
