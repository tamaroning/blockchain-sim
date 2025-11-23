use blockchain_sim::{BlockchainSimulator, NetworkProfile, ProtocolType, TieBreakingRule};
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

    /// ネットワークプロファイルファイルパス（指定すると、このプロファイルからノード構成を読み込む）
    #[clap(long)]
    profile: Option<PathBuf>,
}

fn main() {
    env_logger::init();

    if let Err(e) = run() {
        eprintln!("エラー: {}", e);
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = Cli::parse();
    if args.seed.is_none() {
        args.seed = Some(rand::thread_rng().r#gen::<u64>());
    }
    log::info!("args: {:?}", args);

    let output = args
        .output
        .map(|path| csv::Writer::from_path(path).expect("Failed to create CSV writer"));

    let mut simulator = if let Some(profile_path) = args.profile {
        // プロファイルから読み込む
        let profile = NetworkProfile::from_file(&profile_path)
            .map_err(|e| {
                format!(
                    "プロファイルファイル '{}' の読み込みに失敗しました: {}\n\nプロファイルファイルの形式を確認してください。\n例: examples/profile-example.json",
                    profile_path.display(),
                    e
                )
            })?;
        log::info!("プロファイルファイル '{}' を読み込みました", profile_path.display());
        log::info!("読み込んだノード数: {}", profile.num_nodes());
        BlockchainSimulator::new_with_profile(
            profile,
            args.seed.unwrap(),
            args.end_round,
            args.tie,
            args.delay,
            args.generation_time,
            args.protocol.to_protocol(),
            output,
        )
        .map_err(|e| format!("プロファイルからシミュレーターの作成に失敗しました: {}", e))?
    } else {
        // 従来通りランダムに生成
        BlockchainSimulator::new(
            args.num_nodes,
            args.seed.unwrap(),
            args.end_round,
            args.tie,
            args.delay,
            args.generation_time,
            args.protocol.to_protocol(),
            output,
        )
    };

    simulator.print_hashrates();
    simulator.simulation();
    //simulator.print_blockchain();
    simulator.print_summary();
    simulator.print_mining_fairness();
    Ok(())
}
