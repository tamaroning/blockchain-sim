use crate::{blockchain::BlockId, node::NodeId, simulator::Env};

use super::{
    Action, MiningStrategy, selfish::SelfishMiningStrategy, timewarp::timewarp_adjusted_timestamp,
};

/// Selfish mining と同一の分岐・公開ロジックに、timewarp と同様のタイムスタンプ調整を加えた戦略。
pub struct SelfishTimewarpStrategy(SelfishMiningStrategy);

impl Default for SelfishTimewarpStrategy {
    fn default() -> Self {
        Self(SelfishMiningStrategy::default())
    }
}

impl MiningStrategy for SelfishTimewarpStrategy {
    fn name(&self) -> &'static str {
        "selfish_timewarp"
    }

    fn on_mining_block(
        &mut self,
        block_id: BlockId,
        current_time: i64,
        env: &Env,
        node_id: NodeId,
    ) -> Vec<Action> {
        self.0.on_mining_block(block_id, current_time, env, node_id)
    }

    fn on_receiving_block(
        &mut self,
        block_id: BlockId,
        current_time: i64,
        env: &Env,
        node_id: NodeId,
    ) -> Vec<Action> {
        self.0
            .on_receiving_block(block_id, current_time, env, node_id)
    }

    fn handle_timestamp(
        &self,
        original_timestamp: i64,
        parent_block_id: BlockId,
        block_height: i64,
        env: &Env,
    ) -> i64 {
        timewarp_adjusted_timestamp(original_timestamp, parent_block_id, block_height, env)
    }
}
