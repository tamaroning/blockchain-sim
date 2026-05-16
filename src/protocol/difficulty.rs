use primitive_types::U256;
use rand::rngs::StdRng;

use super::{BitcoinDifficulty, EthereumDifficulty};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Difficulty {
    Bitcoin(BitcoinDifficulty),
    Ethereum(EthereumDifficulty),
}

impl Difficulty {
    /// 次の採掘イベントまでの待ち時間（**マイクロ秒**）。指数分布サンプル、最低 1μs。
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

    /// フォーク選択用の整数 chainwork 増分（累積は `U256` で保持）。
    pub fn chain_work_increment(self) -> U256 {
        match self {
            Difficulty::Bitcoin(d) => d.chain_work_increment(),
            Difficulty::Ethereum(d) => d.chain_work_increment(),
        }
    }
}
