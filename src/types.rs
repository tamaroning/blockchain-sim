use clap::ValueEnum;
use serde::Serialize;

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

    /// ブロック公開時刻を調整する
    /// `base_publish_time`: 通常のブロック公開時刻
    /// `from`: 送信元ノードID
    /// `to`: 送信先ノードID
    /// `current_time`: 現在の時刻（ブロック生成時刻）
    /// 返り値: 調整後のブロック公開時刻
    fn adjust_block_publish_time(
        &self,
        base_publish_time: i64,
        _from: usize,
        _to: usize,
        _current_time: i64,
    ) -> i64 {
        // デフォルト実装：何も調整しない
        base_publish_time
    }
}

/// 通常のマイニング戦略（何も調整しない）
pub struct HonestMiningStrategy;

impl MiningStrategy for HonestMiningStrategy {
    fn name(&self) -> &'static str {
        "Honest"
    }
}

/// Selfish mining戦略
pub struct SelfishMiningStrategy {
    /// 自分のブロックの伝播を遅らせる時間
    propagation_delay: i64,
}

impl SelfishMiningStrategy {
    pub fn new(propagation_delay: i64) -> Self {
        Self { propagation_delay }
    }
}

impl MiningStrategy for SelfishMiningStrategy {
    fn name(&self) -> &'static str {
        "Selfish"
    }

    fn adjust_propagation_time(
        &self,
        base_delay: i64,
        _from: usize,
        _to: usize,
        _current_time: i64,
    ) -> i64 {
        // 自分のブロックを他のノードに伝播する際は遅延を追加
        // この戦略を持つノードが`from`であることが保証されている
        base_delay + self.propagation_delay
    }
}

/// SimpleSubmissionPostpone戦略
/// ブロックの公開（伝播開始）を一定時間だけ遅らせる
pub struct SimpleSubmissionPostpone {
    /// 公開を遅らせる時間
    postpone_time: i64,
}

impl SimpleSubmissionPostpone {
    pub fn new(postpone_time: i64) -> Self {
        Self { postpone_time }
    }
}

impl MiningStrategy for SimpleSubmissionPostpone {
    fn name(&self) -> &'static str {
        "SimpleSubmissionPostpone"
    }

    fn adjust_block_publish_time(
        &self,
        base_publish_time: i64,
        _from: usize,
        _to: usize,
        _current_time: i64,
    ) -> i64 {
        // ブロック公開時刻に遅延を追加
        // この戦略を持つノードが`from`であることが保証されている
        base_publish_time + self.postpone_time
    }
}

