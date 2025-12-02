use crate::{block::GENESIS_BLOCK_ID, blockchain::BlockId, simulator::Env};
use serde::{Deserialize, Serialize};

fn longest_chain(env: &Env, block1_id: BlockId, block2_id: BlockId) -> BlockId {
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
    Propagate { block_id: BlockId, to: usize },
    /// Reschedule a mining task.
    RestartMining { prev_block_id: BlockId },
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
        _node_id: usize,
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
        _node_id: usize,
    ) -> Vec<Action> {
        Vec::new()
    }
}

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
        _node_id: usize,
    ) -> Vec<Action> {
        let mut actions = Vec::new();

        // Immediately schedule propagation tasks to all other nodes.
        for node in 0..env.num_nodes {
            actions.push(Action::Propagate { block_id, to: node });
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
        _node_id: usize,
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
}

// Selfish mining strategy
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelfishMiningStrategy {
    /// The last block of the public chain.
    public_chain: BlockId,
    /// The last block of the private chain.
    private_chain: BlockId,
    /// The length of the private branch.
    private_branch_len: usize,
}

impl Default for SelfishMiningStrategy {
    fn default() -> Self {
        Self {
            public_chain: GENESIS_BLOCK_ID,
            private_chain: GENESIS_BLOCK_ID,
            private_branch_len: 0,
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
        _node_id: usize,
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
                for other_node in 0..env.num_nodes {
                    actions.push(Action::Propagate {
                        block_id: private_block_id,
                        to: other_node,
                    });
                }
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
        _node_id: usize,
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
            for other_node in 0..env.num_nodes {
                actions.push(Action::Propagate {
                    block_id: published_block_id,
                    to: other_node,
                });
            }
        } else if delta_prev == 2 {
            // Publish all the blocks in the private chain.
            // This node can win due to the lead of 1 block.
            for private_block_id in self.get_private_branch(env) {
                for other_node in 0..env.num_nodes {
                    actions.push(Action::Propagate {
                        block_id: private_block_id,
                        to: other_node,
                    });
                }
            }
            self.private_branch_len = 0;
        } else {
            // Publish the first unpublished block in the private chain.
            let published_block_id = self.get_first_unpublished_private_block(env);
            for other_node in 0..env.num_nodes {
                actions.push(Action::Propagate {
                    block_id: published_block_id,
                    to: other_node,
                });
            }
        }
        actions
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum MiningStrategyEnum {
    Honest,
    Selfish,
}

impl MiningStrategyEnum {
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy::default()),
            MiningStrategyEnum::Selfish => Box::new(SelfishMiningStrategy::default()),
        }
    }
}
