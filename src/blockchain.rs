use serde::{Deserialize, Serialize};

use crate::block::{Block, GENESIS_BLOCK_ID};
use std::sync::atomic::AtomicUsize;

#[derive(Clone, Copy, Debug, Hash, Eq, PartialEq, Serialize, Deserialize)]
pub struct BlockId(usize);

impl BlockId {
    pub const fn new(id: usize) -> Self {
        Self(id)
    }
}

impl std::fmt::Display for BlockId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// A pool for blocks which maintains a single global instance of the blockchain.
pub struct Blockchain {
    blocks: Vec<Block>,
    next_block_id: AtomicUsize,
}

impl Blockchain {
    pub fn new() -> Self {
        let mut blockchain = Self {
            blocks: Vec::new(),
            next_block_id: AtomicUsize::new(1),
        };
        blockchain.add_block(Block::genesis());
        blockchain
    }

    pub fn add_block(&mut self, block: Block) -> BlockId {
        let id = block.id();
        self.blocks.push(block);
        id
    }

    pub fn get_block(&self, id: BlockId) -> Option<&Block> {
        self.blocks.get(id.0)
    }

    pub fn get_block_mut(&mut self, id: BlockId) -> Option<&mut Block> {
        self.blocks.get_mut(id.0)
    }

    pub fn blocks(&self) -> &[Block] {
        &self.blocks
    }

    pub fn len(&self) -> usize {
        self.blocks.len()
    }

    pub fn max_height(&self) -> i64 {
        self.blocks.iter().map(|b| b.height()).max().unwrap_or(0)
    }

    pub fn next_block_id(&self) -> BlockId {
        BlockId::new(
            self.next_block_id
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst),
        )
    }

    pub fn last_block(&self) -> Option<&Block> {
        self.blocks.last()
    }

    /// メインチェーンを取得する（最高heightのブロックからprev_block_idを辿る）
    /// Return: A list of block IDs. (oldest to newest)
    pub fn get_main_chain(&self) -> Vec<BlockId> {
        let max_height = self.max_height();
        if max_height == 0 {
            return vec![GENESIS_BLOCK_ID]; // ジェネシスブロックのみ
        }

        // 最高heightを持つブロックを探す
        let mut tip_block_id = None;
        for block in &self.blocks {
            if block.height() == max_height {
                tip_block_id = Some(block.id());
                break;
            }
        }

        let Some(tip_id) = tip_block_id else {
            return vec![GENESIS_BLOCK_ID];
        };

        // prev_block_idを辿ってメインチェーンを構築
        let mut chain = Vec::new();
        let mut current_id = tip_id;
        loop {
            chain.push(current_id);
            let Some(block) = self.get_block(current_id) else {
                break;
            };
            match block.prev_block_id() {
                Some(prev_id) => current_id = prev_id,
                None => break, // ジェネシスブロックに到達
            }
        }

        chain.reverse(); // ジェネシスブロックから順に
        chain
    }
}
