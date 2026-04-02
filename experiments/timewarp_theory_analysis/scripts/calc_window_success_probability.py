# P(N,alpha)を計算するスクリプト

from __future__ import annotations
from typing import List

def prob_always_at_least_6_As_in_last_11(N: int, alpha: float) -> float:
    """
    Returns P( for all t=11..N, among draws t-10..t, #A >= 6 ),
    where each draw is independent and P(A)=alpha, P(H)=1-alpha.

    State = last 10 outcomes as a 10-bit mask (bit=1 means A).
    Constraint for next outcome x in {0,1}: popcount(state)+x >= 6.
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be in [0,1]")
    if N <= 0:
        return 0.0
    if N < 11:
        # no 11-window exists yet, so the condition is vacuously true
        return 1.0

    A = alpha
    H = 1.0 - alpha
    S = 1 << 10  # 1024 states

    # popcount for all 10-bit states
    popcnt = [0] * S
    for s in range(1, S):
        popcnt[s] = popcnt[s >> 1] + (s & 1)

    # initial distribution after 10 draws: P(last10 == s)
    # = A^(#1) * H^(10-#1)
    p = [0.0] * S
    for s in range(S):
        k = popcnt[s]
        p[s] = (A ** k) * (H ** (10 - k))

    # advance from time 10 to N, enforcing constraint for each newly formed 11-window
    # For each step, we append next bit x and keep last 10 bits.
    mask10 = S - 1
    steps = N - 10
    for _ in range(steps):
        new_p = [0.0] * S
        for s, ps in enumerate(p):
            if ps == 0.0:
                continue

            k = popcnt[s]

            # next bit = 1 (A). Allowed if k+1 >= 6
            if k + 1 >= 6:
                ns = ((s << 1) | 1) & mask10
                new_p[ns] += ps * A

            # next bit = 0 (H). Allowed if k >= 6
            if k >= 6:
                ns = (s << 1) & mask10
                new_p[ns] += ps * H

        p = new_p

    return float(sum(p))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute P(常に直近11回のうち少なくとも6回がAとなる)"
    )
    parser.add_argument("N", type=int, help="総試行回数（>=1）")
    parser.add_argument("alpha", type=float, help="Aが出る確率 α in [0,1]")
    args = parser.parse_args()

    prob = prob_always_at_least_6_As_in_last_11(args.N, args.alpha)
    print(prob)


if __name__ == "__main__":
    main()
