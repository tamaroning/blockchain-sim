use crate::block::Block;
use crate::blockchain::Blockchain;
use crate::node::Node;
use crate::protocol::Protocol;
use crate::task::{Task, TaskType};
use crate::types::TieBreakingRule;
use priority_queue::PriorityQueue;
use rand::prelude::*;
use rand_distr::Exp;
use std::collections::HashSet;

pub struct BlockchainSimulator {
    current_round: i64,
    current_time: i64,
    delay: i64,
    generation_time: i64,
    tie: TieBreakingRule,
    nodes: Vec<Node>,
    total_hashrate: i64,
    end_round: i64,
    blockchain: Blockchain,
    rng: StdRng,
    protocol: Box<dyn Protocol>,
    /// CSV出力用のライター
    csv: Option<csv::Writer<std::fs::File>>,
    csv_written_block_heights: HashSet<i64>,

    /// タスクキュー
    task_queue: PriorityQueue<Task, i64>,
}

impl BlockchainSimulator {
    pub fn new(
        num_nodes: usize,
        seed: u64,
        end_round: i64,
        tie: TieBreakingRule,
        delay: i64,
        generation_time: i64,
        protocol: Box<dyn Protocol>,
        csv: Option<csv::Writer<std::fs::File>>,
    ) -> Self {
        let mut rng = StdRng::seed_from_u64(seed);
        let exp_dist = Exp::new(1.0).unwrap();
        let mut nodes = Vec::with_capacity(num_nodes);

        // 指数分布でハッシュレートを生成し、ノードを作成
        for i in 0..num_nodes {
            let hashrate = (exp_dist.sample(&mut rng) * 10000.0) as i64 + 1; // 最低1は保証
            nodes.push(Node::new(i, hashrate));
        }
        log::info!(
            "Hashrates: {:?}",
            nodes.iter().map(|n| n.hashrate()).collect::<Vec<_>>()
        );

        let total_hashrate = nodes.iter().map(|n| n.hashrate()).sum();

        let task_queue = PriorityQueue::<Task, i64>::new();

        Self {
            current_round: 0,
            current_time: 0,
            delay,
            generation_time,
            tie,
            nodes,
            total_hashrate,
            end_round,
            blockchain: Blockchain::new(),
            rng,
            protocol,
            csv,
            csv_written_block_heights: HashSet::with_capacity(end_round as usize * 4),
            task_queue,
        }
    }

    fn enqueue_task(&mut self, task: Task) {
        let time = task.time();
        // PriorityQueueは最大キューなので符号反転する
        self.task_queue.push(task, -time);
    }

    fn pop_task(&mut self) -> Option<Task> {
        self.task_queue.pop().map(|(task, _)| task)
    }

    fn propagation_time(&self, from: usize, to: usize) -> i64 {
        if from == to { 0 } else { self.delay }
    }

    fn choose_mainchain(&mut self, block1_id: usize, block2_id: usize, _from: usize, to: usize) {
        let block1 = self.blockchain.get_block(block1_id).unwrap();
        let block2 = self.blockchain.get_block(block2_id).unwrap();

        if block1.height() > block2.height() {
            self.nodes[to].set_current_block_id(block1_id);
            return;
        }

        if block1.height() == block2.height() {
            if self.tie == TieBreakingRule::Random
                && block2.minter() != to as i32
                && block1.rand() < block2.rand()
            {
                self.nodes[to].set_current_block_id(block1_id);
            }

            if self.tie == TieBreakingRule::Time
                && block2.minter() != to as i32
                && block1.time() > block2.time()
            {
                self.nodes[to].set_current_block_id(block1_id);
            }
        }
    }

    /// シミュレーションを実行
    pub fn simulation(&mut self) {
        // 初期マイニングタスクをスケジュール
        for i in 0..self.nodes.len() {
            let node = &self.nodes[i];
            let exp_dist = Exp::new(1.0).unwrap();
            // TODO: 難易度調整
            let time = (exp_dist.sample(&mut self.rng)
                * self.generation_time as f64
                * self.total_hashrate as f64
                / node.hashrate() as f64) as i64;

            let task = Task::new(time, TaskType::BlockGeneration { minter: i });

            self.nodes[i].set_next_mining_time(Some(time));
            self.enqueue_task(task);
        }

        while !self.task_queue.is_empty() && self.current_round < self.end_round {
            let current_task = self.pop_task().expect("Task queue should not be empty");
            self.current_time = current_task.time();

            match current_task.task_type() {
                TaskType::BlockGeneration { minter } => {
                    // 現在のマイニングタスクかチェック
                    if let Some(task_time) = self.nodes[*minter].next_mining_time() {
                        if task_time != current_task.time() {
                            continue;
                        }
                    } else {
                        continue;
                    }

                    let current_block_id = self.nodes[*minter].current_block_id();
                    let current_block = self.blockchain.get_block(current_block_id).unwrap();

                    // 次のマイニングタスクをスケジュール
                    let Some(next_time) = self.nodes[*minter].next_mining_time() else {
                        unreachable!("next_mining_time should be set for all nodes");
                    };
                    self.schedule_next_mining_task(*minter, next_time, current_block.difficulty());
                    let mining_time =
                        self.nodes[*minter].next_mining_time().unwrap() - self.current_time;

                    let current_block_id = self.nodes[*minter].current_block_id();
                    let current_block = self.blockchain.get_block(current_block_id).unwrap();

                    // 難易度調整
                    let new_difficulty = self.calculate_new_difficulty(current_block);

                    if let Some(csv) = &mut self.csv {
                        if !self
                            .csv_written_block_heights
                            .contains(&current_block.height())
                        {
                            self.csv_written_block_heights
                                .insert(current_block.height());
                            csv.serialize(&crate::types::Record {
                                round: current_block.height() as u32,
                                difficulty: new_difficulty,
                                mining_time: current_block.mining_time,
                            })
                            .expect("Failed to write CSV record");
                        }
                    }

                    let new_block = Block::new(
                        current_block.height() + 1,
                        Some(current_block_id),
                        *minter as i32,
                        self.current_time,
                        (self.rng.r#gen::<f64>() * (i64::MAX - 10) as f64) as i64,
                        self.blockchain.next_block_id(),
                        new_difficulty,
                        mining_time,
                    );

                    let new_block_id = self.blockchain.add_block(new_block.clone());
                    self.nodes[*minter].set_current_block_id(new_block_id);
                    if self.current_round < new_block.height() {
                        self.current_round = new_block.height();
                    }

                    // 伝播タスクをスケジュール
                    for i in 0..self.nodes.len() {
                        if i != *minter {
                            let prop_task = Task::new(
                                next_time + self.propagation_time(*minter, i),
                                TaskType::Propagation {
                                    from: *minter,
                                    to: i,
                                    block_id: self.nodes[*minter].current_block_id(),
                                },
                            );
                            self.enqueue_task(prop_task);
                        }
                    }

                    log::debug!(
                        "📦 time: {}, minter: {}, difficulty: {}, height: {}",
                        self.current_time,
                        new_block.minter(),
                        new_block.difficulty(),
                        new_block.height()
                    );
                }

                TaskType::Propagation { from, to, block_id } => {
                    log::debug!(
                        "🚚 time: {}, {}->{}, height: {}",
                        self.current_time,
                        from,
                        to,
                        self.blockchain.get_block(*block_id).unwrap().height()
                    );

                    // 伝播されたブロックによってメインチェーンを更新
                    let current_block_id = self.nodes[*to].current_block_id();
                    self.choose_mainchain(*block_id, current_block_id, *from, *to);

                    // 受け取ったノードは次のマイニングタスクをキャンセルし、新しい難易度でスケジュールし直す
                    self.cancel_next_mining_task(*to);
                    let new_difficulty = self
                        .calculate_new_difficulty(self.blockchain.get_block(*block_id).unwrap());
                    self.schedule_next_mining_task(*to, self.current_time, new_difficulty);
                }
            }
        }
    }

    fn cancel_next_mining_task(&mut self, node: usize) {
        if let Some(next_time) = self.nodes[node].next_mining_time() {
            self.nodes[node].set_next_mining_time(None); // キャンセル
            // タスクキューから削除
            self.task_queue.retain(|task, _| {
                !(task.task_type() == &TaskType::BlockGeneration { minter: node }
                    && task.time() == next_time)
            });
        }
    }

    /// time_baseにマイニング時間を加算したものが次のマイニング時刻となる
    fn schedule_next_mining_task(&mut self, node: usize, time_base: i64, new_difficulty: f64) {
        let exp_dist = Exp::new(1.0).unwrap();
        let next_time = time_base
            + (exp_dist.sample(&mut self.rng) * self.generation_time as f64 * new_difficulty
                / self.nodes[node].hashrate() as f64
                * self.total_hashrate as f64) as i64;

        let task = Task::new(next_time, TaskType::BlockGeneration { minter: node });
        self.nodes[node].set_next_mining_time(Some(next_time));

        self.enqueue_task(task);
    }

    pub fn reset(&mut self) {
        self.current_round = 0;
        self.current_time = 0;
        for node in &mut self.nodes {
            node.reset();
        }
    }

    pub fn print_hashrates(&self) {
        log::info!(
            "hashrates: {:?}",
            self.nodes.iter().map(|n| n.hashrate()).collect::<Vec<_>>()
        );
    }

    pub fn print_blockchain(&self) {
        log::info!("Blockchain:");
        for block in self.blockchain.blocks() {
            log::info!(
                "Block ID: {}, Difficulty: {}, Height: {}, Minter: {}, Time: {}, Prev Block ID: {:?}, Rand: {}",
                block.id(),
                block.difficulty(),
                block.height(),
                block.minter(),
                block.time(),
                block.prev_block_id(),
                block.rand()
            );
        }
    }

    fn calculate_new_difficulty(&self, parent_block: &Block) -> f64 {
        self.protocol.calculate_difficulty(
            parent_block,
            self.current_time,
            self.generation_time,
            self.blockchain.blocks(),
        )
    }

    pub fn print_summary(&self) {
        log::info!("Simulation Summary:");
        log::info!("- Current time: {}", self.current_time);
        log::info!("- Current round: {}", self.current_round);
        log::info!("- Total blocks: {}", self.blockchain.len());
        let main_chain_length = self.blockchain.max_height();
        log::info!("- Main chain length: {}", main_chain_length);
        // diffculty
        log::info!(
            "Difficulty: {}",
            self.blockchain.last_block().map_or(0.0, |b| b.difficulty())
        );
        log::info!(
            "- Avg. time/block: {}",
            self.current_time as f64 / main_chain_length as f64
        );

        // Δ/T = 遅延 / 生成時間
        let ratio = self.delay as f64 / self.generation_time as f64;
        log::info!("- Δ/T: {:.2}", ratio);
    }
}
