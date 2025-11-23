use clap::ValueEnum;
use serde::{Deserialize, Serialize};

#[derive(ValueEnum, Debug, Clone, Default, PartialEq)]
#[clap(rename_all = "kebab_case")]
pub enum TieBreakingRule {
    #[default]
    Longest,
    Random,
    Time,
}

#[derive(Serialize)]
pub struct Record {
    pub round: u32,
    pub difficulty: f64,
    /// 実際のブロック生成時間
    pub mining_time: i64,
}

/// マイニング戦略のトレイト
pub trait MiningStrategy: Send + Sync {
    /// 戦略の名前を取得する
    fn name(&self) -> &'static str;

    /// 伝播時間を調整する
    /// `base_delay`: 通常の伝播遅延時間
    /// `from`: 送信元ノードID
    /// `to`: 送信先ノードID
    /// `current_time`: 現在の時刻
    /// 返り値: 調整後の伝播時間
    fn adjust_propagation_time(
        &self,
        base_delay: i64,
        _from: usize,
        _to: usize,
        _current_time: i64,
    ) -> i64 {
        // デフォルト実装：何も調整しない
        base_delay
    }

    /// ブロックを公開すべきかどうかを判断する
    /// `private_chain_height`: プライベートチェーンの高さ
    /// `public_chain_height`: 公開チェーンの高さ
    /// 返り値: 公開すべきかどうか
    fn should_publish_block(&self, _private_chain_height: i64, _public_chain_height: i64) -> bool {
        // デフォルト実装：常に公開する
        true
    }
}

/// 通常のマイニング戦略（何も調整しない）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HonestMiningStrategy;

impl MiningStrategy for HonestMiningStrategy {
    fn name(&self) -> &'static str {
        "Honest"
    }
}

/// k-lead selfish mining戦略
/// プライベートチェーンが公開チェーンよりkブロック先に進むまでブロックを公開しない
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KLeadSelfishMiningStrategy {
    /// リードを取る必要があるブロック数
    #[serde(default = "default_k")]
    pub k: i64,
}

fn default_k() -> i64 {
    1
}

impl KLeadSelfishMiningStrategy {
    pub fn new(k: i64) -> Self {
        Self { k }
    }
}

impl MiningStrategy for KLeadSelfishMiningStrategy {
    fn name(&self) -> &'static str {
        "KLeadSelfishMining"
    }

    fn should_publish_block(&self, private_chain_height: i64, public_chain_height: i64) -> bool {
        // プライベートチェーンの高さが公開チェーンよりkブロック以上大きい場合のみ公開
        private_chain_height >= public_chain_height + self.k
    }
}

/// マイニング戦略をenumで表現（シリアライズ/デシリアライズ可能）
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum MiningStrategyEnum {
    Honest,
    KLeadSelfishMining { k: i64 },
}

impl MiningStrategyEnum {
    /// enumからMiningStrategyトレイトオブジェクトを作成
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy),
            MiningStrategyEnum::KLeadSelfishMining { k } => {
                Box::new(KLeadSelfishMiningStrategy::new(*k))
            }
        }
    }
}
