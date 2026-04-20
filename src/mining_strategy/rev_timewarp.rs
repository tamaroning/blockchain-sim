use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

use super::{Action, MiningStrategy, longest_chain, timewarp::timewarp_mtp_plus_one_ms};

/// timewarp と同様に常に MTP+1 を使うが、調整期間末尾（高さ % 2016 == 2015）でも +2h を付けない。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RevTimewarpStrategy {
    current_block_id: BlockId,
}

impl Default for RevTimewarpStrategy {
    fn default() -> Self {
        Self {
            current_block_id: GENESIS_BLOCK_ID,
        }
    }
}

impl MiningStrategy for RevTimewarpStrategy {
    fn name(&self) -> &'static str {
        "rev_timewarp"
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

        for node in env.nodes() {
            actions.push(Action::Propagate {
                block_id,
                to: *node,
            });
        }

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
            vec![]
        } else {
            vec![Action::RestartMining {
                prev_block_id: self.current_block_id,
            }]
        }
    }

    fn handle_timestamp(
        &self,
        _original_timestamp: i64,
        parent_block_id: BlockId,
        _block_height: i64,
        env: &Env,
    ) -> i64 {
        timewarp_mtp_plus_one_ms(parent_block_id, env)
    }
}
