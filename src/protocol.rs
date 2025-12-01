use crate::{block::Block, simulator::Env};
use clap::ValueEnum;

const BTC_DAA_EPOCH: i64 = 2016;

/// プロトコルのトレイト定義
pub trait Protocol: Send + Sync {
    fn name(&self) -> &'static str;
    fn calculate_difficulty(&self, parent_block: &Block, current_time: i64, env: &Env) -> f64;
}

/// Bitcoinプロトコルの実装
pub struct BitcoinProtocol;

impl Protocol for BitcoinProtocol {
    fn name(&self) -> &'static str {
        "Bitcoin"
    }

    fn calculate_difficulty(&self, parent_block: &Block, current_time: i64, env: &Env) -> f64 {
        let parent_block_id = parent_block.id();
        let parent_difficulty = parent_block.difficulty();
        let parent_height = parent_block.height();

        let new_height = parent_height + 1;

        if new_height % BTC_DAA_EPOCH == 0 && new_height >= BTC_DAA_EPOCH {
            let (first_block_in_epoch, height) = {
                let mut block_id = parent_block_id;
                let block = env.blockchain.get_block(block_id).unwrap();
                for _ in 0..BTC_DAA_EPOCH {
                    if let Some(prev_id) = block.prev_block_id() {
                        block_id = prev_id;
                    } else {
                        break;
                    }
                }
                (block_id, block.height())
            };
            let first_block_in_epoch = env.blockchain.get_block(first_block_in_epoch).unwrap();
            let average_generation_time = (current_time - first_block_in_epoch.time()) as f64
                / (parent_height - height) as f64;
            let ratio = average_generation_time / env.generation_time as f64;
            if ratio < 0.5 {
                parent_difficulty * 0.25
            } else if ratio > 2.0 {
                parent_difficulty * 4.
            } else {
                parent_difficulty / ratio
            }
        } else {
            parent_difficulty
        }
    }
}

/// Ethereumプロトコルの実装
pub struct EthereumProtocol;

impl Protocol for EthereumProtocol {
    fn name(&self) -> &'static str {
        "Ethereum"
    }

    fn calculate_difficulty(&self, parent_block: &Block, _current_time: i64, env: &Env) -> f64 {
        if parent_block.height() == 0 {
            return 1.0;
        }
        let grand_parent_block_id = parent_block.prev_block_id().unwrap();
        let grand_parent_block = env.blockchain.get_block(grand_parent_block_id).unwrap();

        let time_diff = (parent_block.time() - grand_parent_block.time()) / 1_000_000; // us to s
        let adjustment_factor = (1 - (time_diff / 10)).max(-99);
        let difficulty_adjustment = parent_block.difficulty() / 2048. * adjustment_factor as f64;

        let uncle_adjustment = 0.;

        let new_difficulty = parent_block.difficulty() + difficulty_adjustment + uncle_adjustment;
        if new_difficulty - parent_block.difficulty() > 1. {
            log::error!(
                "Difficulty adjustment error:
                height: {},
                parent_difficulty: {:.2},
                new_difficulty: {:.2},
                difficulty_adjustment: {:.2},
                uncle_adjustment: {:.2}",
                parent_block.height() + 1,
                parent_block.difficulty(),
                new_difficulty,
                difficulty_adjustment,
                uncle_adjustment,
            );
        }
        new_difficulty
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
