use crate::{blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

mod honest;
mod selfish;
mod selfish_timewarp;
mod timewarp;

pub use honest::HonestMiningStrategy;
pub use selfish::SelfishMiningStrategy;
pub use selfish_timewarp::SelfishTimewarpStrategy;
pub use timewarp::TimewarpStrategy;

fn cumulative_chain_weight(env: &Env, tip_id: BlockId) -> f64 {
    env.blockchain
        .get_block(tip_id)
        .map(|block| block.cumulative_chain_weight())
        .unwrap_or(0.0)
}

pub(crate) fn longest_chain(env: &Env, block1_id: BlockId, block2_id: BlockId) -> BlockId {
    let weight1 = cumulative_chain_weight(env, block1_id);
    let weight2 = cumulative_chain_weight(env, block2_id);
    if weight1 > weight2 {
        block1_id
    } else if weight2 > weight1 {
        block2_id
    } else {
        // Tie-break: keep current head.
        // `longest_chain(current_head, incoming_head)` call sites preserve first-seen behavior.
        block1_id
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

    /// ブロック生成時に呼ばれるコールバック
    /// Return: A list of actions to schedule.
    fn on_mining_block(
        &mut self,
        _block_id: BlockId,
        _current_time: i64,
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
        _current_time: i64,
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
