use primitive_types::U256;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

use crate::{
    Protocol,
    block::{Block, GENESIS_BLOCK_ID},
    types::ChainMetrics,
};
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
    /// `BlockGeneration` イベントまで到達したブロック（キューから捨てられた未発火分は含まない）
    generation_completed: HashSet<BlockId>,
}

impl Blockchain {
    pub fn new(protocol: &dyn Protocol, total_hashrate: i64) -> Self {
        let mut blockchain = Self {
            blocks: Vec::new(),
            next_block_id: AtomicUsize::new(1),
            generation_completed: HashSet::new(),
        };
        blockchain.add_block(Block::genesis(protocol, total_hashrate));
        blockchain
    }

    pub fn add_block(&mut self, block: Block) -> BlockId {
        let id = block.id();
        self.blocks.push(block);
        id
    }

    /// マイニング完了イベントが処理されたブロックのみマークする（スケジュールのみでイベントが取代されたブロックは含めない）。
    pub fn mark_block_generation_completed(&mut self, block_id: BlockId) {
        self.generation_completed.insert(block_id);
    }

    /// 少なくとも一度 `Propagate` がキューに載ったブロックを「ネットワークに告知済み」とする。
    pub fn mark_block_announced(&mut self, block_id: BlockId) {
        if let Some(b) = self.get_block_mut(block_id) {
            b.set_announced(true);
        }
    }

    pub fn get_block(&self, id: BlockId) -> Option<&Block> {
        self.blocks.get(id.0)
    }

    pub fn get_block_mut(&mut self, id: BlockId) -> Option<&mut Block> {
        self.blocks.get_mut(id.0)
    }

    /// Get all blocks including orphan blocks.
    pub fn blocks(&self) -> &[Block] {
        &self.blocks
    }

    /// blockの祖先nブロックを返す　(block_id自身は含まない)
    /// blockの高さがnより小さい場合は、blockの全ての祖先ブロックを返す。
    pub fn get_last_n_blocks(&self, block_id: BlockId, n: usize) -> Vec<&Block> {
        let mut blocks = Vec::new();
        let mut current_block = self.get_block(block_id).unwrap();

        for _ in 0..n {
            if let Some(prev_block_id) = current_block.prev_block_id() {
                current_block = self.get_block(prev_block_id).unwrap();
                blocks.push(current_block);
            } else {
                break;
            }
        }
        assert!(!blocks.iter().any(|b| b.id() == block_id));
        blocks
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

    fn cumulative_chain_work(&self, tip_id: BlockId) -> U256 {
        self.get_block(tip_id)
            .map(|block| block.cumulative_chain_work())
            .unwrap_or(U256::zero())
    }

    /// ジェネシス、または `BlockGeneration` イベントが処理されたブロックのみを「有効」とする。
    #[inline]
    fn is_effective_chain_block(&self, id: BlockId) -> bool {
        id == GENESIS_BLOCK_ID || self.generation_completed.contains(&id)
    }

    /// 主鎖・指標では、採掘完了かつネットワークに告知済みのブロックだけを連鎖に含める。
    #[inline]
    fn is_public_main_chain_block(&self, id: BlockId) -> bool {
        if id == GENESIS_BLOCK_ID {
            return true;
        }
        self.get_block(id)
            .is_some_and(|b| b.is_announced()) && self.is_effective_chain_block(id)
    }

    /// tip から prev を辿り、ジェネシスまでの経路に未完了ブロックが無ければそのチェーンを返す。
    fn chain_from_tip_if_fully_effective(&self, tip: BlockId) -> Option<Vec<BlockId>> {
        let mut rev = Vec::new();
        let mut cur = tip;
        loop {
            if cur == GENESIS_BLOCK_ID {
                rev.push(cur);
                break;
            }
            if !self.is_public_main_chain_block(cur) {
                return None;
            }
            rev.push(cur);
            cur = self.get_block(cur)?.prev_block_id()?;
        }
        rev.reverse();
        Some(rev)
    }

    /// メインチェーンを取得する（採掘完了済みブロックのみを連鎖し、最重の有効先端を採用）
    /// Return: A list of block IDs. (oldest to newest)
    pub fn get_main_chain(&self) -> Vec<BlockId> {
        if self.blocks.is_empty() {
            return vec![GENESIS_BLOCK_ID];
        }

        let mut best_weight = self.cumulative_chain_work(GENESIS_BLOCK_ID);
        let mut best_tips: Vec<BlockId> = vec![GENESIS_BLOCK_ID];
        for block in &self.blocks {
            if !self.is_public_main_chain_block(block.id()) {
                continue;
            }
            let w = self.cumulative_chain_work(block.id());
            match w.cmp(&best_weight) {
                std::cmp::Ordering::Greater => {
                    best_weight = w;
                    best_tips = vec![block.id()];
                }
                std::cmp::Ordering::Equal => best_tips.push(block.id()),
                std::cmp::Ordering::Less => {}
            }
        }

        for &tip in &best_tips {
            if let Some(ch) = self.chain_from_tip_if_fully_effective(tip) {
                return ch;
            }
        }

        // 最大 work の先端がすべて有効な祖先を持たない（異常）とき、次点以降を探索
        let mut tips: Vec<(U256, BlockId)> = self
            .blocks
            .iter()
            .filter(|b| self.is_public_main_chain_block(b.id()))
            .map(|b| (self.cumulative_chain_work(b.id()), b.id()))
            .collect();
        tips.sort_by(|a, b| b.0.cmp(&a.0));
        for (_, tip) in tips {
            if best_tips.contains(&tip) {
                continue;
            }
            if let Some(ch) = self.chain_from_tip_if_fully_effective(tip) {
                return ch;
            }
        }

        vec![GENESIS_BLOCK_ID]
    }

    /// 採掘完了済みメインチェーンの先端ブロックの高さ（ジェネシスのみなら 0）
    pub fn main_chain_height(&self) -> i64 {
        self.get_main_chain()
            .last()
            .and_then(|&id| self.get_block(id))
            .map(|b| b.height())
            .unwrap_or(0)
    }

    /// ジェネシス以外で、実際にマイニング完了イベントが発火したブロックを「採掘済み」とみなし、
    /// メインチェーンに乗らないものを stale と数える（未発火のプレ生成ブロックは母集団に含めない）。
    pub fn chain_metrics(&self) -> ChainMetrics {
        let main = self.get_main_chain();
        let main_set: HashSet<_> = main.iter().copied().collect();
        let mut mined_blocks: u64 = 0;
        let mut main_mined_blocks: u64 = 0;
        for block in self.blocks() {
            if block.height() == 0 {
                continue;
            }
            if !self.generation_completed.contains(&block.id()) {
                continue;
            }
            if !block.is_announced() {
                continue;
            }
            mined_blocks += 1;
            if main_set.contains(&block.id()) {
                main_mined_blocks += 1;
            }
        }
        let stale_blocks = mined_blocks.saturating_sub(main_mined_blocks);
        let stale_rate = if mined_blocks > 0 {
            stale_blocks as f64 / mined_blocks as f64
        } else {
            0.0
        };
        ChainMetrics {
            mined_blocks,
            main_mined_blocks,
            stale_blocks,
            stale_rate,
        }
    }
}
