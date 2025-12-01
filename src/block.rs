use crate::{Protocol, blockchain::BlockId};

pub const GENESIS_BLOCK_ID: BlockId = BlockId::new(0);

/// ブロックを表す構造体
#[derive(Clone, Debug)]
pub struct Block {
    height: i64,
    prev_block_id: Option<BlockId>,
    minter: i32,
    time: i64,
    rand: i64,
    id: BlockId,
    /// Difficulty
    difficulty: f64,
    /// マイニングにかかった時間
    pub mining_time: i64,
}

impl Block {
    pub fn new(
        height: i64,
        prev_block_id: Option<BlockId>,
        minter: i32,
        time: i64,
        rand: i64,
        id: BlockId,
        difficulty: f64,
        mining_time: i64,
    ) -> Self {
        Self {
            height,
            prev_block_id,
            minter,
            time,
            rand,
            id,
            difficulty,
            mining_time,
        }
    }

    pub fn genesis(protocol: &dyn Protocol) -> Self {
        Self {
            height: 0,
            prev_block_id: None,
            minter: -1,
            time: 0,
            rand: 0,
            id: GENESIS_BLOCK_ID,
            difficulty: protocol.default_difficulty(),
            mining_time: 0,
        }
    }

    pub fn height(&self) -> i64 {
        self.height
    }

    pub fn id(&self) -> BlockId {
        self.id
    }

    pub fn difficulty(&self) -> f64 {
        self.difficulty
    }

    pub fn minter(&self) -> i32 {
        self.minter
    }

    pub fn time(&self) -> i64 {
        self.time
    }

    pub fn prev_block_id(&self) -> Option<BlockId> {
        self.prev_block_id
    }

    pub fn rand(&self) -> i64 {
        self.rand
    }
}
