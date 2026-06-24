import sys
from pathlib import Path
from typing import List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rpa_platform.worker.dingtalk_group_handoff_batch import main as batch_main


def main(argv: Optional[List[str]] = None) -> int:
    return batch_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
