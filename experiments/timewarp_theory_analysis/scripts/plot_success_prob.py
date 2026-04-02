import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

TOTAL_EVENTS = 2016

def get_popcounts(window_size):
    return np.array([bin(i).count('1') for i in range(1 << window_size)])

def survival_probability_fast(alpha, window_size):
    if alpha <= 0.0: return 0.0
    if alpha >= 1.0: return 1.0

    num_states = 1 << window_size
    min_a = (window_size + 1) // 2
    popcounts = get_popcounts(window_size)
    valid_mask = popcounts >= min_a

    probs = np.zeros(num_states)
    k = popcounts
    probs = (alpha ** k) * ((1 - alpha) ** (window_size - k))
    probs[~valid_mask] = 0.0

    if np.sum(probs) == 0: return 0.0

    idx_a = ((np.arange(num_states) << 1) | 1) & (num_states - 1)
    idx_b = (np.arange(num_states) << 1) & (num_states - 1)
    mask_a = valid_mask[idx_a]
    mask_b = valid_mask[idx_b]

    for _ in range(window_size, TOTAL_EVENTS):
        new_probs = np.zeros(num_states)
        np.add.at(new_probs, idx_a[mask_a], probs[mask_a] * alpha)
        np.add.at(new_probs, idx_b[mask_b], probs[mask_b] * (1 - alpha))

        probs = new_probs
        current_sum = np.sum(probs)
        if current_sum < 1e-12: return 0.0 # リニアスケールなので閾値を少し緩和

    return np.sum(probs)

def adaptive_sample(f, x0, x1, y0, y1, tol=0.003, depth=0):
    mid_x = (x0 + x1) / 2
    mid_y = f(mid_x)
    # 線形補間とのズレがtol未満なら分割終了
    if depth > 5 or abs(mid_y - (y0 + y1) / 2) < tol:
        return [(mid_x, mid_y)]
    return (adaptive_sample(f, x0, mid_x, y0, mid_y, tol, depth + 1) +
            [(mid_x, mid_y)] +
            adaptive_sample(f, mid_x, x1, mid_y, y1, tol, depth + 1))

def run_simulation():
    windows = [13, 11, 9, 7, 5]
    plt.figure(figsize=(12, 7))

    for w in windows:
        print(f"Processing WINDOW={w}...")
        f = lambda a: survival_probability_fast(a, w)

        # アルファ 0.5〜1.0 の範囲を調査
        xs_base = [0.5, 1.0]
        ys_base = [f(0.5), 1.0]

        samples = [(xs_base[0], ys_base[0])] + \
                  adaptive_sample(f, xs_base[0], xs_base[1], ys_base[0], ys_base[1]) + \
                  [(xs_base[1], ys_base[1])]

        samples.sort()
        xs, ys = zip(*samples)

        plt.plot(xs, ys, marker='.', markersize=4, label=f'Window={w} (points={len(xs)})')

    # --- グラフ設定の変更点 ---
    plt.yscale('linear')      # リニアスケールに設定
    plt.ylim(-0.05, 1.05)     # 0と1が綺麗に見えるようにマージンを調整
    plt.xlim(0.7, 1.0)        # alpha=0.5以下の意味は薄いため絞り込み

    plt.xlabel("Attacker hashrate (without selfish mining)")
    plt.ylabel("Attack success rate")
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.legend()
    out_path = Path(__file__).resolve().parents[1] / "results" / "success_prob.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    print(f"Saved: {out_path}")
    plt.close()

if __name__ == "__main__":
    run_simulation()
