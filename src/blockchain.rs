use primitive_types::U256;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

use crate::{
    Protocol,
    block::{Block, GENESIS_BLOCK_ID},
    node::NodeId,
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

    /// 主鎖候補: 採掘完了済み。`include_unannounced` が false のときは告知済みのみ。
    #[inline]
    fn is_main_chain_candidate(&self, id: BlockId, include_unannounced: bool) -> bool {
        if id == GENESIS_BLOCK_ID {
            return true;
        }
        if !self.is_effective_chain_block(id) {
            return false;
        }
        if include_unannounced {
            return true;
        }
        self.get_block(id).is_some_and(|b| b.is_announced())
    }

    /// tip から prev を辿り、ジェネシスまでの経路に未完了ブロックが無ければそのチェーンを返す。
    fn chain_from_tip_if_fully_effective(
        &self,
        tip: BlockId,
        include_unannounced: bool,
    ) -> Option<Vec<BlockId>> {
        let mut rev = Vec::new();
        let mut cur = tip;
        loop {
            if cur == GENESIS_BLOCK_ID {
                rev.push(cur);
                break;
            }
            if !self.is_main_chain_candidate(cur, include_unannounced) {
                return None;
            }
            rev.push(cur);
            cur = self.get_block(cur)?.prev_block_id()?;
        }
        rev.reverse();
        Some(rev)
    }

    fn compute_main_chain(&self, include_unannounced: bool) -> Vec<BlockId> {
        if self.blocks.is_empty() {
            return vec![GENESIS_BLOCK_ID];
        }

        let mut best_weight = self.cumulative_chain_work(GENESIS_BLOCK_ID);
        let mut best_tips: Vec<BlockId> = vec![GENESIS_BLOCK_ID];
        for block in &self.blocks {
            if !self.is_main_chain_candidate(block.id(), include_unannounced) {
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
            if let Some(ch) = self.chain_from_tip_if_fully_effective(tip, include_unannounced) {
                return ch;
            }
        }

        // 最大 work の先端がすべて有効な祖先を持たない（異常）とき、次点以降を探索
        let mut tips: Vec<(U256, BlockId)> = self
            .blocks
            .iter()
            .filter(|b| self.is_main_chain_candidate(b.id(), include_unannounced))
            .map(|b| (self.cumulative_chain_work(b.id()), b.id()))
            .collect();
        tips.sort_by(|a, b| b.0.cmp(&a.0));
        for (_, tip) in tips {
            if best_tips.contains(&tip) {
                continue;
            }
            if let Some(ch) = self.chain_from_tip_if_fully_effective(tip, include_unannounced) {
                return ch;
            }
        }

        vec![GENESIS_BLOCK_ID]
    }

    /// メインチェーン（告知済み・採掘完了ブロックのみ）。シミュレーション中のネットワーク上の最重鎖。
    pub fn get_main_chain(&self) -> Vec<BlockId> {
        self.compute_main_chain(false)
    }

    /// シミュレーション終了後の CSV 等用。採掘完了済みなら未告知（私有）も含めた最重鎖。
    pub fn get_main_chain_for_export(&self) -> Vec<BlockId> {
        self.compute_main_chain(true)
    }

    /// 採掘完了済みメインチェーンの先端ブロックの高さ（ジェネシスのみなら 0）
    pub fn main_chain_height(&self) -> i64 {
        self.get_main_chain()
            .last()
            .and_then(|&id| self.get_block(id))
            .map(|b| b.height())
            .unwrap_or(0)
    }

    /// 終了後レポート用のメインチェーン先端高さ（未告知ブロックを含む）
    pub fn main_chain_height_for_export(&self) -> i64 {
        self.get_main_chain_for_export()
            .last()
            .and_then(|&id| self.get_block(id))
            .map(|b| b.height())
            .unwrap_or(0)
    }

    /// ジェネシス以外で、実際にマイニング完了イベントが発火したブロックを「採掘済み」とみなし、
    /// メインチェーンに乗らないものを stale と数える（未発火のプレ生成ブロックは母集団に含めない）。
    ///
    /// `honest_minters` を渡したときは、同条件で honest / 非 honest 採掘分の指標も集計する。
    /// `min_height` / `max_height` でブロック高さの包含範囲を制限できる（ジェネシスは常に除外）。
    pub fn chain_metrics(
        &self,
        honest_minters: Option<&HashSet<NodeId>>,
        min_height: Option<i64>,
        max_height: Option<i64>,
    ) -> ChainMetrics {
        let main = self.get_main_chain();
        let main_set: HashSet<_> = main.iter().copied().collect();
        let mut mined_blocks: u64 = 0;
        let mut main_mined_blocks: u64 = 0;
        let mut honest_mined_blocks: u64 = 0;
        let mut honest_main_mined_blocks: u64 = 0;
        let mut attacker_mined_blocks: u64 = 0;
        let mut attacker_main_mined_blocks: u64 = 0;
        for block in self.blocks() {
            let height = block.height();
            if height == 0 {
                continue;
            }
            if min_height.is_some_and(|min_h| height < min_h) {
                continue;
            }
            if max_height.is_some_and(|max_h| height > max_h) {
                continue;
            }
            if !self.generation_completed.contains(&block.id()) {
                continue;
            }
            if !block.is_announced() {
                continue;
            }
            mined_blocks += 1;
            let on_main = main_set.contains(&block.id());
            if on_main {
                main_mined_blocks += 1;
            }
            if honest_minters.is_some_and(|set| set.contains(&block.minter())) {
                honest_mined_blocks += 1;
                if on_main {
                    honest_main_mined_blocks += 1;
                }
            } else if honest_minters.is_some() {
                attacker_mined_blocks += 1;
                if on_main {
                    attacker_main_mined_blocks += 1;
                }
            }
        }
        let stale_blocks = mined_blocks.saturating_sub(main_mined_blocks);
        let stale_rate = if mined_blocks > 0 {
            stale_blocks as f64 / mined_blocks as f64
        } else {
            0.0
        };
        let honest_stale_blocks = honest_mined_blocks.saturating_sub(honest_main_mined_blocks);
        let honest_stale_rate = if honest_mined_blocks > 0 {
            honest_stale_blocks as f64 / honest_mined_blocks as f64
        } else {
            0.0
        };
        let attacker_stale_blocks = attacker_mined_blocks.saturating_sub(attacker_main_mined_blocks);
        let attacker_stale_rate = if attacker_mined_blocks > 0 {
            attacker_stale_blocks as f64 / attacker_mined_blocks as f64
        } else {
            0.0
        };
        ChainMetrics {
            mined_blocks,
            main_mined_blocks,
            stale_blocks,
            stale_rate,
            honest_mined_blocks,
            honest_main_mined_blocks,
            honest_stale_blocks,
            honest_stale_rate,
            attacker_mined_blocks,
            attacker_main_mined_blocks,
            attacker_stale_blocks,
            attacker_stale_rate,
        }
    }
}

#[cfg(test)]
mod chain_metrics_tests {
    use super::*;
    use crate::{
        block::Block,
        node::NodeId,
        protocol::{GenesisDifficultyMode, ProtocolType},
    };

    fn test_protocol() -> Box<dyn Protocol> {
        ProtocolType::Bitcoin.to_protocol(GenesisDifficultyMode::Fixed)
    }

    fn push_block(
        chain: &mut Blockchain,
        id: usize,
        height: i64,
        prev: BlockId,
        minter: usize,
        announced: bool,
    ) -> BlockId {
        let protocol = test_protocol();
        let difficulty = protocol.default_difficulty(1);
        let parent_work = chain
            .get_block(prev)
            .map(|b| b.cumulative_chain_work())
            .unwrap_or(U256::zero());
        let cumulative = parent_work + difficulty.chain_work_increment();
        let block_id = BlockId::new(id);
        let block = Block::new(
            height,
            Some(prev),
            NodeId::new(minter),
            height * 1000,
            0,
            block_id,
            difficulty,
            cumulative,
            1.0,
            announced,
        );
        chain.add_block(block);
        block_id
    }

    #[test]
    fn honest_stale_rate_counts_only_honest_announced_completed_blocks() {
        let protocol = test_protocol();
        let mut chain = Blockchain::new(protocol.as_ref(), 3);
        let honest: HashSet<NodeId> = [1usize, 2].into_iter().map(NodeId::new).collect();

        // main: genesis -> h1(honest) -> h2(attacker) -> h3(honest)
        let b1 = push_block(&mut chain, 1, 1, GENESIS_BLOCK_ID, 1, true);
        let b2 = push_block(&mut chain, 2, 2, b1, 0, true);
        let _b3 = push_block(&mut chain, 3, 3, b2, 1, true);
        // stale honest fork at height 2（告知済み・採掘完了）
        let b4 = push_block(&mut chain, 4, 2, b1, 2, true);

        for id in [b1, b2, b4, BlockId::new(3)] {
            chain.mark_block_generation_completed(id);
        }

        let m = chain.chain_metrics(Some(&honest), None, None);
        assert_eq!(m.honest_mined_blocks, 3, "honest blocks: b1, b3, b4");
        assert_eq!(m.honest_main_mined_blocks, 2, "on main: b1, b3");
        assert_eq!(m.honest_stale_blocks, 1, "stale honest: b4");
        assert!(
            (m.honest_stale_rate - (1.0 / 3.0)).abs() < 1e-12,
            "honest_stale_rate = stale / mined"
        );
        assert_eq!(m.attacker_mined_blocks, 1, "attacker blocks: b2");
        assert_eq!(m.attacker_main_mined_blocks, 1, "on main: b2");
        assert_eq!(m.attacker_stale_blocks, 0);
        assert_eq!(m.attacker_stale_rate, 0.0);

        // 攻撃者ブロックは honest 母集団に入らない
        let m_all = chain.chain_metrics(None, None, None);
        assert_eq!(m_all.mined_blocks, 4);
        assert!(m.honest_mined_blocks < m_all.mined_blocks);
    }

    #[test]
    fn export_main_chain_includes_unannounced_heavier_branch() {
        let protocol = test_protocol();
        let mut chain = Blockchain::new(protocol.as_ref(), 3);

        // 公衆鎖: genesis -> h1 (告知済み)
        let b1 = push_block(&mut chain, 1, 1, GENESIS_BLOCK_ID, 1, true);
        // 私有の重い分岐: genesis -> h2 -> h3 (未告知・攻撃者)
        let b2 = push_block(&mut chain, 2, 2, GENESIS_BLOCK_ID, 0, false);
        let b3 = push_block(&mut chain, 3, 3, b2, 0, false);
        for id in [b1, b2, b3] {
            chain.mark_block_generation_completed(id);
        }

        let public = chain.get_main_chain();
        assert_eq!(public.len(), 2, "announced main: genesis + b1");
        assert_eq!(public.last(), Some(&b1));

        let export = chain.get_main_chain_for_export();
        assert_eq!(export, vec![GENESIS_BLOCK_ID, b2, b3]);
        assert_eq!(chain.main_chain_height_for_export(), 3);
    }

    #[test]
    fn honest_stale_rate_respects_height_bounds_and_announced_filter() {
        let protocol = test_protocol();
        let mut chain = Blockchain::new(protocol.as_ref(), 3);
        let honest: HashSet<NodeId> = HashSet::from([NodeId::new(1)]);

        let b1 = push_block(&mut chain, 1, 1, GENESIS_BLOCK_ID, 1, true);
        let b2 = push_block(&mut chain, 2, 2, b1, 1, false); // 未告知
        let b3 = push_block(&mut chain, 3, 5, b2, 1, true);
        for id in [b1, b2, b3] {
            chain.mark_block_generation_completed(id);
        }

        let m = chain.chain_metrics(Some(&honest), Some(2), Some(4));
        assert_eq!(m.honest_mined_blocks, 0, "height 2..4 に告知済み honest ブロックなし");
        assert_eq!(m.honest_stale_rate, 0.0);
    }
}
