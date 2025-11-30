use crate::{block::GENESIS_BLOCK_ID, simulator::Env};
use serde::{Deserialize, Serialize};

pub enum Action {
    /// Propagate a block to a node.
    Propagate { block_id: usize, to: usize },
    /// Reschedule a mining task.
    RestartMining { prev_block_id: usize },
}

/// マイニング戦略のトレイト
pub trait MiningStrategy: Send + Sync {
    /// 戦略の名前を取得する
    fn name(&self) -> &'static str;

    /// ブロック生成時に呼ばれるコールバック
    /// Return: A list of actions to schedule.
    fn on_mining_block(
        &mut self,
        _block_id: usize,
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
        _block_id: usize,
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
    current_block_id: usize,
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
        block_id: usize,
        _current_time: i64,
        env: &Env,
        node_id: usize,
    ) -> Vec<Action> {
        let mut actions = Vec::new();

        // Immediately schedule propagation tasks to all other nodes.
        for node in 0..env.num_nodes {
            if node != node_id {
                actions.push(Action::Propagate { block_id, to: node });
            }
        }

        // Schedule a new mining task.
        actions.push(Action::RestartMining {
            prev_block_id: block_id,
        });
        actions
    }

    fn on_receiving_block(
        &mut self,
        block_id: usize,
        _current_time: i64,
        env: &Env,
        _node_id: usize,
    ) -> Vec<Action> {
        let incoming_block_height = env.blockchain.get_block(block_id).unwrap().height();
        let my_chain_height = env
            .blockchain
            .get_block(self.current_block_id)
            .unwrap()
            .height();

        if incoming_block_height > my_chain_height {
            vec![Action::RestartMining {
                prev_block_id: block_id,
            }]
        } else {
            vec![]
        }
    }
}

// Selfish mining strategy
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelfishMiningStrategy {
    public_chain: usize,
    private_chain: usize,
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
    fn get_private_branch(&self, env: &Env) -> Vec<usize> {
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

    fn get_last_private_block(&self, env: &Env) -> usize {
        self.private_chain
    }

    fn get_first_unpublished_private_block(&self, env: &Env) -> usize {
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
        block_id: usize,
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
        block_id: usize,
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

        println!("block_height: {}", env.blockchain.get_block(block_id).unwrap().height());
        println!(
            "private_chain_height: {}, public_chain_height: {}, delta_prev: {}",
            private_chain_height, public_chain_height, delta_prev
        );

        // update the public chain if the incoming block is longer than the known public chain.
        if env.blockchain.get_block(block_id).unwrap().height() > public_chain_height {
            self.public_chain = block_id;
        }

        if delta_prev == 0 {
            // they win.
            self.private_chain = self.public_chain;
            self.private_branch_len = 0;
        } else if delta_prev == 1 {
            // publish the last block of the private chain.
            // Now the same length. Try our luck.
            let published_block_id = self.get_last_private_block(env);
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

        actions.push(Action::RestartMining {
            prev_block_id: self.private_chain,
        });
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
