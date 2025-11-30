use crate::block::Block;
use std::sync::atomic::AtomicUsize;

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
        self.next_block_id
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    }

    pub fn last_block(&self) -> Option<&Block> {
        self.blocks.last()
    }

    /// メインチェーンを取得する（最高heightのブロックからprev_block_idを辿る）
    pub fn get_main_chain(&self) -> Vec<usize> {
        let max_height = self.max_height();
        if max_height == 0 {
            return vec![0]; // ジェネシスブロックのみ
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
            return vec![0];
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
