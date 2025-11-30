use crate::block::Block;
use crate::blockchain::Blockchain;
use crate::event::{Event, EventType};
use crate::mining_strategy::Action;
use crate::node::Node;
use crate::profile::NetworkProfile;
use crate::protocol::Protocol;
use crate::types::TieBreakingRule;
use priority_queue::PriorityQueue;
use rand::prelude::*;
use rand_distr::Exp;

pub struct Env {
    // Configuration
    pub num_nodes: usize,
    pub delay: i64,
    pub generation_time: i64,
    // Current environments
    // TODO:
}

pub struct BlockchainSimulator {
    env: Env,
    /// 作成された最大のブロックの高さ
    current_round: i64,
    current_time: i64,
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
    event_queue: PriorityQueue<Event, i64>,
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

        let event_queue = PriorityQueue::<Event, i64>::new();

        Self {
            env: Env {
                num_nodes,
                delay,
                generation_time,
            },
            current_round: 0,
            current_time: 0,
            tie,
            nodes,
            total_hashrate,
            end_round,
            blockchain: Blockchain::new(),
            rng,
            protocol,
            csv,
            event_queue,
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
        let event_queue = PriorityQueue::<Event, i64>::new();
        let rng = StdRng::seed_from_u64(seed);

        Ok(Self {
            env: Env {
                num_nodes: profile.num_nodes(),
                delay,
                generation_time,
            },
            current_round: 0,
            current_time: 0,
            tie,
            nodes,
            total_hashrate,
            end_round,
            blockchain: Blockchain::new(),
            rng,
            protocol,
            csv,
            event_queue,
        })
    }

    fn enqueue_event(&mut self, task: Event) {
        let time = task.time();
        // PriorityQueueは最大キューなので符号反転する
        self.event_queue.push(task, -time);
    }

    fn pop_event(&mut self) -> Option<Event> {
        self.event_queue.pop().map(|(task, _)| task)
    }

    fn propagation_time(&self, from: usize, to: usize) -> i64 {
        if from == to { 0 } else { self.env.delay }
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

    pub fn enqueue_actions(&mut self, node_id: usize, actions: &[Action]) {
        // アクションを発行した時間
        // アクションの完了時間にタスクがエンキューされる
        let base_time = self.current_time;
        for action in actions {
            let mut event_type = match action {
                Action::Propagate { block_id, to } => EventType::Propagation {
                    from: node_id,
                    to: *to,
                    block_id: *block_id,
                },
                Action::RestartMining { prev_block_id } => EventType::BlockGeneration {
                    minter: node_id,
                    prev_block_id: *prev_block_id,
                    // Dummy. We set it to proper value at the end of the function.
                    block_id: 0,
                },
            };

            match event_type {
                EventType::BlockGeneration {
                    minter,
                    prev_block_id,
                    block_id: _,
                } => {
                    let mining_base_block = self.blockchain.get_block(prev_block_id).unwrap();

                    // Difficulty adjustment
                    let new_difficulty = self.calculate_new_difficulty(mining_base_block);
                    let exp_dist = Exp::new(1.0).unwrap();
                    let next_mining_time = base_time
                        + (exp_dist.sample(&mut self.rng)
                            * self.env.generation_time as f64
                            * new_difficulty
                            / self.nodes[minter].hashrate() as f64
                            * self.total_hashrate as f64) as i64;

                    // ノードのnext_mining_timeを更新
                    self.nodes[minter].set_next_mining_time(Some(next_mining_time));

                    // すでにキューにある同じノードのマイニングタスクを削除
                    self.event_queue.retain(|task, _| {
                        let EventType::BlockGeneration {
                            minter: event_minter,
                            prev_block_id: _,
                            block_id: _,
                        } = task.event_type()
                        else {
                            return true;
                        };
                        *event_minter != node_id
                    });

                    // ブロックを作成
                    let new_block = Block::new(
                        mining_base_block.height() + 1,
                        Some(prev_block_id),
                        minter as i32,
                        self.current_time,
                        (self.rng.r#gen::<f64>() * (i64::MAX - 10) as f64) as i64,
                        self.blockchain.next_block_id(),
                        new_difficulty,
                        self.current_time - mining_base_block.time(),
                    );

                    let EventType::BlockGeneration {
                        minter: _,
                        prev_block_id: _,
                        block_id,
                    } = &mut event_type
                    else {
                        unreachable!("event_type should be BlockGeneration");
                    };
                    *block_id = new_block.id();
                    self.enqueue_event(Event::new(next_mining_time, event_type));
                    self.blockchain.add_block(new_block);
                }
                EventType::Propagation {
                    from,
                    to,
                    block_id: _,
                } => {
                    let prop_delay = self.propagation_time(from, to);
                    let event_time = base_time + prop_delay;
                    self.enqueue_event(Event::new(event_time, event_type));
                }
            }
        }
    }

    /// シミュレーションを実行
    pub fn simulation(&mut self) {
        // 初期マイニングタスクをスケジュール
        for node_id in 0..self.nodes.len() {
            let actions = vec![Action::RestartMining { prev_block_id: 0 }];
            self.enqueue_actions(node_id, &actions);
        }

        while !self.event_queue.is_empty() && self.current_round < self.end_round {
            let current_event = self.pop_event().expect("Task queue should not be empty");
            self.current_time = current_event.time();

            match current_event.event_type() {
                EventType::BlockGeneration {
                    minter,
                    prev_block_id: _,
                    block_id,
                } => {
                    let Some(event_time) = self.nodes[*minter].next_mining_time() else {
                        panic!("Node {} has no next mining time", *minter);
                    };
                    debug_assert_eq!(event_time, current_event.time());

                    let new_block = self.blockchain.get_block(*block_id).unwrap();

                    // コールバックを呼び出してタスクをスケジュール
                    let block = self.blockchain.get_block(*block_id).unwrap();
                    let actions = self.nodes[*minter].mining_strategy_mut().on_mining_block(
                        block,
                        self.current_time,
                        &self.env,
                        *minter,
                    );

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

                    self.enqueue_actions(*minter, &actions);
                }

                EventType::Propagation { from, to, block_id } => {
                    log::trace!(
                        "🚚 time: {}, {}->{}, height: {}",
                        self.current_time,
                        from,
                        to,
                        self.blockchain.get_block(*block_id).unwrap().height()
                    );

                    // 伝播されたブロックによってメインチェーンを更新
                    let current_block_id = self.nodes[*to].current_block_id();
                    self.choose_mainchain(*block_id, current_block_id, *from, *to);

                    // コールバックを呼び出してタスクをスケジュール
                    let block = self.blockchain.get_block(*block_id).unwrap();
                    let actions = self.nodes[*to].mining_strategy_mut().on_receiving_block(
                        block,
                        self.current_time,
                        &self.env,
                        *to,
                    );
                    self.enqueue_actions(*to, &actions);
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
            self.env.generation_time,
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
        let ratio = self.env.delay as f64 / self.env.generation_time as f64;
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
