use primitive_types::U256;

use crate::{Protocol, blockchain::BlockId, node::NodeId, protocol::Difficulty};

pub const GENESIS_BLOCK_ID: BlockId = BlockId::new(0);

/// ブロックを表す構造体
#[derive(Clone, Debug)]
pub struct Block {
    height: i64,
    prev_block_id: Option<BlockId>,
    minter: NodeId,
    /// timestamp（プロトコル上の壁時計、**ミリ秒**）
    time: i64,
    /// Random number for block selection
    rand: i64,
    id: BlockId,
    /// Difficulty
    difficulty: Difficulty,
    /// ジェネシスからこのブロックまでの累積 chainwork（整数）
    cumulative_chain_work: U256,
    /// マイニングにかかった時間（**ミリ秒**、CSV 用に実時間に近い分解能）
    pub mining_time: f64,
    /// 少なくとも一度でもネットワーク上へ伝搬がスケジュールされたか（主鎖・指標用）
    announced: bool,
}

impl Block {
    pub fn new(
        height: i64,
        prev_block_id: Option<BlockId>,
        minter: NodeId,
        time: i64,
        rand: i64,
        id: BlockId,
        difficulty: Difficulty,
        cumulative_chain_work: U256,
        mining_time_ms: f64,
        announced: bool,
    ) -> Self {
        Self {
            height,
            prev_block_id,
            minter,
            time,
            rand,
            id,
            difficulty,
            cumulative_chain_work,
            mining_time: mining_time_ms,
            announced,
        }
    }

    pub fn genesis(protocol: &dyn Protocol, total_hashrate: i64) -> Self {
        let difficulty = protocol.default_difficulty(total_hashrate);
        Self {
            height: 0,
            prev_block_id: None,
            minter: NodeId::dummy(),
            time: 0,
            rand: 0,
            id: GENESIS_BLOCK_ID,
            difficulty,
            cumulative_chain_work: difficulty.chain_work_increment(),
            mining_time: 0.0,
            announced: true,
        }
    }

    pub fn height(&self) -> i64 {
        self.height
    }

    pub fn id(&self) -> BlockId {
        self.id
    }

    pub fn difficulty(&self) -> Difficulty {
        self.difficulty
    }

    pub fn minter(&self) -> NodeId {
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

    pub fn cumulative_chain_work(&self) -> U256 {
        self.cumulative_chain_work
    }

    pub fn is_announced(&self) -> bool {
        self.announced
    }

    pub fn set_announced(&mut self, announced: bool) {
        self.announced = announced;
    }
}
