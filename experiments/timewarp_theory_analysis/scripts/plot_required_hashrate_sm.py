"""
横軸: ブロック生成時間と伝播遅延の比 t_gen / t_prop（無次元）
縦軸: 変換前の名目ハッシュレート割合 α

γ = 0, 0.5, 1 それぞれについて、DP モデルで攻撃成功率が 50% となる名目 α の曲線を描画する。
ヒートマップと同じ timewarp（SM なし）写像で 50% となる名目 α の曲線も重ねる（探索は α ∈ (0,1)。ヒートマップ図の縦軸は [0.5,1] 表示のみ）。
理論の true threshold（Dembo et al.）も重ねる。

名目 α から実効ハッシュレート割合へは γ を含む有理式で写像し、
timewarp 補正ではその実効割合を用いる（縦軸は変換前の名目 α）。

伝播遅延 t_prop は固定（T_PROP）。
"""
import matplotlib

matplotlib.use("Agg")

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import LogFormatterMathtext, LogLocator

# ==========================================
# 1. 動的計画法 (DP) による攻撃成功率の計算
# ==========================================
def _dp_transition_buffers(window_size=11, threshold=6):
    n_states = 1 << window_size
    bit_counts = np.array([bin(i).count("1") for i in range(n_states)], dtype=np.int8)
    valid_states = bit_counts >= threshold
    ar = np.arange(n_states, dtype=np.int64)
    state_a_idx = ((ar << 1) & (n_states - 1)) | 1
    state_h_idx = (ar << 1) & (n_states - 1)
    i_valid = np.flatnonzero(valid_states)
    ja = state_a_idx[i_valid]
    jh = state_h_idx[i_valid]
    mask_a = valid_states[ja]
    mask_h = valid_states[jh]
    return (n_states, i_valid, ja, jh, mask_a, mask_h)


_DP_BUFFERS = None


def _init_dp_worker(buffers):
    global _DP_BUFFERS
    _DP_BUFFERS = buffers


def _dp_job_alpha(alpha_eff):
    return calc_success_prob_dp(alpha_eff, buffers=_DP_BUFFERS)


def calc_success_prob_dp(alpha_eff, n_steps=2016, buffers=None):
    if buffers is None:
        buffers = _dp_transition_buffers()
    n_states, i_valid, ja, jh, mask_a, mask_h = buffers
    P = np.zeros(n_states)
    P[-1] = 1.0
    w_a = float(alpha_eff)
    w_h = 1.0 - w_a
    for _ in range(n_steps):
        P_new = np.zeros(n_states)
        np.add.at(P_new, ja[mask_a], w_a * P[i_valid[mask_a]])
        np.add.at(P_new, jh[mask_h], w_h * P[i_valid[mask_h]])
        P = P_new
    return float(np.sum(P))


def precompute_dp_table(max_workers=None):
    alphas_eff = np.linspace(0.75, 1.0, 100)
    buffers = _dp_transition_buffers()
    with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_dp_worker, initargs=(buffers,)) as pool:
        probs = list(pool.map(_dp_job_alpha, alphas_eff))
    probs = np.asarray(probs, dtype=float)
    return alphas_eff, probs


def effective_hashrate_fraction(alpha, gamma):
    """
    名目攻撃者割合 alpha に対する実効ハッシュレート割合（SM 写像）。
    (α(1−α)²(4α + γ(1−2α)) − α³) / (1 − α(1 + (2−α)α))
    alpha > 0.5 のときは 1 を返す。
    """
    alpha = np.asarray(alpha, dtype=float)
    one_m_a = 1.0 - alpha
    num = alpha * one_m_a**2 * (4.0 * alpha + gamma * (1.0 - 2.0 * alpha)) - alpha**3
    den = 1.0 - alpha * (1.0 + (2.0 - alpha) * alpha)
    result = np.divide(num, den, out=np.zeros_like(num, dtype=float), where=np.abs(den) > 1e-15)
    return np.where(alpha > 0.5, 1.0, result)


def attack_success_prob_nominal(alpha_nom, t_gen, gamma, t_prop, alphas_dp, probs_dp):
    alpha_nom = float(alpha_nom)
    alpha_eff_sm = float(effective_hashrate_fraction(np.array([alpha_nom]), gamma)[0])
    ratio = t_prop / t_gen
    p_orphan = ratio / (1.0 + ratio)
    denom = alpha_eff_sm + (1.0 - alpha_eff_sm) * (1.0 - p_orphan)
    if denom <= 0:
        return 0.0
    alpha_eff = alpha_eff_sm / denom
    return float(np.interp(alpha_eff, alphas_dp, probs_dp, left=0.0, right=1.0))


def attack_success_prob_heatmap_nominal(alpha_nom, t_gen, t_prop, alphas_dp, probs_dp):
    """ヒートマップ script と同じ写像（名目 α を SM なしで timewarp に通す）。"""
    alpha_nom = float(alpha_nom)
    ratio = t_prop / t_gen
    p_orphan = ratio / (1.0 + ratio)
    denom = alpha_nom + (1.0 - alpha_nom) * (1.0 - p_orphan)
    if denom <= 0:
        return 0.0
    alpha_eff = alpha_nom / denom
    return float(np.interp(alpha_eff, alphas_dp, probs_dp, left=0.0, right=1.0))


def nominal_alpha_for_target_prob(target, t_gen, gamma, t_prop, alphas_dp, probs_dp, n_iter=64):
    lo, hi = 1e-12, 0.5

    def p(a):
        return attack_success_prob_nominal(a, t_gen, gamma, t_prop, alphas_dp, probs_dp)

    p_lo, p_hi = p(lo), p(hi)
    if p_hi < target:
        return np.nan
    if p_lo >= target:
        return lo
    for _ in range(n_iter):
        mid = 0.5 * (lo + hi)
        if p(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def nominal_alpha_for_target_prob_heatmap(target, t_gen, t_prop, alphas_dp, probs_dp, n_iter=64):
    """
    timewarp（SM なし）で target 成功率となる名目 α を二分探索。
    `attack_success_prob_heatmap_nominal` は α ∈ (0,1) で単調（α_eff 単調 → DP 補間単調）。
    ヒートマップ PNG の縦軸は表示上 [0.5, 1] に切っているが、式は小さい α も同じ。
    """
    lo, hi = 1e-12, 1.0 - 1e-12

    def p(a):
        return attack_success_prob_heatmap_nominal(a, t_gen, t_prop, alphas_dp, probs_dp)

    p_lo, p_hi = p(lo), p(hi)
    if p_hi < target:
        return np.nan
    if p_lo >= target:
        return lo
    for _ in range(n_iter):
        mid = 0.5 * (lo + hi)
        if p(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _beta_for_t_prop_over_t_gen(*, t_prop: float, t_gen: float) -> float:
    """
    λΔ = t_prop / t_gen = (1 − 2β) / (β(1−β)) を満たす β ∈ (0, 0.5) を返す。
    同値な二次方程式: R β² − (R+2) β + 1 = 0, R = t_prop / t_gen。
    """
    R = t_prop / float(t_gen)
    disc = (R + 2.0) ** 2 - 4.0 * R
    if disc < 0.0:
        return float("nan")
    s = float(np.sqrt(disc))
    two_r = 2.0 * R
    for beta in (((R + 2.0) - s) / two_r, ((R + 2.0) + s) / two_r):
        if 0.0 < beta < 0.5:
            return float(beta)
    return float("nan")


# ==========================================
# 2. γ = 0, 0.5, 1 の 50% 曲線 + true threshold
# ==========================================
def plot_required_nominal_hashrate_curves(*, show_pow_threshold: bool = True):
    T_PROP = 2.0
    x_lim_lo = 0.01
    t_gen_min = x_lim_lo * T_PROP
    t_gen_max = 600
    n_t_gen = 400
    gammas = (0.0, 0.5, 1.0)

    print("DPモデルの事前計算中（並列）...")
    alphas_dp, probs_dp = precompute_dp_table()
    print("完了。プロットを生成します。")

    t_gen_grid = np.geomspace(t_gen_min, t_gen_max, n_t_gen)
    x_ratio = t_gen_grid / T_PROP

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ("#c0392b", "#2980b9", "#27ae60")
    for gamma, color in zip(gammas, colors):
        alphas_nom = np.array(
            [
                nominal_alpha_for_target_prob(0.5, tg, gamma, T_PROP, alphas_dp, probs_dp)
                for tg in t_gen_grid
            ]
        )
        mask = np.isfinite(alphas_nom)
        ax.plot(
            x_ratio[mask],
            alphas_nom[mask],
            color=color,
            linewidth=2.0,
            zorder=3,
            label=rf"50% success timwarp+SM, $\gamma={gamma:g}$",
        )

    alphas_heatmap = np.array(
        [
            nominal_alpha_for_target_prob_heatmap(0.5, tg, T_PROP, alphas_dp, probs_dp)
            for tg in t_gen_grid
        ]
    )
    mask_hm = np.isfinite(alphas_heatmap)
    ax.plot(
        x_ratio[mask_hm],
        alphas_heatmap[mask_hm],
        color="#1a1a1a",
        linewidth=2.0,
        linestyle="-",
        zorder=3,
        label=r"50% success timewarp",
    )

    if show_pow_threshold:
        # Dembo et al.: β = (1−β)/(1+(1−β)·λΔ), λΔ = t_prop/t_gen と同一視。
        # 変形すると t_prop/t_gen = (1−2β)/(β(1−β)), 縦軸は式の右辺（曲線上で β と一致）。
        # β ∈ (0, 0.5) のみ物理的（λΔ > 0）。β → 0.5− で t_gen → ∞ となるため、
        # β > 0.5 のサンプルや粗い格子だと t_gen_max 手前で点が途切れる。右端は解析的に閉じる。
        betas_thr = np.linspace(0.001, 0.499, 4000)
        ratio_prop_gen = (1.0 - 2.0 * betas_thr) / (betas_thr * (1.0 - betas_thr))
        t_gen_thr = T_PROP / ratio_prop_gen
        x_thr = t_gen_thr / T_PROP
        thr_mask = np.isfinite(t_gen_thr) & (t_gen_thr >= t_gen_min) & (t_gen_thr <= t_gen_max)
        y_thr = (1.0 - betas_thr) / (1.0 + (1.0 - betas_thr) * ratio_prop_gen)
        x_p = x_thr[thr_mask]
        y_p = y_thr[thr_mask]
        x_right = t_gen_max / T_PROP
        beta_right = _beta_for_t_prop_over_t_gen(t_prop=T_PROP, t_gen=t_gen_max)
        if np.isfinite(beta_right):
            r_end = T_PROP / t_gen_max
            y_right = (1.0 - beta_right) / (1.0 + (1.0 - beta_right) * r_end)
            if x_p.size == 0 or x_p[-1] < x_right * (1.0 - 1e-9):
                x_p = np.append(x_p, x_right)
                y_p = np.append(y_p, y_right)
        (line_thr,) = ax.plot(
            x_p,
            y_p,
            color="#6c3483",
            linewidth=2.0,
            linestyle="--",
            zorder=4,
            label=r"True threshold: $\alpha=\beta_{\mathrm{crit}}(\lambda\Delta)$ (Dembo et al.)",
        )

    ax.set_title(
        "Required nominal hashrate for 50% attack success vs $t_{\\mathrm{gen}}/t_{\\mathrm{prop}}$ (timewarp)\n"
        rf"$\gamma \in \{{0,\,0.5,\,1\}}$, fixed propagation delay $t_{{\mathrm{{prop}}}} = {T_PROP}$ s"
    )
    ax.set_xlabel(r"Block time ratio $t_{\mathrm{gen}}/t_{\mathrm{prop}}$")
    ax.set_ylabel("Nominal hashrate fraction α")
    ax.set_xlim(x_lim_lo, t_gen_max / T_PROP)
    ax.set_xscale("log")
    # 横軸は t_gen/t_prop。対数軸では 10 の冪を主要目盛りにし、0.25/0.5 のような中途半端なラベルを避ける。
    ax.xaxis.set_major_locator(LogLocator(base=10))
    ax.xaxis.set_major_formatter(LogFormatterMathtext())
    ax.set_ylim(0.0, 1.0)
    ax.grid(True, linestyle=":", alpha=0.25, zorder=0)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.92)

    out_path = (
        Path(__file__).resolve().parents[1]
        / "results"
        / "required_hashrate_sm.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DP timewarp: 50% success nominal α vs t_gen/t_prop for γ=0,0.5,1 and true threshold."
    )
    parser.add_argument(
        "--no-pow-threshold",
        action="store_true",
        help="Do not overlay Dembo et al. true threshold.",
    )
    args = parser.parse_args()
    plot_required_nominal_hashrate_curves(show_pow_threshold=not args.no_pow_threshold)
