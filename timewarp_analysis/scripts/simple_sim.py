import random
import matplotlib.pyplot as plt

# ---- パラメータ ----
T = 2                      # target time (week)
P_MTP_CONTROLLED = 0.9   # MTP control probability
SLOW_CLOCK_SPEED = (2016 / 6) / (7 * 24 * 60 * 60) # slow clock speed (second/epoch)
EPOCHS = 300
RUNS = 1
CLAMP = True

def simulate():
    realtime = 0.0
    blkclock = 0.0
    d = 1.0

    ds = [d]
    blks = [blkclock]
    rts = [realtime]

    for _ in range(EPOCHS):
        print(f"epoch: {_}, d: {d}, blkclock: {blkclock}, realtime: {realtime}")
        prev_blkclock = blkclock

        realtime += d * T

        if random.random() < P_MTP_CONTROLLED:
            blkclock += SLOW_CLOCK_SPEED
        else:
            blkclock = realtime

        # Bitcoin-style retarget:
        #   actual_timespan = last_timestamp - first_timestamp
        #   actual_timespan is clamped to [target/4, target*4]
        #   new_d = d * target / actual_timespan
        #
        # Note: we intentionally do NOT take abs(). If timestamps go backwards
        # (actual_timespan <= 0), clamping will pin it to the minimum timespan.
        actual_timespan = realtime - prev_blkclock

        if CLAMP:
            min_timespan = T / 4.0
            max_timespan = T * 4.0
            if actual_timespan < min_timespan:
                actual_timespan = min_timespan
            elif actual_timespan > max_timespan:
                actual_timespan = max_timespan

        d = d * T / actual_timespan
        
        ds.append(d)
        blks.append(blkclock)
        rts.append(realtime)

    return ds, blks, rts

# ---- 複数回実行 ----
all_results = [simulate() for _ in range(RUNS)]

# ---- 描画 ----
fig, ax1 = plt.subplots()
ax2 = ax1.twinx()

for ds, blks, rts in all_results:
    ax1.plot(ds, alpha=0.6, label="difficulty d")
    ax2.plot(blks, alpha=0.5, linestyle="--", label="MTP clock")
    ax2.plot(rts, alpha=0.5, linestyle=":", label="realtime")

ax1.set_xlabel("epoch")
ax1.set_ylabel("difficulty d")
ax1.set_yscale("log")

ax2.set_ylabel("blkclock / realtime")

ax1.set_title("Timewarp simulation: difficulty evolution")

# 凡例（左右軸の lines を結合）
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")

fig.tight_layout()
plt.show()
