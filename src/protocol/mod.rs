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

pub trait Protocol: Send + Sync {
    fn name(&self) -> &'static str;
    fn default_difficulty(&self) -> Difficulty;
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
    pub fn to_protocol(&self) -> Box<dyn Protocol> {
        match self {
            ProtocolType::Bitcoin => Box::new(BitcoinProtocol),
            ProtocolType::Ethereum => Box::new(EthereumProtocol),
        }
    }
}
