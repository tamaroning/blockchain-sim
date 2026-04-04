"""
横軸: ブロック生成時間と伝播遅延の比 t_gen / t_prop（無次元）
縦軸: 名目ハッシュレート割合 α
色: DP による攻撃成功率

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


# ==========================================
# 2. ヒートマップ（横軸 = t_gen / t_prop）
# ==========================================
def plot_attack_success_heatmap_by_block_generation_time(*, show_pow_threshold: bool = False):
    T_PROP = 2.0
    t_gen_min = 0.5
    t_gen_max = 600
    n_t_gen = 220
    n_alpha = 200

    print("DPモデルの事前計算中（並列）...")
    alphas_dp, probs_dp = precompute_dp_table()
    print("完了。プロットを生成します。")

    t_gen_grid = np.geomspace(t_gen_min, t_gen_max, n_t_gen)
    alpha_nom_grid = np.linspace(0.5, 1.0, n_alpha)
    Z = np.zeros((len(alpha_nom_grid), len(t_gen_grid)))

    for j, t_gen in enumerate(t_gen_grid):
        ratio = T_PROP / t_gen
        P_orphan_n = ratio / (1.0 + ratio)
        denom = alpha_nom_grid + (1.0 - alpha_nom_grid) * (1.0 - P_orphan_n)
        alpha_eff = np.divide(
            alpha_nom_grid,
            denom,
            out=np.zeros_like(alpha_nom_grid),
            where=denom != 0,
        )
        Z[:, j] = np.interp(alpha_eff, alphas_dp, probs_dp, left=0.0, right=1.0)

    x_ratio = t_gen_grid / T_PROP
    X, Y = np.meshgrid(x_ratio, alpha_nom_grid)

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
        x_thr = t_gen_thr / T_PROP
        thr_mask = np.isfinite(t_gen_thr) & (t_gen_thr >= t_gen_min) & (t_gen_thr <= t_gen_max)
        y_thr = 0.5 + betas_thr
        (line_thr,) = ax.plot(
            x_thr[thr_mask],
            y_thr[thr_mask],
            color="blue",
            linewidth=2,
            zorder=5,
            clip_on=True,
        )

    ax.set_title(
        "Required nominal hashrate vs $t_{\\mathrm{gen}}/t_{\\mathrm{prop}}$ (timewarp)\n"
        f"Fixed propagation delay $t_{{\\mathrm{{prop}}}} = {T_PROP}$ s"
    )
    ax.set_xlabel(r"Block time ratio $t_{\mathrm{gen}}/t_{\mathrm{prop}}$")
    ax.set_ylabel("Nominal hashrate fraction α")
    ax.set_xlim(t_gen_min / T_PROP, t_gen_max / T_PROP)
    ax.set_xscale("log")
    _xt = np.array([0.5, 1.0, 10.0, 100.0, float(t_gen_max)]) / T_PROP
    ax.set_xticks(_xt)
    ax.set_xticklabels(
        [r"$0.25$", r"$0.5$", r"$5$", r"$50$", r"$3\times10^{2}$"]
    )
    ax.set_ylim(0.5, 1.0)
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
        / "required_hashrate_heatmap_block_generation_time.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DP timewarp attack success heatmap vs t_gen/t_prop."
    )
    parser.add_argument(
        "--show-pow-threshold",
        action="store_true",
        help="Overlay Dembo et al. true threshold as α = 0.5+β* on the same y-axis as the heatmap. Default: off.",
    )
    args = parser.parse_args()
    plot_attack_success_heatmap_by_block_generation_time(show_pow_threshold=args.show_pow_threshold)
