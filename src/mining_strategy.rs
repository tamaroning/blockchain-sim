use crate::task::{Task, TaskType};
use serde::{Deserialize, Serialize};

/// マイニング戦略のトレイト
pub trait MiningStrategy: Send + Sync {
    /// 戦略の名前を取得する
    fn name(&self) -> &'static str;

    /// ブロック生成時に呼ばれるコールバック
    /// 返り値: スケジュールすべきタスクのリスト（propagation task と mining task）
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
    /// 返り値: スケジュールすべきタスクのリスト（propagation task と mining task）
    ///
    /// `private_chain_blocks`:
    ///   プライベートチェーンのブロック ID リスト。
    ///   「公開チェーンの高さより大きいブロックのみ」を古い順に並べたものを想定。
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

        // 即座に propagation task をスケジュール（すべての他ノードに）
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

        // 次の mining task をスケジュール
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
        // 正直マイナーは受信時に特別な公開制御は行わず、
        // 単に次の採掘を続けるだけとする。
        vec![Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        )]
    }
}

/// k-lead selfish mining 戦略
///
/// モデル（この実装で採用する方針）
///
/// - リード: L := private_chain_height - public_chain_height_before
/// - 採掘時 (on_mining_block):
///     - 新しく掘ったブロックは常にプライベートに保持し、即時公開はしない。
///     - つまり「採掘時は常に非公開」。
/// - 受信時 (on_receiving_block):
///     - L <= 0:
///         - リードなし／負けているので公開しない（攻撃リセット相当）
///     - L == 1:
///         - 1 ブロック公開して 1 vs 1 のフォーク勝負に持ち込む
///     - 1 < L <= k:
///         - 何も公開せず、そのままリードを維持（受信により L は 1 減る想定）
///     - L > k:
///         - (L - k) 個の古いプライベートブロックを公開し、
///           プライベートリードが概ね k 程度になるよう調整する
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KLeadSelfishMiningStrategy {
    /// 許容する最大リード（目標値）
    pub k: i64,
}

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
        _block_id: usize,
        _current_time: i64,
        next_mining_time: i64,
        node_id: usize,
        _num_nodes: usize,
        _delay: i64,
        _private_chain_height: i64,
        _public_chain_height: i64,
    ) -> Vec<Task> {
        // 採掘時は常に非公開。
        vec![Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        )]
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

        if let Some(private_height) = private_chain_height {
            // 受信前のリード L = private - public_before
            let lead_before = private_height - public_chain_height_before;

            // 公開するブロック数を決定
            let num_blocks_to_publish: usize = if lead_before <= 0 {
                // L <= 0: そもそもリードがないので公開しない（攻撃失敗・リセット）
                0
            } else if lead_before == 1 {
                // L = 1: 1 ブロック公開して 1 vs 1 のフォーク勝負に持ち込む
                1
            } else if lead_before <= self.k {
                // 1 < L <= k: 許容リード内なので公開しない（L は 1 減ってもまだ >0）
                0
            } else {
                // L > k: 超過分 (L - k) を公開し、リードを概ね k に戻す
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
                        let publish_time = current_time + delay + idx as i64;
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

        // 次の mining task をスケジュール（常に）
        tasks.push(Task::new(
            next_mining_time,
            TaskType::BlockGeneration { minter: node_id },
        ));

        tasks
    }
}

/// マイニング戦略を enum で表現（シリアライズ/デシリアライズ可能）
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum MiningStrategyEnum {
    Honest,
    KLeadSelfishMining { k: i64 },
}

impl MiningStrategyEnum {
    /// enum から MiningStrategy トレイトオブジェクトを作成
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy),
            MiningStrategyEnum::KLeadSelfishMining { k } => {
                Box::new(KLeadSelfishMiningStrategy::new(*k))
            }
        }
    }
}
