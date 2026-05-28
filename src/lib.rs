pub mod block;
pub mod blockchain;
pub mod event;
pub mod event_queue;
pub mod mining_strategy;
pub mod node;
pub mod profile;
pub mod propagation_delay;
pub mod protocol;
pub mod simulator;
pub mod types;

/// Private-chain attack: 一斉公開に必要な高さリード（公開鎖 tip より何ブロック先か）。
/// honest / 攻撃者が並行して鎖を伸ばし、リードがこの値に達したら公開する（50% ハッシュレートとは無関係）。
pub const PRIVATE_ATTACK_MIN_REORG_BLOCKS: i64 = 50;

pub use block::Block;
pub use blockchain::Blockchain;
pub use event::{Event, EventType};
pub use mining_strategy::{
    HonestMiningStrategy, MiningStrategy, MiningStrategyEnum, PrivateAttackMiningStrategy,
    SelfishMiningStrategy,
};
pub use node::Node;
pub use profile::{NetworkProfile, NodeProfile};
pub use propagation_delay::PropagationDelayMode;
pub use protocol::{GenesisDifficultyMode, Protocol, ProtocolType};
pub use simulator::BlockchainSimulator;
pub use types::{ChainMetrics, Record};
