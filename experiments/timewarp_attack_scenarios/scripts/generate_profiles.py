from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = next(
    candidate for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents] if (candidate / "Cargo.toml").exists()
)
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import write_profile_json

SCENARIO_DIR = SCRIPT_PATH.parents[1]
PROFILES_DIR = SCENARIO_DIR / "profiles"
TOTAL_HASHRATE = 1_000_000_000_000

# ファイル名（timewarp*.json の *）→ 攻撃側 timewarp のハッシュレート。
# timewarp50 は歴史的に 60/40 の内容のまま（ファイル名と数値が一致しない）。
_TIMWARP_ATTACKER_BY_STEM: dict[int, int] = {
    50: 60,
    60: 60,
    70: 70,
    80: 80,
    85: 85,
    90: 90,
    95: 95,
    100: 100,
}


def _percent_hashrate(percent: int) -> int:
    return (TOTAL_HASHRATE * percent) // 100


def _timewarp_profile(attacker_hashrate: int) -> dict:
    if attacker_hashrate == 100:
        return {
            "nodes": [
                {"hashrate": TOTAL_HASHRATE, "strategy": {"type": "timewarp"}},
            ]
        }
    attacker = _percent_hashrate(attacker_hashrate)
    honest = TOTAL_HASHRATE - attacker
    return {
        "nodes": [
            {"hashrate": attacker, "strategy": {"type": "timewarp"}},
            {"hashrate": honest, "strategy": {"type": "honest"}},
        ]
    }


def generate_all() -> list[Path]:
    written: list[Path] = []

    written.append(
        write_profile_json(
            {
                "nodes": [
                    {"hashrate": _percent_hashrate(50), "strategy": {"type": "honest"}},
                    {"hashrate": TOTAL_HASHRATE - _percent_hashrate(50), "strategy": {"type": "honest"}},
                ]
            },
            PROFILES_DIR / "honest.json",
        )
    )

    written.append(
        write_profile_json(
            {"nodes": [{"hashrate": TOTAL_HASHRATE, "strategy": {"type": "timewarp"}}]},
            PROFILES_DIR / "test.json",
        )
    )

    written.append(
        write_profile_json(
            {
                "nodes": [
                    {"hashrate": _percent_hashrate(49), "strategy": {"type": "selfish_timewarp"}},
                    {"hashrate": TOTAL_HASHRATE - _percent_hashrate(49), "strategy": {"type": "honest"}},
                ]
            },
            PROFILES_DIR / "selfish_timewarp.json",
        )
    )

    for stem, attacker in sorted(_TIMWARP_ATTACKER_BY_STEM.items()):
        written.append(
            write_profile_json(
                _timewarp_profile(attacker),
                PROFILES_DIR / f"timewarp{stem}.json",
            )
        )

    return written


def main() -> None:
    paths = generate_all()
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
