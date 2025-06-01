use clap::Parser;
use rand::prelude::*;
use rand_distr::Exp;
use std::cmp::Ordering;
use std::collections::BinaryHeap;

#[derive(Clone, Debug)]
struct Block {
    height: i64,
    prev_block_id: Option<usize>,
    minter: i32,
    time: i64,
    rand: i64,
    id: usize,
}

#[derive(Clone, Debug)]
struct Task {
    time: i64,
    flag: TaskType,
}

#[derive(Clone, Debug)]
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

struct BlockchainSimulator {
    current_round: i64,
    current_time: i64,
    delay: i64,
    generation_time: i64,
    current_block: Vec<usize>,             // ブロックIDを保存
    current_mining_task: Vec<Option<i64>>, // 現在のマイニングタスク時間
    hashrate: Vec<i64>,
    total_hashrate: i64,
    num_main: Vec<Vec<i64>>,
    end_round: i64,
    main_length: i64,
    num_nodes: usize,
    blocks: Vec<Block>, // 全ブロックを保存
    next_block_id: usize,
    rng: StdRng,
}

impl BlockchainSimulator {
    fn new(num_nodes: usize, seed: u64, end_round: i64) -> Self {
        let mut hashrate = vec![1; num_nodes];
        if num_nodes > 0 {
            hashrate[0] = (num_nodes - 1) as i64;
        }

        let total_hashrate = hashrate.iter().sum();

        let mut simulator = Self {
            current_round: 0,
            current_time: 0,
            delay: 6000,
            generation_time: 600000,
            current_block: vec![0; num_nodes], // 全ノードがジェネシスブロックから開始
            current_mining_task: vec![None; num_nodes],
            hashrate,
            total_hashrate,
            num_main: vec![vec![0; num_nodes]; 3],
            end_round,
            main_length: 0,
            num_nodes,
            blocks: Vec::new(),
            next_block_id: 0,
            rng: StdRng::seed_from_u64(seed),
        };

        // ジェネシスブロック作成
        let genesis_block = Block {
            height: 0,
            prev_block_id: None,
            minter: -1,
            time: 0,
            rand: 0,
            id: 0,
        };
        simulator.blocks.push(genesis_block);
        simulator.next_block_id = 1;

        simulator
    }

    fn prop(&self, i: usize, j: usize) -> i64 {
        if i == j { 0 } else { self.delay }
    }

    fn choose_mainchain(
        &mut self,
        block1_id: usize,
        block2_id: usize,
        _from: usize,
        to: usize,
        tie: i32,
    ) {
        let block1 = &self.blocks[block1_id];
        let block2 = &self.blocks[block2_id];

        if block1.height > block2.height {
            self.current_block[to] = block1_id;
            return;
        }

        if block1.height == block2.height {
            if tie == 1 && block2.minter != to as i32 && block1.rand < block2.rand {
                self.current_block[to] = block1_id;
            }

            if tie == 2 && block2.minter != to as i32 && block1.time > block2.time {
                self.current_block[to] = block1_id;
            }
        }
    }

    /*
    fn main_chain(&mut self, block_id: usize, tie: usize) {
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
                    println!("sugeeeee");
                    break;
                }
            }

            if self.blocks[cur_block_id].height > 0 {
                let minter = self.blocks[cur_block_id].minter as usize;
                if minter < self.n {
                    self.num_main[tie][minter] += 1;
                }
            }
            self.main_length = self.main_length.max(self.blocks[cur_block_id].height);
        } else {
            let mut cur_block_id = block_id;
            while self.blocks[cur_block_id].height > self.main_length {
                let minter = self.blocks[cur_block_id].minter as usize;
                if minter < self.n {
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

    fn simulation(&mut self, tie: i32) {
        let mut task_queue = BinaryHeap::new();

        // 初期マイニングタスクをスケジュール
        for i in 0..self.num_nodes {
            let exp_dist = Exp::new(1.0).unwrap();
            let time = (exp_dist.sample(&mut self.rng)
                * self.generation_time as f64
                * self.total_hashrate as f64
                / self.hashrate[i] as f64) as i64;

            let task = Task {
                time,
                flag: TaskType::BlockGeneration { minter: i },
            };

            self.current_mining_task[i] = Some(time);
            task_queue.push(task);
        }

        while !task_queue.is_empty() && self.current_round < self.end_round {
            let current_task = task_queue.pop().unwrap();
            self.current_time = current_task.time;

            match current_task.flag {
                TaskType::BlockGeneration { minter } => {
                    // 現在のマイニングタスクかチェック
                    if let Some(task_time) = self.current_mining_task[minter] {
                        if task_time != current_task.time {
                            continue;
                        }
                    } else {
                        continue;
                    }

                    // 新しいブロック作成
                    let current_block_id = self.current_block[minter];
                    let new_block = Block {
                        height: self.blocks[current_block_id].height + 1,
                        prev_block_id: Some(current_block_id),
                        minter: minter as i32,
                        time: self.current_time,
                        rand: (self.rng.r#gen::<f64>() * (i64::MAX - 10) as f64) as i64,
                        id: self.next_block_id,
                    };

                    self.blocks.push(new_block.clone());
                    self.current_block[minter] = new_block.id;
                    self.next_block_id += 1;

                    // 次のマイニングタスクをスケジュール
                    let exp_dist = Exp::new(1.0).unwrap();
                    let next_time = self.current_time
                        + (exp_dist.sample(&mut self.rng)
                            * self.generation_time as f64
                            * self.total_hashrate as f64
                            / self.hashrate[minter] as f64) as i64;

                    let next_task = Task {
                        time: next_time,
                        flag: TaskType::BlockGeneration { minter },
                    };

                    self.current_mining_task[minter] = Some(next_time);
                    task_queue.push(next_task);

                    // 伝播タスクを作成
                    for i in 0..self.num_nodes {
                        let prop_task = Task {
                            time: self.current_time + self.prop(minter, i),
                            flag: TaskType::Propagation {
                                from: minter,
                                to: i,
                                block_id: new_block.id,
                            },
                        };
                        task_queue.push(prop_task);
                    }

                    if self.current_round < new_block.height {
                        self.current_round = new_block.height;
                    }

                    log::debug!(
                        "block generation, current time: {}, minter{}, block height: {}",
                        self.current_time,
                        new_block.minter,
                        new_block.height
                    );
                }

                TaskType::Propagation { from, to, block_id } => {
                    log::debug!(
                        "block propagation, current time: {}, from: {}, to: {}, height: {}",
                        self.current_time,
                        from,
                        to,
                        self.blocks[block_id].height
                    );

                    let current_block_id = self.current_block[to];
                    self.choose_mainchain(block_id, current_block_id, from, to, tie);
                }
            }
        }
    }

    fn reset(&mut self) {
        self.current_round = 0;
        self.current_time = 0;
        self.main_length = 0;
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
                "Block ID: {}, Height: {}, Minter: {}, Time: {}, Prev Block ID: {:?}, Rand: {}",
                block.id,
                block.height,
                block.minter,
                block.time,
                block.prev_block_id,
                block.rand
            );
        }
    }
}

#[derive(Parser, Debug, Clone)]
struct Cli {
    #[clap(short, long, default_value = "10")]
    num_nodes: usize,

    #[clap(short, long)]
    seed: Option<u64>,

    #[clap(short, long, default_value = "10")]
    end_round: i64,
}

fn main() {
    env_logger::init();

    let args = Cli::parse();
    let seed = args.seed.unwrap_or(rand::thread_rng().r#gen::<u64>());

    log::info!(
        "num_nodes: {}, seed: {}, end_round: {}",
        args.num_nodes,
        seed,
        args.end_round
    );

    let mut simulator = BlockchainSimulator::new(args.num_nodes, seed, args.end_round);

    simulator.print_hashrates();
    simulator.simulation(10);
    simulator.print_blockchain();

    log::info!("block propagation time: {}", simulator.delay);
}
