use std::collections::HashSet;

use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, node::NodeId, simulator::Env};
use serde::{Deserialize, Serialize};

use super::{Action, MiningStrategy, longest_chain};

// Selfish mining strategy
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelfishMiningStrategy {
    /// The last block of the public chain.
    public_chain: BlockId,
    /// The last block of the private chain.
    private_chain: BlockId,
    /// The length of the private branch.
    private_branch_len: usize,
    // published blocks
    published_blocks: HashSet<BlockId>,
}

impl Default for SelfishMiningStrategy {
    fn default() -> Self {
        Self {
            public_chain: GENESIS_BLOCK_ID,
            private_chain: GENESIS_BLOCK_ID,
            private_branch_len: 0,
            published_blocks: HashSet::new(),
        }
    }
}

impl SelfishMiningStrategy {
    fn get_private_branch(&self, env: &Env) -> Vec<BlockId> {
        let mut blocks = Vec::new();

        let mut current_id = self.private_chain;
        for _ in 0..self.private_branch_len {
            blocks.push(current_id);
            let block = env.blockchain.get_block(current_id).unwrap();
            current_id = block.prev_block_id().unwrap();
            blocks.push(block.id());
        }

        blocks
    }

    fn get_last_private_block(&self) -> BlockId {
        self.private_chain
    }

    fn get_first_unpublished_private_block(&self, env: &Env) -> BlockId {
        let mut current_id = self.private_chain;
        for _ in 0..self.private_branch_len {
            let block = env.blockchain.get_block(current_id).unwrap();
            current_id = block.prev_block_id().unwrap();
        }
        current_id
    }

    fn publish_block(&mut self, block: BlockId, env: &Env) -> Vec<Action> {
        let published = self.published_blocks.contains(&block);
        if published {
            vec![]
        } else {
            let mut actions = vec![];
            self.published_blocks.insert(block);
            for node in env.nodes() {
                actions.push(Action::Propagate {
                    block_id: block,
                    to: *node,
                });
            }
            actions
        }
    }
}

impl MiningStrategy for SelfishMiningStrategy {
    fn name(&self) -> &'static str {
        "Selfish"
    }

    fn on_mining_block(
        &mut self,
        block_id: BlockId,
        _current_time: i64,
        env: &Env,
        _node_id: NodeId,
    ) -> Vec<Action> {
        let mut actions = Vec::new();

        let private_chain_height = env
            .blockchain
            .get_block(self.private_chain)
            .unwrap()
            .height();
        let public_chain_height = env
            .blockchain
            .get_block(self.public_chain)
            .unwrap()
            .height();
        let delta_prev = private_chain_height - public_chain_height;

        // Append a new block to the private chain.
        self.private_chain = block_id;
        self.private_branch_len += 1;

        // Was tie with branch of 1.
        if delta_prev == 0 && self.private_branch_len == 2 {
            // Publish all the blocks in the private chain.
            // This node can win due to the lead of 1 block.
            for private_block_id in self.get_private_branch(env) {
                actions.extend(self.publish_block(private_block_id, env));
            }
            self.private_branch_len = 0;
        }

        // Schedule a new mining task.
        actions.push(Action::RestartMining {
            prev_block_id: self.private_chain,
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
        let mut actions = Vec::new();

        let private_chain_height = env
            .blockchain
            .get_block(self.private_chain)
            .unwrap()
            .height();
        let public_chain_height = env
            .blockchain
            .get_block(self.public_chain)
            .unwrap()
            .height();
        let delta_prev = private_chain_height - public_chain_height;

        // update the public chain if the incoming block is longer than the known public chain.
        self.public_chain = longest_chain(env, self.public_chain, block_id);

        if delta_prev <= 0 {
            // they win.
            self.private_chain = self.public_chain;
            self.private_branch_len = 0;
            actions.push(Action::RestartMining {
                prev_block_id: self.public_chain,
            });
        } else if delta_prev == 1 {
            // publish the last block of the private chain.
            // Now the same length. Try our luck.
            let published_block_id = self.get_last_private_block();
            actions.extend(self.publish_block(published_block_id, env));
        } else if delta_prev == 2 {
            // Publish all the blocks in the private chain.
            // This node can win due to the lead of 1 block.
            for private_block_id in self.get_private_branch(env) {
                actions.extend(self.publish_block(private_block_id, env));
            }
            self.private_branch_len = 0;
        } else {
            // Publish the first unpublished block in the private chain.
            let published_block_id = self.get_first_unpublished_private_block(env);
            actions.extend(self.publish_block(published_block_id, env));
        }
        actions
    }
}
