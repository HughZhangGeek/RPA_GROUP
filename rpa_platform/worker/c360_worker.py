import argparse
import asyncio
import sys
from typing import List, Mapping, Optional

from rpa_platform.worker.c360_worker_client import (
    C360WorkerConfigError,
    build_default_diagnostics,
    load_c360_worker_config_from_env,
)
from rpa_platform.worker.c360_task_handlers import build_c360_task_handlers
from rpa_platform.worker.c360_worker_runtime import C360WorkerRuntime, connect_json_transport


def main(argv: Optional[List[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RPA_GROUP worker against the CSM_C360 control plane.")
    parser.add_argument("--once", action="store_true", help="Run until the WebSocket closes or the fake transport is idle.")
    parser.add_argument("--verbose", action="store_true", help="Print redacted local lifecycle events to stdout.")
    args = parser.parse_args(argv)
    try:
        config = load_c360_worker_config_from_env(env)
    except C360WorkerConfigError as exc:
        print("blocked: %s" % exc, file=sys.stderr)
        return 2
    event_logger = _print_event if args.verbose else None
    try:
        asyncio.run(_run(config, event_logger=event_logger))
    except Exception as exc:
        print("worker failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


async def _run(config, event_logger=None) -> None:
    diagnostics = build_default_diagnostics(config)
    if event_logger is not None:
        event_logger("worker connecting worker_id=%s ws_url=%s simulate=%s" % (config.worker_id, config.ws_url, config.simulate))
    transport = await connect_json_transport(config)
    runtime = C360WorkerRuntime(
        config=config,
        transport=transport,
        handlers=build_c360_task_handlers(config, diagnostics),
        diagnostics=diagnostics,
        event_logger=event_logger,
    )
    await runtime.run_until_idle()


def _print_event(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
