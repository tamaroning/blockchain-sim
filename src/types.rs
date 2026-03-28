use serde::Serialize;

use crate::node::NodeId;

#[derive(Serialize)]
pub struct Record {
    pub round: u32,
    pub timestamp: i64,
    pub difficulty: f64,
    /// 実際のブロック生成時間
    pub mining_time: i64,
    pub minter: NodeId,
}

#[derive(Serialize)]
pub struct NodeInfo {
    pub node_id: usize,
    pub strategy: String,
    pub reward_share: f64,
    pub hashrate_share: f64,
    pub fairness: f64,
}
