import argparse
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from rpa_platform.worker.diagnostics import build_diagnostic_summary
from rpa_platform.worker.machine_identity import load_or_create_machine_id


@dataclass(frozen=True)
class WorkerConfig:
    ws_url: str
    machine_token: str
    robot_id: str
    db_path: str
    machine_config: str
    log_path: str
    artifact_dir: str
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
        log_path=values.get("RPA_LOG_PATH", "C:/rpa_group/logs/worker.log"),
        artifact_dir=values.get("RPA_ARTIFACT_DIR", "C:/rpa_group/artifacts"),
        capabilities=[
            item.strip()
            for item in values.get("RPA_CAPABILITIES", "").split(",")
            if item.strip()
        ],
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Windows RPA WebSocket worker.")
    parser.add_argument("--env", required=True, help="Path to worker.env")
    parser.add_argument("--diagnose", action="store_true", help="Print a local redacted diagnostic summary and exit.")
    args = parser.parse_args(argv)
    config = load_worker_config(Path(args.env))
    if args.diagnose:
        machine_id = load_or_create_machine_id(Path(config.machine_config))
        summary = build_diagnostic_summary(
            machine_id=machine_id,
            robot_id=config.robot_id,
            task_id=None,
            mode="manual_debug",
            hostname=socket.gethostname(),
            session_name=os.environ.get("SESSIONNAME", "unknown"),
            interactive_desktop=bool(os.environ.get("SESSIONNAME")),
            screen_resolution="unknown",
            display_scaling="unknown",
            pid=os.getpid(),
            service_version="0.1.0",
            started_at=datetime.now().isoformat(),
            current_task_id=None,
            wss_connected=False,
            last_heartbeat_at=None,
            log_path=config.log_path,
            artifact_dir=config.artifact_dir,
            sqlite_path=config.db_path,
            recent_errors=[],
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("Loaded worker config for robot_id=%s ws_url=%s" % (config.robot_id, config.ws_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
