use rand::rngs::StdRng;

use super::{BitcoinDifficulty, EthereumDifficulty};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Difficulty {
    Bitcoin(BitcoinDifficulty),
    Ethereum(EthereumDifficulty),
}

impl Difficulty {
    pub fn calculate_mining_time(self, rng: &mut StdRng, hashrate: i64) -> i64 {
        match self {
            Difficulty::Bitcoin(d) => d.calculate_mining_time(rng, hashrate),
            Difficulty::Ethereum(d) => d.calculate_mining_time(rng, hashrate),
        }
    }

    /// Conversion intended for output boundaries (CSV/logs, etc.).
    /// Keep protocol calculation logic typed as `Difficulty`.
    pub fn as_f64(self) -> f64 {
        match self {
            Difficulty::Bitcoin(d) => d.as_f64(),
            Difficulty::Ethereum(d) => d.as_f64(),
        }
    }
}
