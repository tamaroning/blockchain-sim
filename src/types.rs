use serde::Serialize;

#[derive(Serialize)]
pub struct Record {
    pub round: u32,
    pub difficulty: f64,
    /// 実際のブロック生成時間
    pub mining_time: i64,
}
