use crate::block::Block;
use crate::blockchain::Blockchain;
use crate::node::Node;
use crate::profile::NetworkProfile;
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
    pub blockchain: Blockchain,
    rng: StdRng,
    protocol: Box<dyn Protocol>,
    /// CSV出力用のライター
    pub csv: Option<csv::Writer<std::fs::File>>,

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
            task_queue,
        }
    }

    /// プロファイルからシミュレーターを作成
    pub fn new_with_profile(
        profile: NetworkProfile,
        seed: u64,
        end_round: i64,
        tie: TieBreakingRule,
        delay: i64,
        generation_time: i64,
        protocol: Box<dyn Protocol>,
        csv: Option<csv::Writer<std::fs::File>>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let mut nodes = Vec::with_capacity(profile.num_nodes());

        // プロファイルからノードを作成
        for i in 0..profile.num_nodes() {
            let node_profile = &profile.nodes[i];
            let strategy = profile.create_strategy(i)?;
            nodes.push(Node::new_with_strategy(i, node_profile.hashrate, strategy));
        }

        log::info!(
            "Hashrates: {:?}",
            nodes.iter().map(|n| n.hashrate()).collect::<Vec<_>>()
        );

        let total_hashrate = nodes.iter().map(|n| n.hashrate()).sum();
        let task_queue = PriorityQueue::<Task, i64>::new();
        let rng = StdRng::seed_from_u64(seed);

        Ok(Self {
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
            task_queue,
        })
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

                    // プライベートチェーンがあれば先頭ブロックを起点にマイニングする
                    let mining_base_block_id =
                        if let Some(private_tip) = self.nodes[*minter].private_chain_tip() {
                            private_tip
                        } else {
                            self.nodes[*minter].current_block_id()
                        };
                    let mining_base_block =
                        self.blockchain.get_block(mining_base_block_id).unwrap();

                    // 難易度調整
                    let new_difficulty = self.calculate_new_difficulty(mining_base_block);

                    // 次のマイニングタスクの時刻を計算
                    let exp_dist = Exp::new(1.0).unwrap();
                    let Some(current_mining_time) = self.nodes[*minter].next_mining_time() else {
                        unreachable!("next_mining_time should be set for all nodes");
                    };
                    let next_mining_time = current_mining_time
                        + (exp_dist.sample(&mut self.rng)
                            * self.generation_time as f64
                            * new_difficulty
                            / self.nodes[*minter].hashrate() as f64
                            * self.total_hashrate as f64) as i64;

                    let new_block = Block::new(
                        mining_base_block.height() + 1,
                        Some(mining_base_block_id),
                        *minter as i32,
                        self.current_time,
                        (self.rng.r#gen::<f64>() * (i64::MAX - 10) as f64) as i64,
                        self.blockchain.next_block_id(),
                        new_difficulty,
                        self.current_time - mining_base_block.time(),
                    );

                    let new_block_id = self.blockchain.add_block(new_block.clone());

                    // プライベートチェーンの先頭に設定
                    self.nodes[*minter].set_private_chain_tip(Some(new_block_id));

                    // 公開チェーンの高さを取得（current_block_idから辿る）
                    let public_chain_height = {
                        let public_block = self
                            .blockchain
                            .get_block(self.nodes[*minter].current_block_id())
                            .unwrap();
                        public_block.height()
                    };

                    // プライベートチェーンの高さ
                    let private_chain_height = new_block.height();

                    // ノード数を事前に取得
                    let num_nodes = self.nodes.len();

                    // コールバックを呼び出してタスクをスケジュール
                    let tasks = self.nodes[*minter].mining_strategy_mut().on_mining_block(
                        new_block_id,
                        self.current_time,
                        next_mining_time,
                        *minter,
                        num_nodes,
                        self.delay,
                        private_chain_height,
                        public_chain_height,
                    );

                    // 返されたタスクをスケジュール
                    for task in tasks {
                        if matches!(task.task_type(), TaskType::BlockGeneration { .. }) {
                            self.nodes[*minter].set_next_mining_time(Some(task.time()));
                        }
                        self.enqueue_task(task);
                    }

                    if self.current_round < new_block.height() {
                        self.current_round = new_block.height();
                    }

                    log::trace!(
                        "📦 time: {}, minter: {}, difficulty: {}, height: {}",
                        self.current_time,
                        new_block.minter(),
                        new_block.difficulty(),
                        new_block.height()
                    );
                }

                TaskType::Propagation { from, to, block_id } => {
                    log::trace!(
                        "🚚 time: {}, {}->{}, height: {}",
                        self.current_time,
                        from,
                        to,
                        self.blockchain.get_block(*block_id).unwrap().height()
                    );

                    // 伝播されたブロックによってメインチェーンを更新
                    let current_block_id = self.nodes[*to].current_block_id();
                    // 受信前の公開チェーンの高さを取得
                    let public_chain_height_before = {
                        let current_block = self.blockchain.get_block(current_block_id).unwrap();
                        current_block.height()
                    };
                    self.choose_mainchain(*block_id, current_block_id, *from, *to);

                    // メインチェーンが更新されたかチェック
                    let new_block_id = self.nodes[*to].current_block_id();
                    let (new_height, new_difficulty) = {
                        let new_block = self.blockchain.get_block(new_block_id).unwrap();
                        let height = new_block.height();
                        let difficulty = self.calculate_new_difficulty(new_block);
                        (height, difficulty)
                    };

                    // プライベートチェーンの情報を取得
                    let (private_chain_height, private_tip_id, private_chain_blocks) =
                        if let Some(private_tip_id) = self.nodes[*to].private_chain_tip() {
                            let private_tip_block =
                                self.blockchain.get_block(private_tip_id).unwrap();
                            let private_chain_height = private_tip_block.height();

                            // 公開チェーンがプライベートチェーンを追い越した場合、プライベートチェーンを無効化
                            if new_height > private_chain_height {
                                self.nodes[*to].set_private_chain_tip(None);
                                (None, None, Vec::new())
                            } else {
                                // プライベートチェーンのブロックIDリストを構築（公開チェーンの高さより大きいブロックのみ、古い順）
                                let mut private_chain_blocks = Vec::new();
                                let mut current_id = private_tip_id;
                                loop {
                                    let block = self.blockchain.get_block(current_id).unwrap();
                                    if block.height() <= new_height {
                                        break;
                                    }
                                    private_chain_blocks.push(current_id);
                                    if let Some(prev_id) = block.prev_block_id() {
                                        current_id = prev_id;
                                    } else {
                                        break;
                                    }
                                }
                                private_chain_blocks.reverse(); // 古い順にソート
                                (
                                    Some(private_chain_height),
                                    Some(private_tip_id),
                                    private_chain_blocks,
                                )
                            }
                        } else {
                            (None, None, Vec::new())
                        };

                    // 受け取ったノードは次のマイニングタスクをキャンセル
                    self.cancel_incoming_mining_task(*to);

                    // 次のマイニングタスクの時刻を計算
                    let exp_dist = Exp::new(1.0).unwrap();
                    let next_mining_time = self.current_time
                        + (exp_dist.sample(&mut self.rng)
                            * self.generation_time as f64
                            * new_difficulty
                            / self.nodes[*to].hashrate() as f64
                            * self.total_hashrate as f64) as i64;

                    // ノード数を事前に取得
                    let num_nodes = self.nodes.len();

                    // コールバックを呼び出してタスクをスケジュール
                    // 受信前の公開チェーンの高さを渡す（リード計算に必要）
                    let tasks = self.nodes[*to].mining_strategy_mut().on_receiving_block(
                        *block_id,
                        self.current_time,
                        next_mining_time,
                        *to,
                        num_nodes,
                        self.delay,
                        private_chain_height,
                        public_chain_height_before,
                        private_tip_id,
                        private_chain_blocks,
                    );

                    // 返されたタスクをスケジュール
                    let mut has_propagation_task = false;
                    for task in tasks {
                        if matches!(task.task_type(), TaskType::Propagation { .. }) {
                            has_propagation_task = true;
                        }
                        if matches!(task.task_type(), TaskType::BlockGeneration { .. }) {
                            self.nodes[*to].set_next_mining_time(Some(task.time()));
                        }
                        self.enqueue_task(task);
                    }

                    // ブロックが公開された場合、プライベートチェーンをクリア
                    if has_propagation_task && private_tip_id.is_some() {
                        // プライベートチェーンをクリアし、公開チェーンに切り替え
                        if let Some(tip_id) = private_tip_id {
                            self.nodes[*to].set_current_block_id(tip_id);
                        }
                        self.nodes[*to].set_private_chain_tip(None);
                    }
                }
            }
        }
    }

    fn cancel_incoming_mining_task(&mut self, node: usize) {
        self.nodes[node].set_next_mining_time(None);
        self.task_queue
            .retain(|task, _| !(task.task_type() == &TaskType::BlockGeneration { minter: node }));
    }

    /// プライベートチェーンのすべてのブロックを公開する
    /// `tip_block_id`: プライベートチェーンの先頭ブロックID
    /// `base_publish_time`: 公開開始時刻
    fn publish_private_chain(
        &mut self,
        minter: usize,
        tip_block_id: usize,
        base_publish_time: i64,
    ) {
        // プライベートチェーンを構築（tipからprev_block_idを辿る）
        let mut private_chain = Vec::new();
        let mut current_id = tip_block_id;
        let public_block_id = self.nodes[minter].current_block_id();

        // 公開チェーンの先頭ブロックを取得
        let public_block = self.blockchain.get_block(public_block_id).unwrap();
        let public_height = public_block.height();

        // プライベートチェーンを構築（公開チェーンの高さより大きいブロックのみ）
        loop {
            let block = self.blockchain.get_block(current_id).unwrap();
            if block.height() <= public_height {
                break;
            }
            private_chain.push(current_id);
            if let Some(prev_id) = block.prev_block_id() {
                current_id = prev_id;
            } else {
                break;
            }
        }

        // プライベートチェーンを逆順にして、古いブロックから順に公開
        private_chain.reverse();

        // 各ブロックを順番に伝播
        for (idx, &block_id) in private_chain.iter().enumerate() {
            for i in 0..self.nodes.len() {
                if i != minter {
                    let publish_time = base_publish_time + (idx as i64 * self.delay);
                    let prop_delay = self.propagation_time(minter, i);
                    let prop_task = Task::new(
                        publish_time + prop_delay,
                        TaskType::Propagation {
                            from: minter,
                            to: i,
                            block_id,
                        },
                    );
                    self.enqueue_task(prop_task);
                }
            }
        }
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

    /// メインチェーンをトラバーサルして報酬を計算し、mining fairnessを表示する
    /// mining fairness = rewardのシェア / hashrateのシェア
    pub fn print_mining_fairness(&self) {
        let main_chain = self.blockchain.get_main_chain();

        // 各ノードの報酬をカウント（ジェネシスブロックを除く）
        let mut rewards: Vec<f64> = vec![0.0; self.nodes.len()];

        for &block_id in &main_chain {
            if let Some(block) = self.blockchain.get_block(block_id) {
                let minter = block.minter();
                if minter >= 0 {
                    let node_id = minter as usize;
                    if node_id < rewards.len() {
                        rewards[node_id] += 1.0;
                    }
                }
            }
        }

        // 全ノードの報酬の合計を計算
        let total_reward: f64 = rewards.iter().sum();

        // mining fairness = rewardのシェア / hashrateのシェア を計算
        let mut fairness_data: Vec<(usize, f64, f64, f64, f64, f64)> = self
            .nodes
            .iter()
            .enumerate()
            .map(|(i, node)| {
                let reward = rewards[i];
                let hashrate = node.hashrate() as f64;

                // rewardのシェア = そのノードの報酬 / 全ノードの報酬の合計
                let reward_share = if total_reward > 0.0 {
                    reward / total_reward
                } else {
                    0.0
                };

                // hashrateのシェア = そのノードのハッシュレート / 全ノードのハッシュレートの合計
                let hashrate_share = if self.total_hashrate > 0 {
                    hashrate / self.total_hashrate as f64
                } else {
                    0.0
                };

                // mining fairness = rewardのシェア / hashrateのシェア
                let fairness = if hashrate_share > 0.0 {
                    reward_share / hashrate_share
                } else {
                    0.0
                };

                (i, reward, hashrate, reward_share, hashrate_share, fairness)
            })
            .collect();

        // mining fairnessが高い順にソート
        fairness_data.sort_by(|a, b| b.5.partial_cmp(&a.5).unwrap_or(std::cmp::Ordering::Equal));

        // ノード数が30以下の場合は全て表示、それ以上の場合は上位5位のみ表示
        let display_count = if self.nodes.len() <= 30 {
            self.nodes.len()
        } else {
            30
        };

        if display_count == self.nodes.len() {
            log::info!("Mining Fairness Ranking (all nodes):");
        } else {
            log::info!("Mining Fairness Ranking (top {}):", display_count);
        }
        log::info!(
            "Rank | Node ID | Reward (%) | Hashrate (%) | Fairness (Reward Share/Hashrate Share) | Strategy"
        );
        log::info!(
            "-----|---------|------------|--------------|--------------------------|----------"
        );

        for (rank, (node_id, _reward, _hashrate, reward_share, hashrate_share, fairness)) in
            fairness_data.iter().take(display_count).enumerate()
        {
            let strategy_name = self.nodes[*node_id].mining_strategy().name();
            log::info!(
                "{:4} | {:7} | {:10.2} | {:12.2} | {:24.6} | {}",
                rank + 1,
                node_id,
                reward_share * 100.0,
                hashrate_share * 100.0,
                fairness,
                strategy_name
            );
        }
    }
}
