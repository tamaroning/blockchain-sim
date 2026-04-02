from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def _run_command(command: list[str], cwd: Path, rust_log: str) -> None:
    env = os.environ.copy()
    env["RUST_LOG"] = rust_log
    print(f"$ RUST_LOG={rust_log} {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _run_commands_in_parallel(
    *, commands: list[list[str]], cwd: Path, rust_log: str
) -> None:
    env = os.environ.copy()
    env["RUST_LOG"] = rust_log

    processes: list[subprocess.Popen] = []
    try:
        for command in commands:
            print(f"$ RUST_LOG={rust_log} {' '.join(command)}")
            processes.append(subprocess.Popen(command, cwd=cwd, env=env))

        failed_returncodes: list[int] = []
        for proc in processes:
            rc = proc.wait()
            if rc != 0:
                failed_returncodes.append(rc)

        if failed_returncodes:
            raise subprocess.CalledProcessError(
                returncode=failed_returncodes[0],
                cmd="parallel cargo runs",
            )
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()


def _build_cargo_command(
    *,
    project_root: Path,
    end_round: int,
    profile: str,
    output: str | None,
) -> list[str]:
    command = [
        "cargo",
        "run",
        "--release",
        "--manifest-path",
        str(project_root / "Cargo.toml"),
        "--",
        "--end-round",
        str(end_round),
        "--protocol",
        "bitcoin",
        "--profile",
        profile,
    ]
    if output:
        command.extend(["--output", output])
    return command


def run_full(*, scenario_dir: Path, project_root: Path, end_round: int, with_plot: bool) -> None:
    _run_command(
        ["python", "scripts/generate_profiles.py"],
        cwd=scenario_dir,
        rust_log="warn",
    )

    commands = [
        _build_cargo_command(
            project_root=project_root,
            end_round=end_round,
            profile="profiles/honest.json",
            output="results/honest.csv",
        ),
        _build_cargo_command(
            project_root=project_root,
            end_round=end_round,
            profile="profiles/selfish_timewarp.json",
            output="results/selfish_timewarp.csv",
        ),
    ]
    for tw_hash in (85, 90, 100):
        commands.append(
            _build_cargo_command(
                project_root=project_root,
                end_round=end_round,
                profile=f"profiles/timewarp{tw_hash}.json",
                output=f"results/timewarp{tw_hash}.csv",
            )
        )
    _run_commands_in_parallel(commands=commands, cwd=scenario_dir, rust_log="warn")

    if with_plot:
        _run_command(
            ["python", "scripts/plot_timewarp_scenarios.py"],
            cwd=scenario_dir,
            rust_log="warn",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="timewarp 実験のシミュレータ実行をまとめて行うスクリプト"
    )
    parser.add_argument(
        "--end-round",
        type=int,
        default=100000,
        help="シミュレーション終了ラウンド",
    )
    parser.add_argument(
        "--with-plot",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="シミュレーション終了後に difficulty グラフを生成するか",
    )
    return parser


def main() -> None:
    script_path = Path(__file__).resolve()
    scenario_dir = script_path.parents[1]
    project_root = script_path.parents[3]
    args = build_parser().parse_args()

    run_full(
        scenario_dir=scenario_dir,
        project_root=project_root,
        end_round=args.end_round,
        with_plot=args.with_plot,
    )


if __name__ == "__main__":
    main()
