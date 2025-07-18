use clap::{Parser, ValueEnum};
use priority_queue::PriorityQueue;
use rand::prelude::*;
use rand_distr::Exp;
use serde::Serialize;
use std::cmp::Ordering;
use std::path::PathBuf;
use std::sync::atomic::AtomicUsize;

#[derive(Clone, Debug)]
struct Block {
    height: i64,
    prev_block_id: Option<usize>,
    minter: i32,
    time: i64,
    rand: i64,
    id: usize,
    /// 大きいほど難しい。
    difficulty: f64,
}

#[derive(Clone, Debug, Hash)]
struct Task {
    time: i64,
    ty: TaskType,
}

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
enum TaskType {
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

#[derive(ValueEnum, Debug, Clone, Default, PartialEq)]
#[clap(rename_all = "kebab_case")]
enum TieBreakingRule {
    #[default]
    Longest,
    Random,
    Time,
}

#[derive(Serialize)]
struct Record {
    round: u32,
    difficulty: f64,
}

struct BlockchainSimulator {
    current_round: i64,
    current_time: i64,
    delay: i64,
    generation_time: i64,
    tie: TieBreakingRule,
    current_block: Vec<usize>,          // ブロックIDを保存
    next_mining_time: Vec<Option<i64>>, // 現在のマイニングタスク時間
    hashrate: Vec<i64>,
    total_hashrate: i64,
    end_round: i64,
    num_nodes: usize,
    blocks: Vec<Block>, // 全ブロックを保存
    rng: StdRng,
    /// CSV出力用のライター
    csv: Option<csv::Writer<std::fs::File>>,

    /// タスクキュー
    task_queue: PriorityQueue<Task, i64>,
}

impl BlockchainSimulator {
    fn new(
        num_nodes: usize,
        seed: u64,
        end_round: i64,
        tie: TieBreakingRule,
        delay: i64,
        generation_time: i64,
        csv: Option<csv::Writer<std::fs::File>>,
    ) -> Self {
        let mut hashrate = vec![1; num_nodes];
        if num_nodes > 0 {
            hashrate[0] = (num_nodes - 1) as i64;
        }

        let total_hashrate = hashrate.iter().sum();

        let task_queue = PriorityQueue::<Task, i64>::new();

        let mut simulator = Self {
            current_round: 0,
            current_time: 0,
            delay,
            generation_time,
            tie,
            current_block: vec![0; num_nodes], // 全ノードがジェネシスブロックから開始
            next_mining_time: vec![None; num_nodes],
            hashrate,
            total_hashrate,
            //num_main: vec![vec![0; num_nodes]; 3],
            end_round,
            //main_length: 0,
            num_nodes,
            blocks: Vec::new(),
            rng: StdRng::seed_from_u64(seed),
            csv,
            task_queue,
        };

        // ジェネシスブロック作成
        let genesis_block = Block {
            height: 0,
            prev_block_id: None,
            minter: -1,
            time: 0,
            rand: 0,
            id: 0,
            difficulty: 1.,
        };
        simulator.blocks.push(genesis_block);

        simulator
    }

    fn enqueue_task(&mut self, task: Task) {
        let time = task.time;
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
        let block1 = &self.blocks[block1_id];
        let block2 = &self.blocks[block2_id];

        if block1.height > block2.height {
            self.current_block[to] = block1_id;
            return;
        }

        if block1.height == block2.height {
            if self.tie == TieBreakingRule::Random
                && block2.minter != to as i32
                && block1.rand < block2.rand
            {
                self.current_block[to] = block1_id;
            }

            if self.tie == TieBreakingRule::Time
                && block2.minter != to as i32
                && block1.time > block2.time
            {
                self.current_block[to] = block1_id;
            }
        }

        //self.current_block[to] = block2_id;
    }

    /*
    fn mainchain(&mut self, block_id: usize, tie: usize) {
        let block = &self.blocks[block_id];

        if block.height != self.end_round {
            let height = block.height;
            let mut cur_block_id = block_id;

            // 100ブロック前まで遡る
            while self.blocks[cur_block_id].height > 0
                && self.blocks[cur_block_id].height != height - 100
            {
                if let Some(prev_id) = self.blocks[cur_block_id].prev_block_id {
                    cur_block_id = prev_id;
                } else {
                    break;
                }
            }

            if self.blocks[cur_block_id].height > 0 {
                let minter = self.blocks[cur_block_id].minter as usize;
                if minter < self.num_nodes {
                    self.num_main[tie][minter] += 1;
                }
            }
            self.main_length = self.main_length.max(self.blocks[cur_block_id].height);
        } else {
            let mut cur_block_id = block_id;
            while self.blocks[cur_block_id].height > self.main_length {
                let minter = self.blocks[cur_block_id].minter as usize;
                if minter < self.num_nodes {
                    self.num_main[tie][minter] += 1;
                }
                if let Some(prev_id) = self.blocks[cur_block_id].prev_block_id {
                    cur_block_id = prev_id;
                } else {
                    break;
                }
            }
        }
    }
    */

    /// シミュレーションを実行
    fn simulation(&mut self) {
        // 初期マイニングタスクをスケジュール
        for i in 0..self.num_nodes {
            let exp_dist = Exp::new(1.0).unwrap();
            // TODO: 難易度調整
            let time = (exp_dist.sample(&mut self.rng)
                * self.generation_time as f64
                * self.total_hashrate as f64
                / self.hashrate[i] as f64) as i64;

            let task = Task {
                time,
                ty: TaskType::BlockGeneration { minter: i },
            };

            self.next_mining_time[i] = Some(time);
            self.enqueue_task(task);
        }

        while !self.task_queue.is_empty() && self.current_round < self.end_round {
            let current_task = self.pop_task().expect("Task queue should not be empty");
            self.current_time = current_task.time;

            match current_task.ty {
                TaskType::BlockGeneration { minter } => {
                    // 現在のマイニングタスクかチェック
                    if let Some(task_time) = self.next_mining_time[minter] {
                        if task_time != current_task.time {
                            continue;
                        }
                    } else {
                        continue;
                    }

                    // 新しいブロック作成
                    let current_block_id = self.current_block[minter];
                    let current_block = &self.blocks[current_block_id];

                    // 難易度調整
                    let new_difficulty = self.calculate_new_difficulty(current_block);
                    //if current_block.height % 2000 == 0 {
                    if let Some(csv) = &mut self.csv {
                        csv.serialize(&Record {
                            round: current_block.height as u32,
                            difficulty: new_difficulty,
                        })
                        .expect("Failed to write CSV record");
                    }
                    //}

                    static BLOCK_ID: AtomicUsize = AtomicUsize::new(1);
                    let new_block = Block {
                        height: current_block.height + 1,
                        prev_block_id: Some(current_block_id),
                        minter: minter as i32,
                        time: self.current_time,
                        rand: (self.rng.r#gen::<f64>() * (i64::MAX - 10) as f64) as i64,
                        id: BLOCK_ID.fetch_add(1, std::sync::atomic::Ordering::SeqCst),
                        difficulty: new_difficulty,
                    };

                    self.blocks.push(new_block.clone());
                    self.current_block[minter] = new_block.id;
                    if self.current_round < new_block.height {
                        self.current_round = new_block.height;
                    }

                    // 次のマイニングタスクをスケジュール
                    let Some(next_time) = self.next_mining_time[minter] else {
                        unreachable!("next_mining_time should be set for all nodes");
                    };
                    self.schedule_next_mining_task(minter, next_time, new_difficulty);

                    // 伝播タスクをスケジュール
                    for i in 0..self.num_nodes {
                        if i != minter {
                            let prop_task = Task {
                                time: next_time + self.propagation_time(minter, i),
                                ty: TaskType::Propagation {
                                    from: minter,
                                    to: i,
                                    block_id: self.current_block[minter],
                                },
                            };
                            self.enqueue_task(prop_task);
                        }
                    }

                    log::debug!(
                        "📦 time: {}, minter: {}, difficulty: {}, height: {}",
                        self.current_time,
                        new_block.minter,
                        new_block.difficulty,
                        new_block.height
                    );
                }

                TaskType::Propagation { from, to, block_id } => {
                    log::debug!(
                        "🚚 time: {}, {}->{}, height: {}",
                        self.current_time,
                        from,
                        to,
                        self.blocks[block_id].height
                    );

                    // 伝播されたブロックによってメインチェーンを更新
                    let current_block_id = self.current_block[to];
                    self.choose_mainchain(block_id, current_block_id, from, to);

                    // 受け取ったノードは次のマイニングタスクをキャンセルし、新しい難易度でスケジュールし直す
                    self.cancel_next_mining_task(to);
                    let new_difficulty = self.calculate_new_difficulty(&self.blocks[block_id]);
                    self.schedule_next_mining_task(to, self.current_time, new_difficulty);
                }
            }
        }
    }

    fn cancel_next_mining_task(&mut self, node: usize) {
        if let Some(next_time) = self.next_mining_time[node] {
            self.next_mining_time[node] = None; // キャンセル
            // タスクキューから削除
            self.task_queue.retain(|task, _| {
                !(task.ty == TaskType::BlockGeneration { minter: node } && task.time == next_time)
            });
        }
    }

    /// time_baseにマイニング時間を加算したものが次のマイニング時刻となる
    fn schedule_next_mining_task(&mut self, node: usize, time_base: i64, new_difficulty: f64) {
        let exp_dist = Exp::new(1.0).unwrap();
        let next_time = time_base
            + (exp_dist.sample(&mut self.rng) * self.generation_time as f64 * new_difficulty
                / (self.hashrate[node] as f64 / self.total_hashrate as f64)) as i64;

        let task = Task {
            time: next_time,
            ty: TaskType::BlockGeneration { minter: node },
        };
        self.next_mining_time[node] = Some(next_time);

        self.enqueue_task(task);
    }

    fn reset(&mut self) {
        self.current_round = 0;
        self.current_time = 0;
        for i in 0..self.num_nodes {
            self.current_block[i] = 0; // ジェネシスブロックID
        }
    }

    fn print_hashrates(&self) {
        log::info!("hashrates: {:?}", self.hashrate);
    }

    fn print_blockchain(&self) {
        log::info!("Blockchain:");
        for block in &self.blocks {
            log::info!(
                "Block ID: {}, Difficulty: {}, Height: {}, Minter: {}, Time: {}, Prev Block ID: {:?}, Rand: {}",
                block.id,
                block.difficulty,
                block.height,
                block.minter,
                block.time,
                block.prev_block_id,
                block.rand
            );
        }
    }

    fn calculate_new_difficulty(&self, current_block: &Block) -> f64 {
        let current_block_id = current_block.id;
        let current_difficulty = current_block.difficulty;
        let current_height = current_block.height;

        let new_height = current_height + 1;

        let new_difficulty = if new_height % 2000 == 0 && new_height >= 2000 {
            let (first_block_in_epoch, height) = {
                let mut block_id = current_block_id;
                for _ in 0..2000 {
                    if let Some(prev_id) = self.blocks[block_id].prev_block_id {
                        block_id = prev_id;
                    } else {
                        break;
                    }
                }
                (block_id, self.blocks[block_id].height)
            };
            let average_generation_time =
                (self.current_time - self.blocks[first_block_in_epoch].time) as f64
                    / (current_block.height - height) as f64;
            let ratio = average_generation_time / self.generation_time as f64;
            let d = if ratio < 0.5 {
                current_difficulty * 0.25
            } else if ratio > 2.0 {
                current_difficulty * 4.
            } else {
                current_difficulty / ratio
            };
            log::trace!(
                "Difficulty adjustment: height: {}, avg. block/time: {:.2} ratio: {:.2}, {:.2}=>{:.2}",
                new_height,
                average_generation_time,
                ratio,
                current_difficulty,
                d
            );
            d
        } else {
            current_difficulty
        };

        new_difficulty
    }

    fn print_summary(&self) {
        log::info!("Simulation Summary:");
        log::info!("- Current time: {}", self.current_time);
        log::info!("- Current round: {}", self.current_round);
        log::info!("- Total blocks: {}", self.blocks.len());
        let main_chain_length = self.blocks.iter().map(|b| b.height).max().unwrap_or(0);
        log::info!("- Main chain length: {}", main_chain_length);
        // diffculty
        log::info!(
            "Difficulty: {}",
            self.blocks.last().map_or(0.0, |b| b.difficulty)
        );
        log::info!(
            "- Avg. time/block: {}",
            self.current_time as f64 / main_chain_length as f64
        );

        // delta = 遅延 / 生成時間
        let delta = self.delay as f64 / self.generation_time as f64;
        log::info!("- Delta (delay/generation_time): {:.2}", delta);
    }
}

#[derive(Parser, Debug, Clone)]
struct Cli {
    #[clap(short, long, default_value = "10")]
    num_nodes: usize,

    #[clap(short, long)]
    seed: Option<u64>,

    #[clap(long, default_value = "10")]
    end_round: i64,

    #[clap(long, value_enum, default_value_t = TieBreakingRule::Longest)]
    #[arg(value_enum)]
    tie: TieBreakingRule,

    #[clap(long, default_value = "6000")]
    delay: i64, // ブロック伝播時間

    #[clap(long, default_value = "600000")]
    generation_time: i64, // ブロック生成時間

    /// CSV出力ファイルパス
    #[clap(long, short)]
    output: Option<PathBuf>,
}

fn main() {
    env_logger::init();

    let mut args = Cli::parse();
    if args.seed.is_none() {
        args.seed = Some(rand::thread_rng().r#gen::<u64>());
    }
    log::info!("args: {:?}", args);

    let output = args
        .output
        .map(|path| csv::Writer::from_path(path).expect("Failed to create CSV writer"));

    let mut simulator = BlockchainSimulator::new(
        args.num_nodes,
        args.seed.unwrap(),
        args.end_round,
        args.tie,
        args.delay,
        args.generation_time,
        output,
    );

    simulator.print_hashrates();
    simulator.simulation();
    //simulator.print_blockchain();
    simulator.print_summary();
}
