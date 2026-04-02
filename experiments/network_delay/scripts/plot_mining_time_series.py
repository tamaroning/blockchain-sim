import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLOTS_DIR = BASE_DIR / "results" / "plots"


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Blockchain data visualization")
    parser.add_argument(
        "csv_file",
        help="Path to CSV file (e.g. experiments/network_delay/results/data/bitcoin-0.1.csv)",
    )
    parser.add_argument(
        "--window",
        "-w",
        type=int,
        default=1000,
        help="Moving average window size (default: 1000)",
    )
    parser.add_argument(
        "--log-scale",
        "-l",
        action="store_true",
        help="Display mining time in log scale",
    )
    parser.add_argument(
        "--output",
        "-o",
        action="store",
        default="mining_time_difficulty.png",
        help="Output file path for the plot",
    )

    args = parser.parse_args()

    # Read CSV file
    try:
        df = pd.read_csv(args.csv_file)
    except FileNotFoundError:
        print(f"Error: File '{args.csv_file}' not found.")
        return
    except Exception as e:
        print(f"Error: Failed to read CSV file: {e}")
        return

    # Remove duplicate rows (in case round 13 is duplicated)
    df = df.drop_duplicates(subset=["round"])

    # Sort by round
    df = df.sort_values("round")

    # Convert mining time from ms to seconds
    df["mining_time_sec"] = df["mining_time"] / 1000

    # Calculate moving average in seconds
    window_size = args.window
    df["mining_time_ma"] = (
        df["mining_time_sec"].rolling(window=window_size, min_periods=1).mean()
    )

    # Plot setup - single plot with dual y-axes
    fig, ax1 = plt.subplots(figsize=(12, 8))

    # Left y-axis: Mining time (moving average)
    color1 = "tab:red"
    ax1.set_xlabel("Round (Time)")
    ax1.set_ylabel("Mining Time (sec)", color=color1)
    line1 = ax1.plot(
        df["round"],
        df["mining_time_ma"],
        color=color1,
        linewidth=2,
        label=f"Mining Time ({window_size}-block MA)",
    )
    ax1.tick_params(axis="y", labelcolor=color1)

    # Prevent scientific notation on y-axis
    from matplotlib.ticker import ScalarFormatter

    ax1.yaxis.set_major_formatter(ScalarFormatter())
    ax1.ticklabel_format(style="plain", axis="y")

    # Apply log scale if requested
    if args.log_scale:
        ax1.set_yscale("log")
        ax1.set_ylabel("Mining Time (sec) - Log Scale", color=color1)

    # Right y-axis: Difficulty
    ax2 = ax1.twinx()
    color2 = "tab:blue"
    ax2.set_ylabel("Difficulty", color=color2)
    line2 = ax2.plot(
        df["round"], df["difficulty"], color=color2, linewidth=2, label="Difficulty"
    )
    ax2.tick_params(axis="y", labelcolor=color2)
    ax2.set_ylim(bottom=0.0)

    # Title and grid
    plt.title("Blockchain Mining Time and Difficulty Over Time")
    ax1.grid(True, alpha=0.3)

    # Combined legend
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left")

    # Layout adjustment
    plt.tight_layout()

    # Save the plot
    csv_path = Path(args.csv_file)
    output_file = args.output
    if output_file == "mining_time_difficulty.png":
        output_file = PLOTS_DIR / f"mining_time_difficulty_{csv_path.stem}.png"
    else:
        output_file = Path(output_file)
        if not output_file.is_absolute():
            output_file = PLOTS_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    print(f"Plot saved to {output_file}")

    # Show the plot
    plt.show()

    # Display statistics
    print("=== Data Statistics ===")
    print(f"CSV file: {args.csv_file}")
    print(f"Total blocks: {len(df)}")
    print(f"Average difficulty: {df['difficulty'].mean():.2f}")
    print(f"Average mining time: {df['mining_time_sec'].mean():.3f} sec")
    print(f"Mining time std deviation: {df['mining_time_sec'].std():.3f} sec")
    print(f"Moving average window size: {window_size}")

    # Display first few rows
    print("\n=== Data Sample ===")
    print(df.head(10))


if __name__ == "__main__":
    main()
