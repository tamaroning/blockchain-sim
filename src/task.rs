use std::cmp::Ordering;

#[derive(Clone, Debug, Hash)]
pub struct Task {
    time: i64,
    ty: TaskType,
}

impl Task {
    pub fn new(time: i64, ty: TaskType) -> Self {
        Self { time, ty }
    }

    pub fn time(&self) -> i64 {
        self.time
    }

    pub fn task_type(&self) -> &TaskType {
        &self.ty
    }

    pub fn is_block_generation(&self) -> bool {
        matches!(self.ty, TaskType::BlockGeneration { .. })
    }

    pub fn is_propagation(&self) -> bool {
        matches!(self.ty, TaskType::Propagation { .. })
    }
}

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub enum TaskType {
    BlockGeneration {
        minter: usize,
    },
    Propagation {
        from: usize,
        to: usize,
        block_id: usize,
    },
}

impl Eq for Task {}

impl PartialEq for Task {
    fn eq(&self, other: &Self) -> bool {
        self.time == other.time
    }
}

impl Ord for Task {
    fn cmp(&self, other: &Self) -> Ordering {
        other.time.cmp(&self.time) // 逆順（最小ヒープにするため）
    }
}

impl PartialOrd for Task {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

