use crate::{block::Block, simulator::Env};
use clap::ValueEnum;

mod bitcoin;
mod ethereum;
mod difficulty;

use bitcoin::BitcoinProtocol;
pub use bitcoin::BitcoinDifficulty;
pub use difficulty::Difficulty;
pub use ethereum::EthereumDifficulty;
use ethereum::EthereumProtocol;

#[derive(ValueEnum, Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum GenesisDifficultyMode {
    /// ハッシュレートから逆算した推奨の難易度を使用する
    #[default]
    Inferred,
    /// 仕様に基づいて固定の難易度を使用する
    /// 例: Bitcoin の場合は 1.0, Ethereum の場合は 2^256
    Fixed,
}

pub trait Protocol: Send + Sync {
    fn name(&self) -> &'static str;
    fn default_difficulty(&self, total_hashrate: i64) -> Difficulty;
    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> Difficulty;
}

/// プロトコル列挙型（CLI用）
#[derive(ValueEnum, Debug, Clone, Default, PartialEq)]
pub enum ProtocolType {
    #[default]
    Bitcoin,
    Ethereum,
}

impl ProtocolType {
    pub fn to_protocol(&self, genesis_difficulty_mode: GenesisDifficultyMode) -> Box<dyn Protocol> {
        match self {
            ProtocolType::Bitcoin => Box::new(BitcoinProtocol::new(genesis_difficulty_mode)),
            ProtocolType::Ethereum => Box::new(EthereumProtocol::new(genesis_difficulty_mode)),
        }
    }
}
