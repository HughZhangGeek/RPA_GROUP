import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class WorkerConfig:
    ws_url: str
    machine_token: str
    robot_id: str
    db_path: str
    machine_config: str
    capabilities: List[str]


def _read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_worker_config(path: Path) -> WorkerConfig:
    values = _read_env_file(path)
    return WorkerConfig(
        ws_url=values["RPA_WS_URL"],
        machine_token=values["RPA_MACHINE_TOKEN"],
        robot_id=values["RPA_ROBOT_ID"],
        db_path=values["RPA_DB_PATH"],
        machine_config=values.get("RPA_MACHINE_CONFIG", "C:/rpa_group/config/machine.json"),
        capabilities=[
            item.strip()
            for item in values.get("RPA_CAPABILITIES", "").split(",")
            if item.strip()
        ],
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Windows RPA WebSocket worker.")
    parser.add_argument("--env", required=True, help="Path to worker.env")
    args = parser.parse_args(argv)
    config = load_worker_config(Path(args.env))
    print("Loaded worker config for robot_id=%s ws_url=%s" % (config.robot_id, config.ws_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
