use crate::task::{Task, TaskType};
use serde::{Deserialize, Serialize};

/// マイニング戦略のトレイト
pub trait MiningStrategy: Send + Sync {
    /// 戦略の名前を取得する
    fn name(&self) -> &'static str;

    /// ブロック生成時に呼ばれるコールバック
    /// 返り値: スケジュールすべきタスクのリスト（propagation taskとmining task）
    fn on_mining_block(
        &mut self,
        _block_id: usize,
        _current_time: i64,
        _next_mining_time: i64,
        _node_id: usize,
        _num_nodes: usize,
        _delay: i64,
        _private_chain_height: i64,
        _public_chain_height: i64,
    ) -> Vec<Task> {
        // デフォルト実装：空のリストを返す
        Vec::new()
    }

    /// ブロック受信時に呼ばれるコールバック
    /// 返り値: スケジュールすべきタスクのリスト（propagation taskとmining task）
    /// `private_chain_blocks`: プライベートチェーンのブロックIDリスト（公開チェーンの高さより大きいブロックのみ、古い順）
    fn on_receiving_block(
        &mut self,
        _block_id: usize,
        _current_time: i64,
        _next_mining_time: i64,
        _node_id: usize,
        _num_nodes: usize,
        _delay: i64,
        _private_chain_height: Option<i64>,
        _public_chain_height: i64,
        _private_tip_id: Option<usize>,
        _private_chain_blocks: Vec<usize>,
    ) -> Vec<Task> {
        // デフォルト実装：空のリストを返す
        Vec::new()
    }
}

/// 通常のマイニング戦略（何も調整しない）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HonestMiningStrategy;

impl MiningStrategy for HonestMiningStrategy {
    fn name(&self) -> &'static str {
        "Honest"
    }

    fn on_mining_block(
        &mut self,
        block_id: usize,
        current_time: i64,
        next_mining_time: i64,
        node_id: usize,
        num_nodes: usize,
        delay: i64,
        _private_chain_height: i64,
        _public_chain_height: i64,
    ) -> Vec<Task> {
        let mut tasks = Vec::new();

        // 即座にpropagation taskをスケジュール（すべての他のノードに）
        for i in 0..num_nodes {
            if i != node_id {
                let prop_time = current_time + delay;
                tasks.push(Task::new(
                    prop_time,
                    TaskType::Propagation {
                        from: node_id,
                        to: i,
                        block_id,
                    },
                ));
            }
        }

        // 次のmining taskをスケジュール
        tasks.push(Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        ));

        tasks
    }

    fn on_receiving_block(
        &mut self,
        _block_id: usize,
        _current_time: i64,
        next_mining_time: i64,
        node_id: usize,
        _num_nodes: usize,
        _delay: i64,
        _private_chain_height: Option<i64>,
        _public_chain_height: i64,
        _private_tip_id: Option<usize>,
        _private_chain_blocks: Vec<usize>,
    ) -> Vec<Task> {
        // 次のmining taskをスケジュール
        vec![Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        )]
    }
}

/// k-lead selfish mining戦略
/// プライベートチェーンが公開チェーンよりkブロック先に進むまでブロックを公開しない
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KLeadSelfishMiningStrategy {
    /// リードを取る必要があるブロック数
    pub k: i64,
}

/// モデル
/// 採掘時: 常に後悔しない
/// 受信時: リードがk未満: リードがkとなるように公開
impl KLeadSelfishMiningStrategy {
    pub fn new(k: i64) -> Self {
        Self { k }
    }
}

impl MiningStrategy for KLeadSelfishMiningStrategy {
    fn name(&self) -> &'static str {
        "KLeadSelfishMining"
    }

    fn on_mining_block(
        &mut self,
        block_id: usize,
        current_time: i64,
        next_mining_time: i64,
        node_id: usize,
        num_nodes: usize,
        delay: i64,
        private_chain_height: i64,
        public_chain_height: i64,
    ) -> Vec<Task> {
        let mut tasks = Vec::new();

        let should_propagate = private_chain_height - public_chain_height < self.k;

        if should_propagate {
            for i in 0..num_nodes {
                if i != node_id {
                    let prop_time = current_time + delay;
                    tasks.push(Task::new(
                        prop_time,
                        TaskType::Propagation {
                            from: node_id,
                            to: i,
                            block_id,
                        },
                    ));
                }
            }
        }

        // 次のmining taskをスケジュール（常に）
        tasks.push(Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        ));

        tasks
    }

    fn on_receiving_block(
        &mut self,
        _block_id: usize,
        current_time: i64,
        next_mining_time: i64,
        node_id: usize,
        num_nodes: usize,
        delay: i64,
        private_chain_height: Option<i64>,
        public_chain_height_before: i64,
        _private_tip_id: Option<usize>,
        private_chain_blocks: Vec<usize>,
    ) -> Vec<Task> {
        let mut tasks = Vec::new();

        // 正直マイナーのブロックを受け取ったときの行動
        // リードL = private_chain_height - public_chain_height_before（受信前の状態）
        // 受信後、public_chain_heightが1増えるので、新しいリードL' = L - 1
        if let Some(private_height) = private_chain_height {
            // 受信前のリード（正直マイナーのブロックを受信する前の状態）
            let lead_before = private_height - public_chain_height_before;

            // 公開するブロック数を決定
            let num_blocks_to_publish = if lead_before <= 0 {
                // L ≤ 0: 公開ブロック数 0 → Reset（正直チェーンへ追従、攻撃リセット）
                0
            } else if lead_before == 1 {
                // L = 1: 公開ブロック数 1 → L' = 0（1 vs 1のフォーク勝負へ、γ頼み）
                1
            } else if lead_before < self.k {
                // 1 < L < k: 公開ブロック数 1 → L' = L - 1（少しだけ公開して調整）
                1
            } else if lead_before == self.k {
                // L = k: 公開ブロック数 1 → L' = k - 1（リード維持のために調整公開）
                1
            } else {
                // L > k: 公開ブロック数 L - k → L' = k（超過分だけ公開して再び L = k に戻す）
                (lead_before - self.k) as usize
            };

            // 指定された数のブロックを公開（古い順に）
            let blocks_to_publish: Vec<usize> = private_chain_blocks
                .iter()
                .take(num_blocks_to_publish)
                .copied()
                .collect();

            for (idx, &block_id) in blocks_to_publish.iter().enumerate() {
                for i in 0..num_nodes {
                    if i != node_id {
                        let publish_time = current_time + (idx as i64 * delay);
                        tasks.push(Task::new(
                            publish_time,
                            TaskType::Propagation {
                                from: node_id,
                                to: i,
                                block_id,
                            },
                        ));
                    }
                }
            }
        }

        // 次のmining taskをスケジュール
        tasks.push(Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        ));

        tasks
    }
}

/// マイニング戦略をenumで表現（シリアライズ/デシリアライズ可能）
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum MiningStrategyEnum {
    Honest,
    KLeadSelfishMining { k: i64 },
}

impl MiningStrategyEnum {
    /// enumからMiningStrategyトレイトオブジェクトを作成
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy),
            MiningStrategyEnum::KLeadSelfishMining { k } => {
                Box::new(KLeadSelfishMiningStrategy::new(*k))
            }
        }
    }
}
