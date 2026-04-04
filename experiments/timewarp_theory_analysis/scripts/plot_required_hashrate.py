import matplotlib

matplotlib.use("Agg")

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# 1. パラメータの初期設定
t_prop = 2.0         # ブロック伝播遅延 (秒)
H_total = 1.0        # 総ハッシュレート (相対値として1.0とする)
D_0 = 600.0          # 初期難易度 (初期 t_gen が600秒=10分となるように設定)
alpha_req = 0.88     # MTP支配に必要な実効ハッシュレート閾値 (理論値 88%)
epochs = 10          # シミュレーションするエポック数

# データ記録用リスト
epoch_list = list(range(epochs + 1))
alpha_needed_list = []
D_n = D_0

# 2. エポックごとの状態推移計算
for n in epoch_list:
    # 現在のエポックの平均ブロック生成時間
    t_gen_n = D_n / H_total
    
    # ポアソン過程に基づくオーファン率の計算
    P_orphan_n = 1.0 - np.exp(-t_prop / t_gen_n)
    
    # 攻撃を継続するために必要な「名目ハッシュレート割合」の算出
    # 式: alpha >= (alpha_req * (1 - P_orphan)) / (1 - alpha_req * P_orphan)
    numerator = alpha_req * (1.0 - P_orphan_n)
    denominator = 1.0 - alpha_req * P_orphan_n
    
    if denominator <= 0:
        alpha_needed = 0.0 # 誠実なノードが完全に崩壊した状態
    else:
        alpha_needed = numerator / denominator
        
    alpha_needed_list.append(alpha_needed)
    
    # 次エポックへ向けて難易度が1/4に低下すると仮定（Timewarp成功時の最大低下幅）
    D_n = D_n / 4.0

# 3. シミュレーション結果のプロット
plt.figure(figsize=(10, 6))
plt.plot(epoch_list, [a * 100 for a in alpha_needed_list], marker='o', color='b')
plt.title("Required Nominal Hashrate for Timewarp Attack over Epochs")
plt.xlabel("Epochs since Attack Started")
plt.ylabel("Required Nominal Hashrate (%)")
plt.grid(True, linestyle='--', alpha=0.7)
plt.axhline(y=alpha_req * 100, color='r', linestyle='--', label=f'Initial Threshold ({alpha_req*100}%)')
plt.ylim(0, 100)
plt.legend()
out_path = Path(__file__).resolve().parents[1] / "results" / "required_hashrate.png"
out_path.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out_path, dpi=200)
plt.close()
print(f"Saved: {out_path}")
