use crate::block::Block;
use std::sync::atomic::AtomicUsize;

/// ブロックチェーンを管理する構造体
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

    pub fn add_block(&mut self, block: Block) -> usize {
        let id = block.id();
        self.blocks.push(block);
        id
    }

    pub fn get_block(&self, id: usize) -> Option<&Block> {
        self.blocks.get(id)
    }

    pub fn get_block_mut(&mut self, id: usize) -> Option<&mut Block> {
        self.blocks.get_mut(id)
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

    pub fn next_block_id(&self) -> usize {
        self.next_block_id.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    }

    pub fn last_block(&self) -> Option<&Block> {
        self.blocks.last()
    }
}

