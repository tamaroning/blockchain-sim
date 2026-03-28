use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

use super::{Action, MiningStrategy, longest_chain};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimewarpStrategy {
    current_block_id: BlockId,
}

impl Default for TimewarpStrategy {
    fn default() -> Self {
        Self {
            current_block_id: GENESIS_BLOCK_ID,
        }
    }
}

/// Bitcoin 風の timewarp 調整（MTP+1、2015 番目のブロックで +2h）。
pub(crate) fn timewarp_adjusted_timestamp(
    original_timestamp: i64,
    parent_block_id: BlockId,
    block_height: i64,
    env: &Env,
) -> i64 {
    if block_height % 2016 == 2015 {
        let two_hour_ms = 2 * 60 * 60 * 1000;
        return original_timestamp + two_hour_ms as i64;
    }

    let mut last_11_block_timestamps = env
        .blockchain
        .get_last_n_blocks(parent_block_id, 10)
        .iter()
        .map(|b| b.time())
        .collect::<Vec<i64>>();
    let _11th_block_timestamp = env.blockchain.get_block(parent_block_id).unwrap().time();
    last_11_block_timestamps.push(_11th_block_timestamp);
    let mut timestamps = last_11_block_timestamps;

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
        _current_time: i64,
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
        _current_time: i64,
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
        timewarp_adjusted_timestamp(original_timestamp, parent_block_id, block_height, env)
    }
}
