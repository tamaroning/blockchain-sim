use std::collections::HashSet;

use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

use super::{Action, MiningStrategy, longest_chain};

/// Private-chain attack: 採掘ブロックを隠蔽し、公開鎖より長くなった時点で一斉公開する。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrivateAttackMiningStrategy {
    public_chain: BlockId,
    private_chain: BlockId,
    private_branch_len: usize,
    published_blocks: HashSet<BlockId>,
}

impl Default for PrivateAttackMiningStrategy {
    fn default() -> Self {
        Self {
            public_chain: GENESIS_BLOCK_ID,
            private_chain: GENESIS_BLOCK_ID,
            private_branch_len: 0,
            published_blocks: HashSet::new(),
        }
    }
}

impl PrivateAttackMiningStrategy {
    fn chain_height(&self, env: &Env, tip: BlockId) -> i64 {
        env.blockchain.get_block(tip).unwrap().height()
    }

    fn get_private_branch(&self, env: &Env) -> Vec<BlockId> {
        let mut blocks = Vec::new();
        let mut current_id = self.private_chain;
        for _ in 0..self.private_branch_len {
            blocks.push(current_id);
            let block = env.blockchain.get_block(current_id).unwrap();
            current_id = block.prev_block_id().unwrap();
        }
        blocks.reverse();
        blocks
    }

    fn publish_block(&mut self, block: BlockId, env: &Env) -> Vec<Action> {
        if self.published_blocks.contains(&block) {
            return vec![];
        }
        self.published_blocks.insert(block);
        env.nodes()
            .iter()
            .map(|node| Action::Propagate {
                block_id: block,
                to: *node,
            })
            .collect()
    }

    fn publish_private_chain_if_ahead(&mut self, env: &Env) -> Vec<Action> {
        let private_h = self.chain_height(env, self.private_chain);
        let public_h = self.chain_height(env, self.public_chain);
        if private_h <= public_h {
            return vec![];
        }
        let mut actions = Vec::new();
        for block_id in self.get_private_branch(env) {
            actions.extend(self.publish_block(block_id, env));
        }
        self.private_branch_len = 0;
        actions
    }
}

impl MiningStrategy for PrivateAttackMiningStrategy {
    fn name(&self) -> &'static str {
        "private_attack"
    }

    fn on_mining_block(
        &mut self,
        block_id: BlockId,
        _current_time_us: i64,
        env: &Env,
        _node_id: NodeId,
    ) -> Vec<Action> {
        self.private_chain = block_id;
        self.private_branch_len += 1;

        let mut actions = self.publish_private_chain_if_ahead(env);
        actions.push(Action::RestartMining {
            prev_block_id: self.private_chain,
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
        self.public_chain = longest_chain(env, self.public_chain, block_id);

        let private_h = self.chain_height(env, self.private_chain);
        let public_h = self.chain_height(env, self.public_chain);

        if private_h <= public_h {
            self.private_chain = self.public_chain;
            self.private_branch_len = 0;
            return vec![Action::RestartMining {
                prev_block_id: self.public_chain,
            }];
        }

        let mut actions = self.publish_private_chain_if_ahead(env);
        actions.push(Action::RestartMining {
            prev_block_id: self.private_chain,
        });
        actions
    }
}
