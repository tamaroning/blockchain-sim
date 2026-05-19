use serde::Serialize;

use crate::node::NodeId;

#[derive(Serialize)]
pub struct Record {
    pub round: u32,
    pub timestamp: i64,
    pub difficulty: f64,
    /// 実際のブロック生成時間（ミリ秒、内部は μs から換算）
    pub mining_time: f64,
    pub minter: NodeId,
}

#[derive(Debug, Serialize, Clone)]
pub struct ChainMetrics {
    pub mined_blocks: u64,
    pub main_mined_blocks: u64,
    pub stale_blocks: u64,
    pub stale_rate: f64,
    /// honest ノードが採掘したブロックのみを母集団とした stale 指標
    pub honest_mined_blocks: u64,
    pub honest_main_mined_blocks: u64,
    pub honest_stale_blocks: u64,
    pub honest_stale_rate: f64,
}

#[derive(Serialize)]
pub struct NodeInfo {
    pub node_id: usize,
    pub strategy: String,
    pub reward_share: f64,
    pub hashrate_share: f64,
    pub fairness: f64,
}
