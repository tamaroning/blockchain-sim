use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

use super::{Action, MiningStrategy, longest_chain};

/// 通常のマイニング戦略（何も調整しない）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HonestMiningStrategy {
    current_block_id: BlockId,
}

impl Default for HonestMiningStrategy {
    fn default() -> Self {
        Self {
            current_block_id: GENESIS_BLOCK_ID,
        }
    }
}

impl MiningStrategy for HonestMiningStrategy {
    fn name(&self) -> &'static str {
        "Honest"
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
        timestamp: i64,
        _parent_block_id: BlockId,
        _block_height: i64,
        _env: &Env,
    ) -> i64 {
        timestamp
    }
}
