use crate::{block::Block, simulator::Env};
use rand::rngs::StdRng;
use rand_distr::{Distribution, Exp};

use super::{Difficulty, Protocol};

/// Ethereumプロトコルの実装
///  TODO: implement total difficulty (mainchain choosing)
pub(super) struct EthereumProtocol;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EthereumDifficulty {
    value: f64,
}

impl EthereumDifficulty {
    const MIN: f64 = 1.0;

    pub fn new(value: f64) -> Self {
        assert!(value.is_finite(), "difficulty became non-finite ({value}).");
        let value = value.clamp(Self::MIN, Self::max());
        Self { value }
    }

    pub fn as_f64(self) -> f64 {
        self.value
    }

    pub fn max() -> f64 {
        // Eth1 difficulty is uint256, so max is 2^256-1.
        2f64.powi(256) - 1.0
    }

    pub fn target(self) -> f64 {
        // Yellow Paper: target = 2^256 / difficulty.
        // For difficulty=1, 2^256 overflows uint256, so cap at uint256::MAX.
        (2f64.powi(256) / self.value).min(Self::max())
    }

    pub fn calculate_mining_time(self, rng: &mut StdRng, hashrate: i64) -> i64 {
        let exp_dist: Exp<f64> = Exp::new(1.0).unwrap();
        let expected_hashes = self.value;
        let expected_generation_time = expected_hashes / hashrate as f64;
        (exp_dist.sample(rng) * expected_generation_time) as i64
    }
}

impl Protocol for EthereumProtocol {
    fn name(&self) -> &'static str {
        "Ethereum"
    }

    fn default_difficulty(&self) -> Difficulty {
        Difficulty::Ethereum(EthereumDifficulty::new(2f64.powi(32)))
    }

    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> Difficulty {
        if parent_block.height() <= 1 {
            return self.default_difficulty();
        }
        let grand_parent_block = env
            .blockchain
            .get_block(parent_block.prev_block_id().unwrap())
            .unwrap();

        let time_diff = (parent_block.time() - grand_parent_block.time()) / 1_000; // ms to s
        let adjustment_factor = (1 - (time_diff / 10)).max(-99);
        let parent_difficulty = parent_block.difficulty().as_f64();
        let difficulty_adjustment = (parent_difficulty / 2048.) as i64 * adjustment_factor;

        let uncle_adjustment = 0;

        let next_difficulty = (parent_difficulty as i64 + difficulty_adjustment + uncle_adjustment) as f64;

        /*
        if new_difficulty - parent_block.difficulty() as i64 > 1 {
            log::error!(
                "Difficulty adjustment error:
                height: {},
                parent_difficulty: 0x{:x},
                new_difficulty: 0x{:x},
                difficulty_adjustment: 0x{:x},
                uncle_adjustment: 0x{:x}",
                parent_block.height() + 1,
                parent_block.difficulty(),
                new_difficulty,
                difficulty_adjustment,
                uncle_adjustment,
            );
        }
        */
        Difficulty::Ethereum(EthereumDifficulty::new(next_difficulty))
    }
}
