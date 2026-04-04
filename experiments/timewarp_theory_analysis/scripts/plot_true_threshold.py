import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# beta ranges from 0.001 to 0.5
betas = np.linspace(0.001, 0.499, 1000)

# Calculate lambda * Delta based on the equation: beta = (1 - beta) / (1 + (1 - beta) * lambda * Delta)
# which gives lambda * Delta = (1 - 2 * beta) / (beta * (1 - beta))
lambda_delta = (1 - 2 * betas) / (betas * (1 - betas))
inv_lambda_delta = 1.0 / lambda_delta

plt.figure(figsize=(10, 6))
plt.plot(inv_lambda_delta, betas, label=r'True Threshold $\beta^*(\lambda\Delta)$', color='blue', linewidth=2)

plt.xlim(0.1, 100)
plt.xscale("log")
plt.ylim(0, 0.5)

plt.xlabel(r'Inverse: $1 / (\lambda \Delta)$', fontsize=12)
plt.ylabel(r'Adversary Mining Power Threshold ($\beta$)', fontsize=12)
plt.title('True Security Threshold for PoW Model\n(Dembo et al., "Everything is a Race and Nakamoto Always Wins")', fontsize=14)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)
plt.tight_layout()
out_path = (
    Path(__file__).resolve().parents[1]
    / "results"
    / "pow_true_threshold.png"
)
out_path.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out_path, dpi=200)
plt.close()
print(f"Saved: {out_path}")
