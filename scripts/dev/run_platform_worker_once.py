import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.dev.run_platform_dryrun import run_worker_once


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Claim and execute one fake RPA platform task locally.")
    parser.add_argument("--db-path", default=None, help="SQLite path. Defaults to .local/platform-dryrun.db.")
    parser.add_argument("--robot-id", default=None, help="Robot id. Defaults to the first robot in the DB.")
    args = parser.parse_args(argv)

    result = run_worker_once(db_path=args.db_path, robot_id=args.robot_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
