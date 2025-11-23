use crate::types::{MiningStrategy, MiningStrategyEnum};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

/// ノードの設定を表す構造体
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeProfile {
    /// ハッシュレート
    pub hashrate: i64,
    /// マイニング戦略
    pub strategy: MiningStrategyEnum,
}

/// ネットワークプロファイル（全ノードの設定）
///
/// # 使用例
///
/// ```json
/// {
///   "nodes": [
///     {
///       "hashrate": 1000,
///       "strategy": {
///         "type": "honest"
///       }
///     },
///     {
///       "hashrate": 2000,
///       "strategy": {
///         "type": "pure_propagation_delay",
///         "propagation_delay": 10000
///       }
///     },
///     {
///       "hashrate": 1500,
///       "strategy": {
///         "type": "k_lead_selfish_mining",
///         "k": 2
///       }
///     }
///   ]
/// }
/// ```
///
/// # 戦略の種類とパラメータ
///
/// - `honest`: パラメータなし
/// - `pure_propagation_delay`: `propagation_delay` (i64) - 伝播遅延時間
/// - `simple_submission_postpone`: `postpone_time` (i64) - 公開を遅らせる時間
/// - `k_lead_selfish_mining`: `k` (i64) - リードを取る必要があるブロック数（デフォルト: 1）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkProfile {
    /// ノードの設定リスト（インデックスがノードIDに対応）
    pub nodes: Vec<NodeProfile>,
}

impl NetworkProfile {
    /// プロファイルをJSONファイルから読み込む
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self, Box<dyn std::error::Error>> {
        let content = fs::read_to_string(path)?;
        let profile: NetworkProfile = serde_json::from_str(&content)?;
        Ok(profile)
    }

    /// プロファイルをJSONファイルに保存する
    pub fn to_file<P: AsRef<Path>>(&self, path: P) -> Result<(), Box<dyn std::error::Error>> {
        let json = serde_json::to_string_pretty(self)?;
        fs::write(path, json)?;
        Ok(())
    }

    /// プロファイルからノードのマイニング戦略を作成する
    pub fn create_strategy(
        &self,
        node_index: usize,
    ) -> Result<Box<dyn MiningStrategy>, Box<dyn std::error::Error>> {
        let node_profile = &self.nodes[node_index];
        Ok(node_profile.strategy.to_strategy())
    }

    /// ノード数を取得
    pub fn num_nodes(&self) -> usize {
        self.nodes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_profile_serialization() {
        use crate::types::MiningStrategyEnum;

        let profile = NetworkProfile {
            nodes: vec![
                NodeProfile {
                    hashrate: 1000,
                    strategy: MiningStrategyEnum::Honest,
                },
                NodeProfile {
                    hashrate: 2000,
                    strategy: MiningStrategyEnum::KLeadSelfishMining { k: 2 },
                },
            ],
        };

        let json = serde_json::to_string_pretty(&profile).unwrap();
        println!("{}", json);

        let deserialized: NetworkProfile = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.nodes.len(), 2);
        assert_eq!(deserialized.nodes[0].hashrate, 1000);
        assert_eq!(deserialized.nodes[1].hashrate, 2000);
        assert_eq!(deserialized.nodes[1].strategy, MiningStrategyEnum::KLeadSelfishMining { k: 2 });
    }
}
