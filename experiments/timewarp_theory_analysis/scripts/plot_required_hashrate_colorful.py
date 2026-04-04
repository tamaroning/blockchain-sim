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
    """
    alpha に依存しない遷移構造だけを前計算する。
    密行列 T.dot(P) は O(n^2)／ステップだが、各状態から高々2辺なので
    np.add.at による散布加算で O(n)／ステップにできる。
    """
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
    """
    実効ハッシュレート alpha_eff のもとで、2016ブロックの間
    一度も「直近11ブロック中攻撃者のブロックが6未満」にならない確率を計算する。
    """
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
    """成功率が変化する0.75〜1.0区間でDPを並列事前計算し、補間用テーブルを返す。"""
    alphas_eff = np.linspace(0.75, 1.0, 100)
    buffers = _dp_transition_buffers()
    with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_dp_worker, initargs=(buffers,)) as pool:
        probs = list(pool.map(_dp_job_alpha, alphas_eff))
    probs = np.asarray(probs, dtype=float)
    return alphas_eff, probs

# ==========================================
# 2. シミュレーションとヒートマップの可視化
# ==========================================
def plot_attack_success_heatmap():
    epochs = 10
    t_prop = 2.0         # 伝播遅延 (秒)
    H_total = 1.0        # 総ハッシュレート
    D_0 = 600.0          # 初期難易度
    
    print("DPモデルの事前計算中（並列）...")
    alphas_dp, probs_dp = precompute_dp_table()
    print("完了。プロットを生成します。")
    
    # メッシュグリッドの作成
    epoch_grid = np.arange(epochs + 1)
    alpha_nom_grid = np.linspace(0.5, 1.0, 200) # 名目ハッシュレートを50%~100%で観察
    
    # 色（成功率）を格納するZ軸配列
    Z = np.zeros((len(alpha_nom_grid), len(epoch_grid)))
    
    D_n = D_0
    for i, epoch in enumerate(epoch_grid):
        # 現在のエポックの生成時間とオーファン率
        t_gen_n = D_n / H_total
        P_orphan_n = 1.0 - np.exp(-t_prop / t_gen_n)
        
        denom = alpha_nom_grid + (1.0 - alpha_nom_grid) * (1.0 - P_orphan_n)
        alpha_eff = np.divide(
            alpha_nom_grid,
            denom,
            out=np.zeros_like(alpha_nom_grid),
            where=denom != 0,
        )
        Z[:, i] = np.interp(alpha_eff, alphas_dp, probs_dp, left=0.0, right=1.0)
            
        # 難易度の低下（1/4）
        D_n = D_n / 4.0

    # 描画
    X, Y = np.meshgrid(epoch_grid, alpha_nom_grid)
    
    plt.figure(figsize=(10, 6))
    
    # ヒートマップ (pcolormesh)
    cmap = plt.cm.jet # 色のグラデーション
    c = plt.pcolormesh(X, Y, Z, shading='auto', cmap=cmap, vmin=0, vmax=1)
    plt.colorbar(c, label="Attack Success Probability (DP)")
    
    # 50%成功率の境界線を強調表示
    contour = plt.contour(X, Y, Z, levels=[0.5], colors=['white'], linewidths=3, linestyles='--')
    plt.clabel(
        contour,
        inline=True,
        fmt=lambda _lev: " 50% Success Threshold",
        fontsize=12,
        colors="white",
    )
    
    plt.title("Required Nominal Hashrate Heatmap for Timewarp Attack")
    plt.xlabel("Epochs since Attack Started")
    plt.ylabel("Nominal Hashrate Fraction (α)")
    
    out_path = Path(__file__).resolve().parents[1] / "results" / "required_hashrate_heatmap_colorful.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    plot_attack_success_heatmap()
