use blockchain_sim::{
    BlockchainSimulator, GenesisDifficultyMode, NetworkProfile, ProtocolType, node::NodeId,
};
use clap::Parser;
use rand::Rng;
use std::{
    collections::{HashMap, HashSet},
    path::PathBuf,
};

#[derive(Parser, Debug, Clone)]
struct Cli {
    /// The number of nodes.
    #[clap(short, long, default_value = "10")]
    num_nodes: usize,

    /// The seed for the random number generator.
    #[clap(short, long)]
    seed: Option<u64>,

    /// シミュレーションを続ける目標のメインチェーン高さ（完成済み・告知済みブロックのみ）。
    #[clap(long, default_value = "10")]
    end_round: i64,

    /// The delay time for block propagation in ms.
    #[clap(long, default_value = "600")]
    delay: i64,

    #[clap(long, value_enum, default_value_t = ProtocolType::Bitcoin)]
    protocol: ProtocolType,

    /// How to determine genesis difficulty: inferred from total hashrate or fixed preset.
    #[clap(long, value_enum, default_value_t = GenesisDifficultyMode::Inferred)]
    genesis_difficulty_mode: GenesisDifficultyMode,

    /// The path to the CSV file for outputting block timestamp and difficulty.
    #[clap(long, short)]
    output: Option<PathBuf>,

    /// The path to the CSV file for outputting mining fairness.
    output2: Option<PathBuf>,

    /// The path to the network profile file.
    /// See examples/honest.json for example.
    #[clap(long)]
    profile: Option<PathBuf>,

    /// Single-row CSV: mined_blocks, …, stale_rate, honest_mined_blocks, …, honest_stale_rate
    #[clap(long)]
    metrics: Option<PathBuf>,

    /// メトリクス集計の最小ブロック高さ（含む）。省略時は制限なし。
    #[clap(long)]
    metrics_min_height: Option<i64>,

    /// メトリクス集計の最大ブロック高さ（含む）。省略時は制限なし。
    #[clap(long)]
    metrics_max_height: Option<i64>,
}

fn main() {
    env_logger::init();

    if let Err(e) = run() {
        eprintln!("Error: {}", e);
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = Cli::parse();
    if args.seed.is_none() {
        args.seed = Some(rand::thread_rng().r#gen::<u64>());
    }

    let mut output = args
        .output
        .as_ref()
        .map(|path| csv::Writer::from_path(path).expect("Failed to create CSV writer"));

    let mut output2 = args
        .output2
        .as_ref()
        .map(|path| csv::Writer::from_path(path).expect("Failed to create CSV writer"));

    let mut simulator = if let Some(profile_path) = args.profile {
        // Load from profile
        let profile = NetworkProfile::from_file(&profile_path)
            .map_err(|e| {
                format!(
                    "Failed to load profile file '{}': {}\n\nPlease check the format of the profile file.\nExample: examples/profile-example.json",
                    profile_path.display(),
                    e
                )
            })?;
        log::info!("Loaded profile file '{}'", profile_path.display());
        log::info!("Number of nodes loaded: {}", profile.num_nodes());
        BlockchainSimulator::new_with_profile(
            profile,
            args.seed.unwrap(),
            args.end_round,
            args.delay,
            args.protocol.to_protocol(args.genesis_difficulty_mode),
        )
        .map_err(|e| format!("Failed to create simulator from profile: {}", e))?
    } else {
        BlockchainSimulator::new(
            args.num_nodes,
            args.seed.unwrap(),
            args.end_round,
            args.delay,
            args.protocol.to_protocol(args.genesis_difficulty_mode),
        )
    };

    simulator.print_hashrates();
    simulator.simulation();
    //simulator.print_blockchain();
    simulator.print_summary();
    simulator.print_mining_fairness();

    // Output mainchain blocks to CSV
    // round,difficulty,time
    if let Some(csv) = &mut output {
        for block in simulator.env.blockchain.get_main_chain() {
            let block = simulator.env.blockchain.get_block(block).unwrap();
            let record = blockchain_sim::types::Record {
                round: block.height() as u32,
                timestamp: block.time(),
                difficulty: block.difficulty().as_f64(),
                mining_time: block.mining_time,
                minter: block.minter(),
            };
            csv.serialize(&record).unwrap();
        }
    }

    if let Some(path) = args.metrics.as_ref() {
        let honest_minters: HashSet<NodeId> = simulator
            .nodes
            .nodes()
            .iter()
            .filter(|node| node.mining_strategy().is_honest())
            .map(|node| node.id)
            .collect();
        let m = simulator.env.blockchain.chain_metrics(
            Some(&honest_minters),
            args.metrics_min_height,
            args.metrics_max_height,
        );
        let mut csv = csv::Writer::from_path(path).expect("Failed to create metrics CSV writer");
        csv.serialize(&m).expect("Failed to serialize chain metrics");
        csv.flush().ok();
    }

    if let Some(csv) = &mut output2 {
        let total_hashrate = simulator
            .nodes
            .nodes()
            .iter()
            .map(|node| node.hashrate())
            .sum::<i64>();

        let main_chain: Vec<_> = simulator.env.blockchain.get_main_chain();

        let mut node_rewards = HashMap::<NodeId, usize>::new();
        main_chain.iter().for_each(|block_id| {
            let Some(block) = simulator.env.blockchain.get_block(*block_id) else {
                unreachable!();
            };
            let minter = block.minter();
            if minter != NodeId::dummy() {
                let node_id = minter;
                *node_rewards.entry(node_id).or_insert(0) += 1;
            }
        });

        let total_reward: usize = node_rewards.values().sum();

        for node in simulator.nodes.nodes() {
            let reward = *node_rewards.get(&node.id).unwrap_or(&0);
            let reward_share = if total_reward > 0 {
                reward as f64 / total_reward as f64
            } else {
                0.0
            };
            let hashrate_share = if total_hashrate > 0 {
                node.hashrate as f64 / total_hashrate as f64
            } else {
                0.0
            };
            let fairness = if hashrate_share > 0.0 {
                reward_share / hashrate_share
            } else {
                0.0
            };

            let record = blockchain_sim::types::NodeInfo {
                node_id: node.id.into_usize(),
                strategy: node.mining_strategy.name().to_string(),
                reward_share,
                hashrate_share,
                fairness,
            };
            csv.serialize(&record).unwrap();
        }
    }

    Ok(())
}
