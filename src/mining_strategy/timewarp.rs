use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

use super::{Action, MiningStrategy, longest_chain};

/// MTP（Median Time Past）算出に使う直近ブロック数のデフォルト値（Bitcoin 既定の 11）。
pub const DEFAULT_MTP_WINDOW_SIZE: usize = 11;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimewarpStrategy {
    current_block_id: BlockId,
    mtp_window_size: usize,
}

impl Default for TimewarpStrategy {
    fn default() -> Self {
        Self::with_window_size(DEFAULT_MTP_WINDOW_SIZE)
    }
}

impl TimewarpStrategy {
    pub fn with_window_size(mtp_window_size: usize) -> Self {
        assert!(mtp_window_size >= 1, "mtp_window_size は 1 以上である必要があります");
        Self {
            current_block_id: GENESIS_BLOCK_ID,
            mtp_window_size,
        }
    }

    pub fn mtp_window_size(&self) -> usize {
        self.mtp_window_size
    }
}

/// Bitcoin 風の timewarp 調整（MTP+1ms、2015 番目（高さ % 2016 == 2015）のブロックで +2h）。
///
/// `mtp_window_size` は MTP 算出に用いる「parent を含む直近ブロック数」。
/// 既定の 11 では parent と parent の祖先 10 ブロックのタイムスタンプ計 11 個から中央値を取る。
pub(crate) fn timewarp_adjusted_timestamp(
    original_timestamp: i64,
    parent_block_id: BlockId,
    block_height: i64,
    env: &Env,
    mtp_window_size: usize,
) -> i64 {
    if block_height % 2016 == 2015 {
        let two_hour_ms = 2 * 60 * 60 * 1000;
        return original_timestamp + two_hour_ms as i64;
    }

    assert!(mtp_window_size >= 1, "mtp_window_size は 1 以上である必要があります");

    let parent_timestamp = env.blockchain.get_block(parent_block_id).unwrap().time();
    let mut timestamps: Vec<i64> = env
        .blockchain
        .get_last_n_blocks(parent_block_id, mtp_window_size - 1)
        .iter()
        .map(|b| b.time())
        .collect();
    timestamps.push(parent_timestamp);

    timestamps.sort();
    let len = timestamps.len();
    let median = if len == 0 {
        unreachable!("No blocks in the blockchain")
    } else if len % 2 == 0 {
        timestamps[len / 2]
    } else {
        timestamps[len / 2]
    };
    median + 1_000
}

impl MiningStrategy for TimewarpStrategy {
    fn name(&self) -> &'static str {
        "TimeWarp"
    }

    fn on_mining_block(
        &mut self,
        block_id: BlockId,
        _current_time_us: i64,
        env: &Env,
        _node_id: NodeId,
    ) -> Vec<Action> {
        self.current_block_id = block_id;
        let mut actions = Vec::new();

        // Immediately schedule propagation tasks to all other nodes.
        for node in env.nodes() {
            actions.push(Action::Propagate {
                block_id,
                to: *node,
            });
        }

        // Schedule a new mining task.
        actions.push(Action::RestartMining {
            prev_block_id: block_id,
        });
        actions
    }

    fn on_receiving_block(
        &mut self,
        block_id: BlockId,
        _current_time_us: i64,
        env: &Env,
        _node_id: NodeId,
    ) -> Vec<Action> {
        let old_chain = self.current_block_id;
        self.current_block_id = longest_chain(env, self.current_block_id, block_id);

        if old_chain == self.current_block_id {
            // If the chain is not changed, continue mining.
            vec![]
        } else {
            // If the chain is changed, restart mining.
            vec![Action::RestartMining {
                prev_block_id: self.current_block_id,
            }]
        }
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
