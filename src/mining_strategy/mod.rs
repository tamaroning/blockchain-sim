use crate::{blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

mod honest;
mod selfish;
mod timewarp;

pub use honest::HonestMiningStrategy;
pub use selfish::SelfishMiningStrategy;
pub use timewarp::TimewarpStrategy;

pub(crate) fn longest_chain(env: &Env, block1_id: BlockId, block2_id: BlockId) -> BlockId {
    let block1 = env.blockchain.get_block(block1_id).unwrap();
    let block2 = env.blockchain.get_block(block2_id).unwrap();
    let height1 = block1.height();
    let height2 = block2.height();
    if height1 >= height2 {
        block1_id
    } else if height1 < height2 {
        block2_id
    } else {
        if block1.rand() > block2.rand() {
            block1_id
        } else {
            block2_id
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
    Timewarp,
}

impl MiningStrategyEnum {
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy::default()),
            MiningStrategyEnum::Selfish => Box::new(SelfishMiningStrategy::default()),
            MiningStrategyEnum::Timewarp => Box::new(TimewarpStrategy::default()),
        }
    }
}
