use crate::{block::Block, simulator::Env};
use clap::ValueEnum;
use rand::rngs::StdRng;
use rand_distr::Distribution;
use rand_distr::Exp;

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

/// Bitcoin Protocol
/// expected generation time = expected required hash / hashrate
/// expected required hash = D * 2^32
pub struct BitcoinProtocol;

impl Protocol for BitcoinProtocol {
    fn name(&self) -> &'static str {
        "Bitcoin"
    }

    fn default_difficulty(&self) -> f64 {
        // FIXME: 適切な値を考える
        // とりあえず、hashrate合計が100のときに、1epochが2週間くらいになるように設定しておく
        let total_hashrate = 100.;
        total_hashrate * 600_000. / (1u64 << 32) as f64
    }

    fn calculate_difficulty(&self, parent_block: &Block, env: &Env) -> f64 {
        const BTC_DAA_EPOCH: i64 = 2016;
        /// BTCの目標生成時間 (ms)
        const BTC_TARGET_GENERATION_TIME: i64 = 600_000;

        let parent_block_id = parent_block.id();
        let parent_difficulty = parent_block.difficulty();
        let parent_height = parent_block.height();

        let new_height = parent_height + 1;

        let new_difficulty = if new_height % BTC_DAA_EPOCH == 0 && new_height >= BTC_DAA_EPOCH {
            let first_block_in_epoch = {
                let mut block_id = parent_block_id;
                let mut block = env.blockchain.get_block(block_id).unwrap();
                for _ in 0..(BTC_DAA_EPOCH - 1) {
                    block_id = block.prev_block_id().unwrap();
                    block = env.blockchain.get_block(block_id).unwrap();
                }
                block
            };
            // TODO: remove this
            // 見かけでかかった時間
            let apparent_epoch_time = parent_block.time() - first_block_in_epoch.time();
            // in week
            let apparent_epoch_time_in_week: f64 =
                apparent_epoch_time as f64 / (7 * 24 * 60 * 60 * 1000) as f64;
            log::debug!("見かけでかかった時間: {:.2}週", apparent_epoch_time_in_week);

            // 実際は2015ブロック分で計算する
            // 2016ブロックの難易度調整は, 0~2015ブロックのブロック間の平均生成時間で行う(2015区間)
            let average_generation_time = (parent_block.time() - first_block_in_epoch.time())
                as f64
                / (BTC_DAA_EPOCH - 1) as f64;
            let ratio = average_generation_time / BTC_TARGET_GENERATION_TIME as f64;
            let ratio = ratio.max(0.25).min(4.0);

            let new_difficulty = parent_difficulty / ratio;
            new_difficulty
        } else {
            parent_difficulty
        };
        check_difficulty(new_difficulty);
        new_difficulty
    }

    fn calculate_generation_time(&self, rng: &mut StdRng, difficulty: f64, hashrate: i64) -> i64 {
        let exp_dist: Exp<f64> = Exp::new(1.0).unwrap();
        let expected_hash = difficulty * 2f64.powi(32);
        let exptected_generation_time = expected_hash as f64 / hashrate as f64;
        (exp_dist.sample(rng) * exptected_generation_time) as i64
    }
}

/// Ethereumプロトコルの実装
///  TODO: implement total difficulty (mainchain choosing)
pub struct EthereumProtocol;

impl Protocol for EthereumProtocol {
    fn name(&self) -> &'static str {
        "Ethereum"
    }

    fn default_difficulty(&self) -> f64 {
        2f64.powi(32)
    }

    fn calculate_difficulty(&self, parent_block: &Block, _env: &Env) -> f64 {
        if parent_block.height() <= 1 {
            return self.default_difficulty();
        }
        let grand_parent_block = _env
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
