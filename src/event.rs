use std::cmp::Ordering;

use crate::{blockchain::BlockId, node::NodeId};

#[derive(Clone, Debug, Hash)]
pub struct Event {
    time: i64,
    ty: EventType,
}

impl Event {
    pub fn new(time: i64, ty: EventType) -> Self {
        Self { time, ty }
    }

    pub fn time(&self) -> i64 {
        self.time
    }

    pub fn event_type(&self) -> &EventType {
        &self.ty
    }

    pub fn is_block_generation(&self) -> bool {
        matches!(self.ty, EventType::BlockGeneration { .. })
    }

    pub fn is_propagation(&self) -> bool {
        matches!(self.ty, EventType::Propagation { .. })
    }
}

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub enum EventType {
    BlockGeneration {
        minter: NodeId,
        prev_block_id: BlockId,
        block_id: BlockId,
    },
    Propagation {
        from: NodeId,
        to: NodeId,
        block_id: BlockId,
    },
}

impl Eq for Event {}

impl PartialEq for Event {
    fn eq(&self, other: &Self) -> bool {
        self.time == other.time
    }
}

impl Ord for Event {
    fn cmp(&self, other: &Self) -> Ordering {
        other.time.cmp(&self.time) // 逆順（最小ヒープにするため）
    }
}

impl PartialOrd for Event {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
