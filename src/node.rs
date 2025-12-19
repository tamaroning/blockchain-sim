use crate::mining_strategy::MiningStrategy;

#[derive(Clone, Copy, Debug, Hash, Eq, PartialEq)]
pub struct NodeId(usize);

impl NodeId {
    pub const fn new(id: usize) -> Self {
        Self(id)
    }

    pub fn into_usize(self) -> usize {
        self.0
    }

    pub fn dummy() -> Self {
        Self(usize::MAX)
    }
}

impl std::fmt::Display for NodeId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// A miner in the network.
pub struct Node {
    /// The ID of the node.
    pub id: NodeId,
    /// The hashrate of the node.
    pub hashrate: i64,
    pub mining_strategy: Box<dyn MiningStrategy>,
}

impl Node {
    pub fn new(id: NodeId, hashrate: i64) -> Self {
        Self::new_with_strategy(
            id,
            hashrate,
            Box::new(crate::mining_strategy::HonestMiningStrategy::default()),
        )
    }

    pub fn new_with_strategy(
        id: NodeId,
        hashrate: i64,
        mining_strategy: Box<dyn MiningStrategy>,
    ) -> Self {
        Self {
            id,
            hashrate,
            mining_strategy,
        }
    }

    pub fn id(&self) -> NodeId {
        self.id
    }

    pub fn hashrate(&self) -> i64 {
        self.hashrate
    }

    pub fn mining_strategy(&self) -> &dyn MiningStrategy {
        self.mining_strategy.as_ref()
    }

    pub fn mining_strategy_mut(&mut self) -> &mut dyn MiningStrategy {
        self.mining_strategy.as_mut()
    }
}

pub struct NodeList {
    nodes: Vec<Node>,
}

impl NodeList {
    pub fn new(nodes: Vec<Node>) -> Self {
        Self { nodes }
    }

    pub fn nodes(&self) -> &[Node] {
        &self.nodes
    }

    pub fn nodes_mut(&mut self) -> &mut [Node] {
        &mut self.nodes
    }

    pub fn get_node(&self, id: NodeId) -> &Node {
        &self.nodes[id.into_usize()]
    }

    pub fn get_node_mut(&mut self, id: NodeId) -> &mut Node {
        &mut self.nodes[id.into_usize()]
    }
}
