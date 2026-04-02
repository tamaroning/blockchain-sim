use crate::{block::Block, simulator::Env};
use clap::ValueEnum;
use rand::rngs::StdRng;

mod bitcoin;
mod ethereum;

use bitcoin::BitcoinProtocol;
use ethereum::EthereumProtocol;

pub trait Protocol: Send + Sync {
    fn name(&self) -> &'static str;
    fn default_difficulty(&self) -> f64;
    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> f64;
    fn calculate_generation_time(&self, rng: &mut StdRng, difficulty: f64, hashrate: i64) -> i64;
}

fn check_difficulty(difficulty: f64) {
    if !difficulty.is_finite() {
        panic!("difficulty became non-finite ({}).", difficulty);
    }
    if difficulty == 0.0 {
        panic!("difficulty underflowed to 0.0 (likely f64 underflow).");
    }
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
