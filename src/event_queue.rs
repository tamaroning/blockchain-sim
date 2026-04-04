use std::collections::HashMap;

use priority_queue::PriorityQueue;

use crate::event::{Event, EventType};
use crate::node::NodeId;

/// Priority queue of simulation events plus a per-minter index of pending `BlockGeneration`s.
///
/// At most one pending mining event exists per minter; a new `RestartMining` removes the old
/// one via `PriorityQueue::remove` instead of scanning the whole queue.
pub struct EventQueue {
    inner: PriorityQueue<Event, i64>,
    pending_mining_by_minter: HashMap<NodeId, Event>,
}

impl EventQueue {
    pub fn new() -> Self {
        Self {
            inner: PriorityQueue::new(),
            pending_mining_by_minter: HashMap::new(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Non-mining events (e.g. propagation) that are not tied 1:1 to a minter slot.
    pub fn push(&mut self, event: Event) {
        let time = event.time();
        self.inner.push(event, -time);
    }

    /// Enqueue a `BlockGeneration`, replacing any existing pending mining event for the same minter.
    pub fn push_mining(&mut self, event: Event) {
        let minter = match event.event_type() {
            EventType::BlockGeneration { minter, .. } => *minter,
            EventType::Propagation { .. } => {
                self.push(event);
                return;
            }
        };
        if let Some(old) = self.pending_mining_by_minter.remove(&minter) {
            let _ = self.inner.remove(&old);
        }
        let time = event.time();
        self.pending_mining_by_minter.insert(minter, event.clone());
        self.inner.push(event, -time);
    }

    pub fn pop(&mut self) -> Option<Event> {
        let (event, _) = self.inner.pop()?;
        if let EventType::BlockGeneration { minter, .. } = event.event_type() {
            self.pending_mining_by_minter.remove(minter);
        }
        Some(event)
    }
}

impl Default for EventQueue {
    fn default() -> Self {
        Self::new()
    }
}
