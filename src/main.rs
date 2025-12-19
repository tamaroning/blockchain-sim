use blockchain_sim::{BlockchainSimulator, NetworkProfile, ProtocolType, node::NodeId};
use clap::Parser;
use rand::Rng;
use std::{collections::HashMap, path::PathBuf};

#[derive(Parser, Debug, Clone)]
struct Cli {
    /// The number of nodes.
    #[clap(short, long, default_value = "10")]
    num_nodes: usize,

    /// The seed for the random number generator.
    #[clap(short, long)]
    seed: Option<u64>,

    /// The maximum round (block height) to simulate.
    #[clap(long, default_value = "10")]
    end_round: i64,

    /// The delay time for block propagation in ms.
    #[clap(long, default_value = "600")]
    delay: i64,

    #[clap(long, value_enum, default_value_t = ProtocolType::Bitcoin)]
    protocol: ProtocolType,

    /// The path to the CSV file for outputting block timestamp and difficulty.
    #[clap(long, short)]
    output: Option<PathBuf>,

    /// The path to the CSV file for outputting mining fairness.
    output2: Option<PathBuf>,

    /// The path to the network profile file.
    /// See examples/honest.json for example.
    #[clap(long)]
    profile: Option<PathBuf>,
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
            args.protocol.to_protocol(),
        )
        .map_err(|e| format!("Failed to create simulator from profile: {}", e))?
    } else {
        BlockchainSimulator::new(
            args.num_nodes,
            args.seed.unwrap(),
            args.end_round,
            args.delay,
            args.protocol.to_protocol(),
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
                difficulty: block.difficulty(),
                mining_time: block.mining_time,
            };
            csv.serialize(&record).unwrap();
        }
    }

    if let Some(csv) = &mut output2 {
        let total_hashrate = simulator
            .nodes
            .nodes()
            .iter()
            .map(|node| node.hashrate())
            .sum::<i64>();
        let total_blocks = simulator.env.blockchain.len();

        let mut node_rewards = HashMap::<NodeId, usize>::new();
        simulator
            .env
            .blockchain
            .get_main_chain()
            .iter()
            .for_each(|block_id| {
                let Some(block) = simulator.env.blockchain.get_block(*block_id) else {
                    unreachable!();
                };
                let minter = block.minter();
                if minter != NodeId::dummy() {
                    let node_id = minter;
                    *node_rewards.entry(node_id).or_insert(0) += 1;
                }
            });

        for node in simulator.nodes.nodes() {
            let reward_share = node_rewards[&node.id] as f64 / total_blocks as f64;
            let hashrate_share = node.hashrate as f64 / total_hashrate as f64;
            let fairness = reward_share / hashrate_share;

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
