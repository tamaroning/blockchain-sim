import random
import matplotlib.pyplot as plt

# ---- パラメータ ----
T = 2                      # target time (week)
P_MTP_CONTROLLED = 0.2   # MTP control probability
SLOW_CLOCK_SPEED = 2016 / 6 / (7 * 24 * 60 * 60) # slow clock speed (second/epoch)
EPOCHS = 50
RUNS = 1

def simulate():
    realtime = 0.0
    blkclock = 0.0
    d = 1.0

    ds = [d]

    for _ in range(EPOCHS):
        print(f"epoch: {_}, d: {d}, blkclock: {blkclock}, realtime: {realtime}")
        prev_blkclock = blkclock

        realtime += d * T

        if random.random() < P_MTP_CONTROLLED:
            blkclock += SLOW_CLOCK_SPEED
        else:
            blkclock = realtime


        d = d * T / (realtime - prev_blkclock)
        ds.append(d)

    return ds

# ---- 複数回実行 ----
all_ds = [simulate() for _ in range(RUNS)]

# ---- 描画 ----
plt.figure()
for ds in all_ds:
    plt.plot(ds, alpha=0.6)

plt.xlabel("epoch")
plt.ylabel("difficulty d")
plt.title("Timewarp simulation: difficulty evolution")
plt.show()
