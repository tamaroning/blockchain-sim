from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def find_project_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "Cargo.toml").exists():
            return candidate
    raise FileNotFoundError("Cargo.toml が見つからないため、リポジトリルートを特定できません。")


def run_cargo_build_release(project_root: Path) -> None:
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "cargo build --release の実行に失敗しました\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
        )


def ensure_release_binary(
    start: Path,
    *,
    binary_name: str = "blockchain-sim",
    auto_build: bool = False,
) -> Path:
    project_root = find_project_root(start)
    binary_path = project_root / "target" / "release" / binary_name

    if binary_path.exists():
        return binary_path

    if auto_build:
        run_cargo_build_release(project_root)

    if not binary_path.exists():
        raise FileNotFoundError(
            f"{binary_name} バイナリが見つかりません: {binary_path}\n"
            "先に `cargo build --release` を実行してください。"
        )
    return binary_path


def write_profile_json(profile: dict[str, Any], profile_path: Path) -> Path:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with profile_path.open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    return profile_path
