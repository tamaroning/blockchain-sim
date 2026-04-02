use crate::{block::Block, simulator::Env};
use rand::rngs::StdRng;
use rand_distr::{Distribution, Exp};

use super::{Protocol, check_difficulty};

/// Ethereumプロトコルの実装
///  TODO: implement total difficulty (mainchain choosing)
pub(super) struct EthereumProtocol;

impl Protocol for EthereumProtocol {
    fn name(&self) -> &'static str {
        "Ethereum"
    }

    fn default_difficulty(&self) -> f64 {
        2f64.powi(32)
    }

    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> f64 {
        if parent_block.height() <= 1 {
            return self.default_difficulty();
        }
        let grand_parent_block = env
            .blockchain
            .get_block(parent_block.prev_block_id().unwrap())
            .unwrap();

        let time_diff = (parent_block.time() - grand_parent_block.time()) / 1_000; // ms to s
        let adjustment_factor = (1 - (time_diff / 10)).max(-99);
        let difficulty_adjustment = (parent_block.difficulty() / 2048.) as i64 * adjustment_factor;

        let uncle_adjustment = 0;

        let new_difficulty =
            parent_block.difficulty() as i64 + difficulty_adjustment + uncle_adjustment;
        let new_difficulty = new_difficulty as f64;

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
        check_difficulty(new_difficulty);
        new_difficulty
    }

    fn calculate_generation_time(&self, rng: &mut StdRng, difficulty: f64, hashrate: i64) -> i64 {
        let exp_dist: Exp<f64> = Exp::new(1.0).unwrap();
        let expected_hash = difficulty;
        let exptected_generation_time = expected_hash as f64 / hashrate as f64;
        (exp_dist.sample(rng) * exptected_generation_time) as i64
    }
}
