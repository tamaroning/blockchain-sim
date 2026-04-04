"""
横軸: ブロック生成時間 t_gen（秒）
縦軸: DP による攻撃成功率
塗りつぶし・等高線: 名目ハッシュレート割合 α

伝播遅延 t_prop は固定（T_PROP）。

plot_required_hashrate_heatmap_block_generation_time.py と同じ t_gen 範囲・対数軸だが、
縦軸と色（成功率と α）を入れ替えた版。
"""
import matplotlib

matplotlib.use("Agg")

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

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


def _compress_nondecreasing_x(xp, fp):
    """np.interp 用に xp を狭義単調増加に圧縮（同一 xp は先頭の fp を残す）。"""
    if len(xp) == 0:
        return xp, fp
    keep_x = [float(xp[0])]
    keep_f = [float(fp[0])]
    for k in range(1, len(xp)):
        if float(xp[k]) > keep_x[-1] + 1e-15:
            keep_x.append(float(xp[k]))
            keep_f.append(float(fp[k]))
    return np.asarray(keep_x), np.asarray(keep_f)


def _alpha_from_success_column(success_vs_alpha, alpha_grid, success_targets):
    """固定 t_gen において success(α) の単調性を仮定し、各目標成功率に対応する α を返す。"""
    s_u, a_u = _compress_nondecreasing_x(success_vs_alpha, alpha_grid)
    if len(s_u) < 2:
        return np.full_like(success_targets, a_u[0] if len(a_u) else np.nan, dtype=float)
    return np.interp(success_targets, s_u, a_u, left=a_u[0], right=a_u[-1])


# ==========================================
# 2. 等高線図（横軸 = ブロック生成時間、縦 = 成功率、色・線 = α）
# ==========================================
def plot_nominal_hashrate_heatmap_by_block_generation_time():
    T_PROP = 2.0
    t_gen_min = 0.5
    t_gen_max = 600
    n_t_gen = 220
    n_alpha = 200
    n_success = 200

    print("DPモデルの事前計算中（並列）...")
    alphas_dp, probs_dp = precompute_dp_table()
    print("完了。プロットを生成します。")

    t_gen_grid = np.geomspace(t_gen_min, t_gen_max, n_t_gen)
    alpha_nom_grid = np.linspace(0.0, 1.0, n_alpha)
    success_vs_alpha = np.zeros((len(alpha_nom_grid), len(t_gen_grid)))

    for j, t_gen in enumerate(t_gen_grid):
        P_orphan_n = 1.0 - np.exp(-T_PROP / t_gen)
        denom = alpha_nom_grid + (1.0 - alpha_nom_grid) * (1.0 - P_orphan_n)
        alpha_eff = np.divide(
            alpha_nom_grid,
            denom,
            out=np.zeros_like(alpha_nom_grid),
            where=denom != 0,
        )
        success_vs_alpha[:, j] = np.interp(alpha_eff, alphas_dp, probs_dp, left=0.0, right=1.0)

    success_grid = np.linspace(0.0, 1.0, n_success)
    Z = np.zeros((len(success_grid), len(t_gen_grid)))
    for j in range(len(t_gen_grid)):
        Z[:, j] = _alpha_from_success_column(
            success_vs_alpha[:, j], alpha_nom_grid, success_grid
        )

    X, Y = np.meshgrid(t_gen_grid, success_grid)

    fig, ax = plt.subplots(figsize=(10, 6))

    cmap = plt.colormaps["viridis"].copy()
    cmap.set_bad(color="#cccccc")
    fill_levels = np.linspace(0.0, 1.0, 41)
    line_levels = np.arange(0.0, 1.01, 0.1)

    csf = ax.contourf(
        X,
        Y,
        Z,
        levels=fill_levels,
        cmap=cmap,
        extend="both",
        corner_mask=False,
    )
    cs = ax.contour(
        X,
        Y,
        Z,
        levels=line_levels,
        colors="0.15",
        linewidths=0.6,
        linestyles="solid",
        corner_mask=False,
    )
    ax.clabel(cs, inline=True, fontsize=8, fmt=r"$\alpha=%.1f$")

    cbar = fig.colorbar(
        csf,
        ax=ax,
        label="Nominal hashrate fraction α",
        ticks=np.linspace(0.0, 1.0, 11),
    )
    cbar.ax.minorticks_off()

    ax.set_title(
        "Attack success probability vs block generation time (timewarp)\n"
        f"Fixed propagation delay $t_{{\\mathrm{{prop}}}} = {T_PROP}$ s — contours: nominal α"
    )
    ax.set_xlabel("Block generation time $t_{\\mathrm{gen}}$ (s)")
    ax.set_ylabel("Attack success probability (DP)")
    ax.set_xlim(t_gen_min, t_gen_max)
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1.0, 10.0, 100.0, float(t_gen_max)])
    ax.set_xticklabels(
        [r"$0.5$", r"$10^{0}$", r"$10^{1}$", r"$10^{2}$", r"$6\times10^{2}$"]
    )
    ax.set_ylim(0.0, 1.0)
    ax.grid(True, linestyle=":", alpha=0.25)

    out_path = (
        Path(__file__).resolve().parents[1]
        / "results"
        / "nominal_hashrate_heatmap_block_generation_time.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    plot_nominal_hashrate_heatmap_by_block_generation_time()
