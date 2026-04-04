"""
横軸: ブロック生成時間 t_gen（秒）
縦軸: 変換前の名目ハッシュレート割合 α
色: DP による攻撃成功率

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
from matplotlib.colors import BoundaryNorm

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


# ==========================================
# 2. ヒートマップ（横軸 = ブロック生成時間）
# ==========================================
def plot_attack_success_heatmap_by_block_generation_time(
    *, show_pow_threshold: bool = False, gamma: float = 0.5
):
    T_PROP = 2.0
    t_gen_min = 0.5
    t_gen_max = 600
    n_t_gen = 220
    n_alpha = 200

    print("DPモデルの事前計算中（並列）...")
    alphas_dp, probs_dp = precompute_dp_table()
    print("完了。プロットを生成します。")

    t_gen_grid = np.geomspace(t_gen_min, t_gen_max, n_t_gen)
    alpha_nom_grid = np.linspace(0.0, 1.0, n_alpha)
    alpha_eff_sm = effective_hashrate_fraction(alpha_nom_grid, gamma)
    Z = np.zeros((len(alpha_nom_grid), len(t_gen_grid)))

    for j, t_gen in enumerate(t_gen_grid):
        P_orphan_n = 1.0 - np.exp(-T_PROP / t_gen)
        denom = alpha_eff_sm + (1.0 - alpha_eff_sm) * (1.0 - P_orphan_n)
        alpha_eff = np.divide(
            alpha_eff_sm,
            denom,
            out=np.zeros_like(alpha_eff_sm),
            where=denom != 0,
        )
        Z[:, j] = np.interp(alpha_eff, alphas_dp, probs_dp, left=0.0, right=1.0)

    X, Y = np.meshgrid(t_gen_grid, alpha_nom_grid)

    fig, ax = plt.subplots(figsize=(10, 6))

    boundaries = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    cmap = plt.colormaps["YlOrRd"].copy()
    cmap.set_bad(color="#cccccc")
    norm = BoundaryNorm(boundaries, ncolors=cmap.N, clip=True)

    pcm = ax.pcolormesh(X, Y, Z, shading="auto", cmap=cmap, norm=norm, zorder=1)
    cbar = fig.colorbar(pcm, ax=ax, label="Attack success probability (DP)", ticks=np.arange(0.0, 1.0, 0.1))
    cbar.ax.minorticks_off()

    cs_fine = ax.contour(X, Y, Z, levels=[0.2, 0.4, 0.6, 0.8], colors="k", linewidths=0.35, alpha=0.35, zorder=2)
    ax.clabel(cs_fine, inline=True, fontsize=8, fmt="%.1f")
    cs50 = ax.contour(X, Y, Z, levels=[0.5], colors=["#1a1a1a"], linewidths=2.0, linestyles="-", zorder=2)
    ax.clabel(cs50, inline=True, fontsize=10, fmt=lambda _lev: "50%")

    if show_pow_threshold:
        # Dembo et al. true threshold: 1/(λΔ) = β(1−β)/(1−2β); λΔ = t_prop / t_gen ⇒ t_gen = t_prop / (λΔ).
        # 縦位置は主軸の α と同一スケール: y = 0.5 + β*（旧 twinx の 0–0.5 と幾何的に同じ）。
        betas_thr = np.linspace(0.001, 0.499, 1000)
        lambda_delta = (1.0 - 2.0 * betas_thr) / (betas_thr * (1.0 - betas_thr))
        inv_lambda_delta = 1.0 / lambda_delta
        t_gen_thr = T_PROP * inv_lambda_delta
        thr_mask = np.isfinite(t_gen_thr) & (t_gen_thr >= t_gen_min) & (t_gen_thr <= t_gen_max)
        y_thr = 0.5 + betas_thr
        (line_thr,) = ax.plot(
            t_gen_thr[thr_mask],
            y_thr[thr_mask],
            color="blue",
            linewidth=2,
            zorder=5,
            clip_on=True,
        )

    ax.set_title(
        "Required nominal hashrate vs block generation time (timewarp)\n"
        f"$\\gamma = {gamma}$, fixed propagation delay $t_{{\\mathrm{{prop}}}} = {T_PROP}$ s"
    )
    ax.set_xlabel("Block generation time $t_{\\mathrm{gen}}$ (s)")
    ax.set_ylabel("Nominal hashrate fraction α (pre-mapping)")
    ax.set_xlim(t_gen_min, t_gen_max)
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1.0, 10.0, 100.0, float(t_gen_max)])
    ax.set_xticklabels(
        [r"$0.5$", r"$10^{0}$", r"$10^{1}$", r"$10^{2}$", r"$6\times10^{2}$"]
    )
    ax.set_ylim(0.0, 1.0)
    ax.grid(True, linestyle=":", alpha=0.25, zorder=0)
    if show_pow_threshold:
        leg = fig.legend(
            [line_thr],
            [r"True threshold: $\alpha = 0.5+\beta^*(\lambda\Delta)$ (Dembo et al.)"],
            loc="lower left",
            bbox_to_anchor=(0.12, 0.02),
            fontsize=9,
            framealpha=0.92,
        )
        leg.set_zorder(10)

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
        description="DP timewarp attack success heatmap vs block generation time."
    )
    parser.add_argument(
        "--show-pow-threshold",
        action="store_true",
        help="Overlay Dembo et al. true threshold as α = 0.5+β* on the same y-axis as the heatmap. Default: off.",
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=0.5,
        help="Parameter γ in the effective hashrate fraction mapping (default: 0.5).",
    )
    args = parser.parse_args()
    plot_attack_success_heatmap_by_block_generation_time(
        show_pow_threshold=args.show_pow_threshold, gamma=args.gamma
    )
