import argparse
import asyncio
import sys
from typing import List, Mapping, Optional

from rpa_platform.worker.c360_worker_client import (
    C360WorkerConfigError,
    build_default_diagnostics,
    load_c360_worker_config_from_env,
)
from rpa_platform.worker.c360_worker_runtime import C360WorkerRuntime, connect_json_transport
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


def main(argv: Optional[List[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RPA_GROUP worker against the CSM_C360 control plane.")
    parser.add_argument("--once", action="store_true", help="Run until the WebSocket closes or the fake transport is idle.")
    parser.parse_args(argv)
    try:
        config = load_c360_worker_config_from_env(env)
    except C360WorkerConfigError as exc:
        print("blocked: %s" % exc, file=sys.stderr)
        return 2
    try:
        asyncio.run(_run(config))
    except Exception as exc:
        print("worker failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


async def _run(config) -> None:
    diagnostics = build_default_diagnostics(config)
    transport = await connect_json_transport(config)
    runtime = C360WorkerRuntime(
        config=config,
        transport=transport,
        handlers=SimulatedTaskHandlers(diagnostics),
        diagnostics=diagnostics,
    )
    await runtime.run_until_idle()


if __name__ == "__main__":
    raise SystemExit(main())
