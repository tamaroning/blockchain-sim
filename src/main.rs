use blockchain_sim::{BlockchainSimulator, ProtocolType, TieBreakingRule};
use clap::Parser;
use rand::Rng;
use std::path::PathBuf;

#[derive(Parser, Debug, Clone)]
struct Cli {
    #[clap(short, long, default_value = "10")]
    num_nodes: usize,

    #[clap(short, long)]
    seed: Option<u64>,

    #[clap(long, default_value = "10")]
    end_round: i64,

    #[clap(long, value_enum, default_value_t = TieBreakingRule::Longest)]
    #[arg(value_enum)]
    tie: TieBreakingRule,

    #[clap(long, default_value = "6000")]
    delay: i64, // ブロック伝播時間

    #[clap(long, default_value = "600000")]
    generation_time: i64, // ブロック生成時間

    #[clap(long, value_enum, default_value_t = ProtocolType::Bitcoin)]
    protocol: ProtocolType,

    /// CSV出力ファイルパス
    #[clap(long, short)]
    output: Option<PathBuf>,
}

fn main() {
    env_logger::init();

    let mut args = Cli::parse();
    if args.seed.is_none() {
        args.seed = Some(rand::thread_rng().r#gen::<u64>());
    }
    log::info!("args: {:?}", args);

    let output = args
        .output
        .map(|path| csv::Writer::from_path(path).expect("Failed to create CSV writer"));

    let mut simulator = BlockchainSimulator::new(
        args.num_nodes,
        args.seed.unwrap(),
        args.end_round,
        args.tie,
        args.delay,
        args.generation_time,
        args.protocol.to_protocol(),
        output,
    );

    simulator.print_hashrates();
    simulator.simulation();
    //simulator.print_blockchain();
    simulator.print_summary();
    simulator.print_mining_fairness();
}
