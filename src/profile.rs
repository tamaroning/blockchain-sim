use crate::mining_strategy::{MiningStrategy, MiningStrategyEnum};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

/// A struct representing node configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeProfile {
    /// Hashrate
    pub hashrate: i64,
    /// Mining strategy
    pub strategy: MiningStrategyEnum,
}

/// Network profile (configuration for all nodes)
///
/// # Usage Example
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
///       "hashrate": 1500,
///       "strategy": {
///         "type": "selfish"
///       }
///     }
///   ]
/// }
/// ```
///
/// # Strategy Types and Parameters
///
/// - `honest`: No parameters.
/// - `selfish`: No parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkProfile {
    /// A list of node profiles.
    pub nodes: Vec<NodeProfile>,
}

impl NetworkProfile {
    /// Load profile from JSON file
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self, Box<dyn std::error::Error>> {
        let content = fs::read_to_string(path)?;
        let profile: NetworkProfile = serde_json::from_str(&content)?;
        Ok(profile)
    }

    /// Save profile to JSON file
    pub fn to_file<P: AsRef<Path>>(&self, path: P) -> Result<(), Box<dyn std::error::Error>> {
        let json = serde_json::to_string_pretty(self)?;
        fs::write(path, json)?;
        Ok(())
    }

    /// Create mining strategy for a node from profile
    pub fn create_strategy(
        &self,
        node_index: usize,
    ) -> Result<Box<dyn MiningStrategy>, Box<dyn std::error::Error>> {
        let node_profile = &self.nodes[node_index];
        Ok(node_profile.strategy.to_strategy())
    }

    /// Get the number of nodes
    pub fn num_nodes(&self) -> usize {
        self.nodes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_profile_serialization() {
        use crate::mining_strategy::MiningStrategyEnum;

        let profile = NetworkProfile {
            nodes: vec![
                NodeProfile {
                    hashrate: 1000,
                    strategy: MiningStrategyEnum::Honest,
                },
                NodeProfile {
                    hashrate: 2000,
                    strategy: MiningStrategyEnum::Selfish,
                },
            ],
        };

        let json = serde_json::to_string_pretty(&profile).unwrap();
        println!("{}", json);

        let deserialized: NetworkProfile = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.nodes.len(), 2);
        assert_eq!(deserialized.nodes[0].hashrate, 1000);
        assert_eq!(deserialized.nodes[1].hashrate, 2000);
        assert_eq!(deserialized.nodes[1].strategy, MiningStrategyEnum::Selfish);
    }
}
