use crate::mining_strategy::MiningStrategy;

/// ノードを表す構造体
pub struct Node {
    /// The ID of the node.
    id: usize,
    /// The hashrate of the node.
    hashrate: i64,
    mining_strategy: Box<dyn MiningStrategy>,
}

impl Node {
    pub fn new(id: usize, hashrate: i64) -> Self {
        Self::new_with_strategy(
            id,
            hashrate,
            Box::new(crate::mining_strategy::HonestMiningStrategy),
        )
    }

    pub fn new_with_strategy(
        id: usize,
        hashrate: i64,
        mining_strategy: Box<dyn MiningStrategy>,
    ) -> Self {
        Self {
            id,
            hashrate,
            mining_strategy,
        }
    }

    pub fn id(&self) -> usize {
        self.id
    }

    pub fn hashrate(&self) -> i64 {
        self.hashrate
    }

    pub fn mining_strategy(&self) -> &dyn MiningStrategy {
        self.mining_strategy.as_ref()
    }

    pub fn mining_strategy_mut(&mut self) -> &mut dyn MiningStrategy {
        self.mining_strategy.as_mut()
    }
}
