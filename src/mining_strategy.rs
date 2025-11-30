use crate::{Block, simulator::Env};
use serde::{Deserialize, Serialize};

pub enum Action {
    /// Propagate a block to a node.
    Propagate { block_id: usize, to: usize },
    /// Reschedule a mining task.
    RestartMining { prev_block_id: usize },
}

/// マイニング戦略のトレイト
pub trait MiningStrategy: Send + Sync {
    /// 戦略の名前を取得する
    fn name(&self) -> &'static str;

    /// ブロック生成時に呼ばれるコールバック
    /// 返り値: スケジュールすべきタスクのリスト（propagation task と mining task）
    fn on_mining_block(
        &mut self,
        _block: &Block,
        _current_time: i64,
        _env: &Env,
        _node_id: usize,
    ) -> Vec<Action> {
        Vec::new()
    }

    /// ブロック受信時に呼ばれるコールバック
    /// 返り値: スケジュールすべきタスクのリスト（propagation task と mining task）
    ///
    /// `private_chain_blocks`:
    ///   プライベートチェーンのブロック ID リスト。
    ///   「公開チェーンの高さより大きいブロックのみ」を古い順に並べたものを想定。
    fn on_receiving_block(
        &mut self,
        _block: &Block,
        _current_time: i64,
        _env: &Env,
        _node_id: usize,
    ) -> Vec<Action> {
        Vec::new()
    }
}

/// 通常のマイニング戦略（何も調整しない）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HonestMiningStrategy;

impl MiningStrategy for HonestMiningStrategy {
    fn name(&self) -> &'static str {
        "Honest"
    }

    fn on_mining_block(
        &mut self,
        block: &Block,
        _current_time: i64,
        env: &Env,
        node_id: usize,
    ) -> Vec<Action> {
        let mut actions = Vec::new();
        let block_id = block.id();

        // 即座に propagation task をスケジュール（すべての他ノードに）
        for i in 0..env.num_nodes {
            if i != node_id {
                actions.push(Action::Propagate { block_id, to: i });
            }
        }

        // 次の mining task をスケジュール
        actions.push(Action::RestartMining {
            prev_block_id: block_id,
        });
        actions
    }

    fn on_receiving_block(
        &mut self,
        block: &Block,
        _current_time: i64,
        _env: &Env,
        _node_id: usize,
    ) -> Vec<Action> {
        vec![Action::RestartMining {
            prev_block_id: block.id(),
        }]
    }
}

// Selfish mining strategy
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelfishMiningStrategy;

impl MiningStrategy for SelfishMiningStrategy {
    fn name(&self) -> &'static str {
        "Selfish"
    }

    fn on_mining_block(
        &mut self,
        block: &Block,
        _current_time: i64,
        _env: &Env,
        _node_id: usize,
    ) -> Vec<Action> {
        // Mining block is always private.
        vec![Action::RestartMining {
            prev_block_id: block.id(),
        }]
    }

    fn on_receiving_block(
        &mut self,
        block: &Block,
        _current_time: i64,
        _env: &Env,
        _node_id: usize,
    ) -> Vec<Action> {
        let mut actions = Vec::new();

        // TODO: 公開制御を実装

        actions.push(Action::RestartMining {
            prev_block_id: block.id(),
        });
        actions
    }
}

/// マイニング戦略を enum で表現（シリアライズ/デシリアライズ可能）
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum MiningStrategyEnum {
    Honest,
    Selfish,
}

impl MiningStrategyEnum {
    /// enum から MiningStrategy トレイトオブジェクトを作成
    pub fn to_strategy(&self) -> Box<dyn MiningStrategy> {
        match self {
            MiningStrategyEnum::Honest => Box::new(HonestMiningStrategy),
            MiningStrategyEnum::Selfish => Box::new(SelfishMiningStrategy),
        }
    }
}
