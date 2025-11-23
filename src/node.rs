use crate::types::MiningStrategy;

/// ノードを表す構造体
pub struct Node {
    id: usize,
    hashrate: i64,
    current_block_id: usize,
    next_mining_time: Option<i64>,
    mining_strategy: Box<dyn MiningStrategy>,
    /// プライベートチェーンの先頭ブロックID（k-lead selfish mining用）
    private_chain_tip: Option<usize>,
}

impl Node {
    pub fn new(id: usize, hashrate: i64) -> Self {
        Self::new_with_strategy(id, hashrate, Box::new(crate::types::HonestMiningStrategy))
    }

    pub fn new_with_strategy(
        id: usize,
        hashrate: i64,
        mining_strategy: Box<dyn MiningStrategy>,
    ) -> Self {
        Self {
            id,
            hashrate,
            current_block_id: 0, // ジェネシスブロック
            next_mining_time: None,
            mining_strategy,
            private_chain_tip: None,
        }
    }

    pub fn id(&self) -> usize {
        self.id
    }

    pub fn hashrate(&self) -> i64 {
        self.hashrate
    }

    pub fn current_block_id(&self) -> usize {
        self.current_block_id
    }

    pub fn set_current_block_id(&mut self, block_id: usize) {
        self.current_block_id = block_id;
    }

    pub fn next_mining_time(&self) -> Option<i64> {
        self.next_mining_time
    }

    pub fn set_next_mining_time(&mut self, time: Option<i64>) {
        self.next_mining_time = time;
    }

    pub fn reset(&mut self) {
        self.current_block_id = 0;
        self.next_mining_time = None;
        self.private_chain_tip = None;
    }

    pub fn mining_strategy(&self) -> &dyn MiningStrategy {
        self.mining_strategy.as_ref()
    }

    pub fn mining_strategy_mut(&mut self) -> &mut dyn MiningStrategy {
        self.mining_strategy.as_mut()
    }

    pub fn private_chain_tip(&self) -> Option<usize> {
        self.private_chain_tip
    }

    pub fn set_private_chain_tip(&mut self, block_id: Option<usize>) {
        self.private_chain_tip = block_id;
    }
}

