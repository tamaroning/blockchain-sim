use crate::{block::Block, simulator::Env};
use primitive_types::U256;
use rand::rngs::StdRng;
use rand_distr::{Distribution, Exp};

use super::{Difficulty, GenesisDifficultyMode, Protocol};

/// Ethereumプロトコルの実装
///  TODO: implement total difficulty (mainchain choosing)
pub(super) struct EthereumProtocol {
    genesis_difficulty_mode: GenesisDifficultyMode,
}

impl EthereumProtocol {
    pub fn new(genesis_difficulty_mode: GenesisDifficultyMode) -> Self {
        Self {
            genesis_difficulty_mode,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EthereumDifficulty {
    value: U256,
}

impl EthereumDifficulty {
    const MIN: U256 = U256([1, 0, 0, 0]);

    pub fn new(value: U256) -> Self {
        let value = value.clamp(Self::MIN, Self::max());
        Self { value }
    }

    pub fn from_u64(value: u64) -> Self {
        Self::new(U256::from(value))
    }

    pub fn as_u256(self) -> U256 {
        self.value
    }

    pub fn as_f64(self) -> f64 {
        u256_to_f64_lossy(self.value)
    }

    pub fn max() -> U256 {
        // Eth1 difficulty is uint256, so max is 2^256-1.
        U256::MAX
    }

    pub fn target(self) -> f64 {
        // Yellow Paper: target = 2^256 / difficulty.
        // Kept as f64 for output/inspection only.
        let d = self.as_f64();
        let max_target = u256_to_f64_lossy(U256::MAX);
        if d <= 1.0 {
            max_target
        } else {
            (2f64.powi(256) / d).min(max_target)
        }
    }

    pub fn work(self) -> f64 {
        // PoW chainwork increment: floor(2^256 / (target + 1)).
        // Ethereum's total-difficulty based fork-choice is effectively this sum.
        2f64.powi(256) / (self.target() + 1.0)
    }

    pub fn calculate_mining_time(self, rng: &mut StdRng, hashrate: i64) -> i64 {
        let exp_dist: Exp<f64> = Exp::new(1.0).unwrap();
        // Mining time model uses a floating approximation at the boundary.
        let expected_hashes = self.as_f64();
        let expected_generation_time = expected_hashes / hashrate as f64;
        (exp_dist.sample(rng) * expected_generation_time) as i64
    }
}

impl Protocol for EthereumProtocol {
    fn name(&self) -> &'static str {
        "Ethereum"
    }

    fn default_difficulty(&self, total_hashrate: i64) -> Difficulty {
        match self.genesis_difficulty_mode {
            GenesisDifficultyMode::Inferred => {
                // Expected time = difficulty / hashrate in this simulator's Eth model.
                // Solve for difficulty so that the network target is 12 seconds per block.
                const TARGET_BLOCK_TIME_MS: i64 = 12_000;
                let safe_hashrate = total_hashrate.max(1);
                let difficulty =
                    U256::from(safe_hashrate as u64) * U256::from(TARGET_BLOCK_TIME_MS as u64);
                Difficulty::Ethereum(EthereumDifficulty::new(difficulty))
            }
            GenesisDifficultyMode::Fixed => {
                Difficulty::Ethereum(EthereumDifficulty::new(U256::from(1u64) << 32))
            }
        }
    }

    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> Difficulty {
        if parent_block.height() <= 1 {
            return self.default_difficulty(env.total_hashrate);
        }
        let grand_parent_block = env
            .blockchain
            .get_block(parent_block.prev_block_id().unwrap())
            .unwrap();

        let time_diff = (parent_block.time() - grand_parent_block.time()) / 1_000; // ms to s
        let adjustment_factor = (1 - (time_diff / 10)).max(-99);
        let parent_difficulty = match parent_block.difficulty() {
            Difficulty::Ethereum(d) => d.as_u256(),
            Difficulty::Bitcoin(_) => unreachable!("difficulty/protocol mismatch"),
        };
        let difficulty_adjustment = (parent_difficulty / U256::from(2048u64))
            * U256::from(adjustment_factor.unsigned_abs());

        let uncle_adjustment = 0;

        let mut next_difficulty = if adjustment_factor >= 0 {
            parent_difficulty.saturating_add(difficulty_adjustment)
        } else {
            parent_difficulty.saturating_sub(difficulty_adjustment)
        };
        if uncle_adjustment > 0 {
            next_difficulty = next_difficulty.saturating_add(U256::from(uncle_adjustment as u64));
        } else if uncle_adjustment < 0 {
            next_difficulty =
                next_difficulty.saturating_sub(U256::from((-uncle_adjustment) as u64));
        }

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

fn u256_to_f64_lossy(value: U256) -> f64 {
    if value.is_zero() {
        return 0.0;
    }
    let bits = value.bits();
    if bits <= 53 {
        return value.low_u64() as f64;
    }

    let shift = bits - 53;
    let mantissa = (value >> shift).low_u64() as f64;
    mantissa * 2f64.powi(shift as i32)
}
