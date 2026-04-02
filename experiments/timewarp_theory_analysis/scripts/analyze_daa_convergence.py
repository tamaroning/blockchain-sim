#!/usr/bin/env python3
# D_k+1/D_kが1/2.8に収束することを示す漸化式を解く
# https://chatgpt.com/c/696f3d78-59e8-8320-aaa1-b333c2dc98ac

import math
import argparse
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

def iterate_timewarp(D0=1.0, A0=1209600.0, T=1209600.0, s=336.0, steps=50):
    """
    Recurrence:
      D_{k+1} = D_k * (T / A_k)
      A_{k+1} = A_k + T * D_{k+1} - s

    Returns:
      list of dicts with k, Dk, Ak, ratio (D_{k+1}/D_k), inv_ratio (D_k/D_{k+1})
    """
    D = float(D0)
    A = float(A0)

    rows = []
    for k in range(steps):
        ratio = T / A                  # D_{k+1}/D_k
        D_next = D * ratio
        A_next = A + T * D_next - s
        delta_A = A_next - A           # A_{k+1} - A_k

        rows.append({
            "k": k,
            "D_k": D,
            "A_k": A,
            "D_{k+1}/D_k": ratio,
            "D_k/D_{k+1}": 1.0 / ratio,
            "D_{k+1}": D_next,
            "A_{k+1}": A_next,
            "A_{k+1}-A_k": delta_A,
        })

        D, A = D_next, A_next

    return rows

def tail_mean(values, tail=5):
    if not values:
        return float("nan")
    n = min(int(tail), len(values))
    return sum(values[-n:]) / n

def main():
    parser = argparse.ArgumentParser(description="Timewarp recurrence explorer")
    parser.add_argument("--linear", action="store_true",
                        help="Use linear y-scale (default: log scale)")
    args = parser.parse_args()

    # Example initial values (you can change these)
    D0 = 1.0
    A0 = 1209600.0
    T  = 1209600.0 # 2016*600 s
    s  = 336.0 # 遅い時計 336 s/epoch

    rows = iterate_timewarp(D0=D0, A0=A0, T=T, s=s, steps=100000)

    # Print header
    print(f"{'k':>3}  {'D_k':>14}  {'A_k':>14}  {'D_{k+1}/D_k':>14}  {'A_{k+1}-A_k':>14}  {'D_k/D_{k+1}':>14}")
    print("-" * 90)

    for r in rows:
        print(
            f"{r['k']:>3}  {r['D_k']:>14.6g}  {r['A_k']:>14.6g}  "
            f"{r['D_{k+1}/D_k']:>14.9f}  {r['A_{k+1}-A_k']:>14.6g}  {r['D_k/D_{k+1}']:>14.6f}"
        )

    # Show limiting estimates (tail mean)
    tail = min(5, len(rows))
    ratio_limit = tail_mean([r["D_{k+1}/D_k"] for r in rows], tail=tail)
    deltaA_limit = tail_mean([r["A_{k+1}-A_k"] for r in rows], tail=tail)

    last = rows[-1]
    print("\nLimiting values:")
    print(f"  D_{last['k']+1}/D_{last['k']}  ≈ {ratio_limit:.12f}  (tail mean over {tail} points)")
    print(f"  A_{last['k']+1}-A_{last['k']}  ≈ {deltaA_limit:.6g} s  (tail mean over {tail} points)")
    print(f"  D_{last['k']}/D_{last['k']+1}  ≈ {(1.0/ratio_limit):.12f}")

    # Plot D_k and A_k over k
    SECS_PER_WEEK = 7.0 * 24.0 * 60.0 * 60.0
    ks = [r["k"] for r in rows]
    Ds = [r["D_k"] for r in rows]
    As_weeks = [r["A_k"] / SECS_PER_WEEK for r in rows]
    T_weeks = T / SECS_PER_WEEK

    fig, ax_left = plt.subplots(figsize=(9, 5))
    ax_right = ax_left.twinx()

    # 左軸に難易度D_k、右軸にA_k
    left_line = ax_left.plot(ks, Ds, marker="o", color="tab:blue", label="D_k")[0]
    right_line = ax_right.plot(ks, As_weeks, marker="o", color="tab:red", label="A_k")[0]

    ax_left.set_xlabel("k")
    ax_left.set_ylabel("D_k (difficulty)", color=left_line.get_color())
    ax_right.set_ylabel("A_k (weeks, apparent epoch time)", color=right_line.get_color())

    # デフォルトで対数スケール、--linear指定時のみ線形
    if not args.linear:
        ax_left.set_yscale("log")

    # Grid: x方向（縦線）だけにして、基準線と紛れないようにする
    ax_left.grid(True, axis="x", linestyle="--", alpha=0.35)
    ax_left.tick_params(axis="y", labelcolor=left_line.get_color())
    ax_right.tick_params(axis="y", labelcolor=right_line.get_color())

    # Reference line for A_k: target epoch time T (= 2 weeks)
    ref_line = ax_right.axhline(
        T_weeks,
        color="gray",
        linestyle=":",
        linewidth=1.5,
        alpha=0.6,
        label="T (2 weeks)",
    )

    yticks = list(ax_right.get_yticks())
    yticks.extend([T_weeks])
    yticks = sorted({t for t in yticks if t > 0})
    ax_right.set_yticks(yticks)

    # Merge per-axis legends
    conv_handle_1 = Line2D([], [], color="none", label=f"D(k+1)/D(k) ≈ {ratio_limit:.6g}")
    conv_handle_2 = Line2D([], [], color="none", label=f"A(k+1)-A(k) ≈ {deltaA_limit:.6g} s")
    lines = [left_line, right_line, ref_line, conv_handle_1, conv_handle_2]
    labels = [l.get_label() for l in lines]
    ax_left.legend(lines, labels, loc="best")

    # Convergence annotation inside the graph
    conv_text = (
        f"Convergence (tail mean over {tail} points)\n"
        f"D(k+1)/D(k) ≈ {ratio_limit:.6g}\n"
        f"A(k+1)-A(k) ≈ {deltaA_limit:.6g} s ({(deltaA_limit/SECS_PER_WEEK):.6g} weeks)"
    )
    ax_left.text(
        0.02,
        0.98,
        conv_text,
        transform=ax_left.transAxes,
        va="top",
        ha="left",
        fontsize=10,
        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.85),
    )

    fig.suptitle(
        "D_k and A_k over k (A_k: apparent epoch elapsed time)",
        y=1.02,
    )
    fig.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
