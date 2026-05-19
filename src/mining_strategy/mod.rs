use primitive_types::U256;
use serde::{Deserialize, Serialize};

use crate::{blockchain::BlockId, node::NodeId, simulator::Env};

mod honest;
mod selfish;
mod selfish_timewarp;
mod timewarp;

pub use honest::HonestMiningStrategy;
pub use selfish::SelfishMiningStrategy;
pub use selfish_timewarp::SelfishTimewarpStrategy;
pub use timewarp::TimewarpStrategy;

fn cumulative_chain_work(env: &Env, tip_id: BlockId) -> U256 {
    env.blockchain
        .get_block(tip_id)
        .map(|block| block.cumulative_chain_work())
        .unwrap_or(U256::zero())
}

pub(crate) fn longest_chain(env: &Env, block1_id: BlockId, block2_id: BlockId) -> BlockId {
    let weight1 = cumulative_chain_work(env, block1_id);
    let weight2 = cumulative_chain_work(env, block2_id);
    match weight1.cmp(&weight2) {
        std::cmp::Ordering::Greater => block1_id,
        std::cmp::Ordering::Less => block2_id,
        std::cmp::Ordering::Equal => {
            // Tie-break: keep current head.
            // `longest_chain(current_head, incoming_head)` call sites preserve first-seen behavior.
            block1_id
        }
    }
}

pub enum Action {
    /// Propagate a block to a node.
    Propagate { block_id: BlockId, to: NodeId },
    /// Reschedule a mining task.
    RestartMining {
        /// The previous block ID.
        prev_block_id: BlockId,
    },
}

/// マイニング戦略のトレイト
pub trait MiningStrategy: Send + Sync {
    /// 戦略の名前を取得する
    fn name(&self) -> &'static str;

    /// honest ノード（通常マイニング）かどうか
    fn is_honest(&self) -> bool {
        false
    }

    /// ブロック生成時に呼ばれるコールバック
    /// Return: A list of actions to schedule.
    fn on_mining_block(
        &mut self,
        _block_id: BlockId,
        _current_time_us: i64,
        _env: &Env,
        _node_id: NodeId,
    ) -> Vec<Action> {
        Vec::new()
    }

    /// ブロック受信時に呼ばれるコールバック
    /// Return: A list of actions to schedule.
    fn on_receiving_block(
        &mut self,
        _block_id: BlockId,
        _current_time_us: i64,
        _env: &Env,
        _node_id: NodeId,
    ) -> Vec<Action> {
        Vec::new()
    }

    fn handle_timestamp(
        &self,
        timestamp: i64,
        _parent_block_id: BlockId,
        _block_height: i64,
        _env: &Env,
    ) -> i64 {
        timestamp
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum MiningStrategyEnum {
    Honest,
    Selfish,
    SelfishTimewarp,
    Timewarp,
}

impl MiningStrategyEnum {
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy::default()),
            MiningStrategyEnum::Selfish => Box::new(SelfishMiningStrategy::default()),
            MiningStrategyEnum::SelfishTimewarp => Box::new(SelfishTimewarpStrategy::default()),
            MiningStrategyEnum::Timewarp => Box::new(TimewarpStrategy::default()),
        }
    }
}
