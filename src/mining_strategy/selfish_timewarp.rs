use crate::{blockchain::BlockId, node::NodeId, simulator::Env};

use super::{
    Action, MiningStrategy,
    selfish::SelfishMiningStrategy,
    timewarp::{DEFAULT_MTP_WINDOW_SIZE, timewarp_adjusted_timestamp},
};

/// Selfish mining と同一の分岐・公開ロジックに、timewarp と同様のタイムスタンプ調整を加えた戦略。
pub struct SelfishTimewarpStrategy {
    inner: SelfishMiningStrategy,
    mtp_window_size: usize,
}

impl Default for SelfishTimewarpStrategy {
    fn default() -> Self {
        Self::with_window_size(DEFAULT_MTP_WINDOW_SIZE)
    }
}

impl SelfishTimewarpStrategy {
    pub fn with_window_size(mtp_window_size: usize) -> Self {
        assert!(mtp_window_size >= 1, "mtp_window_size は 1 以上である必要があります");
        Self {
            inner: SelfishMiningStrategy::default(),
            mtp_window_size,
        }
    }

    pub fn mtp_window_size(&self) -> usize {
        self.mtp_window_size
    }
}

impl MiningStrategy for SelfishTimewarpStrategy {
    fn name(&self) -> &'static str {
        "selfish_timewarp"
    }

    fn on_mining_block(
        &mut self,
        block_id: BlockId,
        current_time_us: i64,
        env: &Env,
        node_id: NodeId,
    ) -> Vec<Action> {
        self.inner
            .on_mining_block(block_id, current_time_us, env, node_id)
    }

    fn on_receiving_block(
        &mut self,
        block_id: BlockId,
        current_time_us: i64,
        env: &Env,
        node_id: NodeId,
    ) -> Vec<Action> {
        self.inner
            .on_receiving_block(block_id, current_time_us, env, node_id)
    }

    fn handle_timestamp(
        &self,
        original_timestamp: i64,
        parent_block_id: BlockId,
        block_height: i64,
        env: &Env,
    ) -> i64 {
        timewarp_adjusted_timestamp(
            original_timestamp,
            parent_block_id,
            block_height,
            env,
            self.mtp_window_size,
        )
    }
}
