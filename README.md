# Blockchain Simulator

A simulator for Proof-of-Work based blockchain such as Bitcoin and Ethereum (version 1.0).


Network topology:
- Complete graph
- Constant network delay


k-lead selfish mining
```bash
# Run Ethereum protocol with 100 nodes for 10,000 rounds
RUST_LOG="info" cargo run --release -- --end-round 10000 --protocol ethereum --num-nodes 100

# Single k-lead selfish miner with 30% hash power
RUST_LOG="info" cargo run --release -- --profile ../examples/single_attacker_30pct.json --end-round 1000000
```

Evaluation:

```bash
cd experiment

# Run simulations
cargo build --release
uv run main.py --protocol=ethereum
uv run main.py --protocol=bitcoin

# Plot difficulty over time
uv run plot-difficulty.py --protocol=ethereum
uv run plot-difficulty.py --protocol=bitcoin

# Plot block generation time and difficulty over time
uv run plot-time.py data/bitcoin-0.001.csv
uv run plot-time.py data/bitcoin-0.01.csv
uv run plot-time.py data/bitcoin-0.1.csv
uv run plot-time.py data/bitcoin-0.5.csv
uv run plot-time.py data/ethereum-0.001.csv
uv run plot-time.py data/ethereum-0.01.csv
uv run plot-time.py data/ethereum-0.1.csv
uv run plot-time.py data/ethereum-0.5.csv
```

