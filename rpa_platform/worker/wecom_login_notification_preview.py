import argparse
import json
import sys
from typing import List, Optional

from rpa_platform.worker.wecom_login_recovery import build_wecom_qr_login_markdown_payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a local UTF-8 WeCom login notification preview without sending webhook requests."
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--enterprise-name", required=True)
    parser.add_argument("--expires-at", required=True, type=float)
    args = parser.parse_args(argv)

    payload = build_wecom_qr_login_markdown_payload(
        expires_at=args.expires_at,
        context={
            "task_id": args.task_id,
            "enterprise_name": args.enterprise_name,
        },
    )
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
