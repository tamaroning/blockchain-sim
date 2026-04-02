use crate::{block::Block, simulator::Env};
use rand::rngs::StdRng;
use rand_distr::{Distribution, Exp};

use super::{Difficulty, Protocol};

/// Bitcoin Protocol
/// expected generation time = expected required hash / hashrate
/// expected required hash = D * 2^32
pub(super) struct BitcoinProtocol;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BitcoinDifficulty {
    value: f64,
}

impl BitcoinDifficulty {
    const MIN: f64 = 1.0;
    const NBITS_DIFFICULTY_1: u32 = 0x1d00ffff;

    pub fn new(value: f64) -> Self {
        assert!(value.is_finite(), "difficulty became non-finite ({value}).");
        let value = value.clamp(Self::MIN, Self::max());
        Self { value }
    }

    pub fn as_f64(self) -> f64 {
        self.value
    }

    pub fn max() -> f64 {
        // difficulty_max = target_max / target_min(=1)
        Self::target_max()
    }

    pub fn target_max() -> f64 {
        let exponent = ((Self::NBITS_DIFFICULTY_1 >> 24) & 0xff) as i32;
        let mantissa = (Self::NBITS_DIFFICULTY_1 & 0x00ff_ffff) as f64;
        mantissa * 2f64.powi(8 * (exponent - 3))
    }

    pub fn calculate_mining_time(self, rng: &mut StdRng, hashrate: i64) -> i64 {
        let exp_dist: Exp<f64> = Exp::new(1.0).unwrap();
        let expected_hashes = self.value * 2f64.powi(32);
        let expected_generation_time = expected_hashes / hashrate as f64;
        (exp_dist.sample(rng) * expected_generation_time) as i64
    }
}

impl Protocol for BitcoinProtocol {
    fn name(&self) -> &'static str {
        "Bitcoin"
    }

    fn default_difficulty(&self) -> Difficulty {
        Difficulty::Bitcoin(BitcoinDifficulty::new(1.0))
    }

    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> Difficulty {
        const BTC_DAA_EPOCH: i64 = 2016;
        /// BTCの目標生成時間 (ms)
        const TWO_WEEKS_MS: i64 = 14 * 24 * 60 * 60 * 1000;

        let parent_block_id = parent_block.id();
        let parent_difficulty = parent_block.difficulty().as_f64();
        let parent_height = parent_block.height();

        let new_height = parent_height + 1;

        let next_difficulty = if new_height % BTC_DAA_EPOCH == 0 && new_height >= BTC_DAA_EPOCH {
            let first_block_in_epoch = {
                let mut block_id = parent_block_id;
                let mut block = env.blockchain.get_block(block_id).unwrap();
                for _ in 0..(BTC_DAA_EPOCH - 1) {
                    block_id = block.prev_block_id().unwrap();
                    block = env.blockchain.get_block(block_id).unwrap();
                }
                block
            };
            // Bitcoin-style retarget:
            //   actual_timespan = last_timestamp - first_timestamp
            //   actual_timespan is clamped to [expected/4, expected*4]
            //   new_difficulty = old_difficulty * expected / actual_timespan
            //
            // Note: we intentionally do NOT take abs(). If timestamps go backwards
            // (actual_timespan <= 0), clamping will pin it to the minimum timespan.
            let mut actual_timespan_ms = parent_block.time() - first_block_in_epoch.time();

            // TODO: remove this debug log
            let apparent_epoch_time_in_week: f64 =
                actual_timespan_ms as f64 / (7 * 24 * 60 * 60 * 1000) as f64;
            log::debug!("見かけでかかった時間: {:.2}週", apparent_epoch_time_in_week);

            // Bitcoinのretargetは常に timespan を [expected/4, expected*4] にclampする
            let min_timespan_ms = TWO_WEEKS_MS / 4;
            let max_timespan_ms = TWO_WEEKS_MS * 4;
            if actual_timespan_ms < min_timespan_ms {
                actual_timespan_ms = min_timespan_ms;
            } else if actual_timespan_ms > max_timespan_ms {
                actual_timespan_ms = max_timespan_ms;
            }

            parent_difficulty * (TWO_WEEKS_MS as f64) / (actual_timespan_ms as f64)
        } else {
            parent_difficulty
        };
        Difficulty::Bitcoin(BitcoinDifficulty::new(next_difficulty))
    }
}
