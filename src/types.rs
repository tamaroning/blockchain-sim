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
