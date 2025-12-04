use serde::Serialize;

#[derive(Serialize)]
pub struct Record {
    pub round: u32,
    pub difficulty: f64,
    /// 実際のブロック生成時間
    pub mining_time: i64,
}

#[derive(Serialize)]
pub struct NodeInfo {
    pub node_id: usize,
    pub strategy: String,
    pub reward_share: f64,
    pub hashrate_share: f64,
    pub fairness: f64,
}