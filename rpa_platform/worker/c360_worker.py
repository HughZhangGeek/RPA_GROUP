import argparse
import asyncio
import os
import sys
from typing import List, Mapping, Optional

from rpa_platform.worker.c360_worker_client import (
    C360WorkerConfigError,
    build_default_diagnostics,
    load_c360_worker_config_from_env,
)
from rpa_platform.worker.c360_task_handlers import build_c360_task_handlers
from rpa_platform.worker.c360_worker_runtime import (
    C360WorkerRuntime,
    HttpWorkerMessageReporter,
    connect_json_transport,
)
from rpa_platform.worker.diagnostics import _redact_string


def main(argv: Optional[List[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RPA_GROUP worker against the CSM_C360 control plane.")
    parser.add_argument("--once", action="store_true", help="Run one WebSocket connection cycle and exit.")
    parser.add_argument("--verbose", action="store_true", help="Print redacted local lifecycle events to stdout.")
    parser.add_argument(
        "--reconnect-delay-seconds",
        type=float,
        default=None,
        help="Seconds to wait before reconnecting in persistent mode.",
    )
    args = parser.parse_args(argv)
    try:
        config = load_c360_worker_config_from_env(env)
    except C360WorkerConfigError as exc:
        print("blocked: %s" % exc, file=sys.stderr)
        return 2
    try:
        reconnect_delay_seconds = (
            args.reconnect_delay_seconds
            if args.reconnect_delay_seconds is not None
            else _reconnect_delay_seconds_from_env(env)
        )
    except ValueError as exc:
        print("blocked: %s" % exc, file=sys.stderr)
        return 2
    event_logger = _print_event if args.verbose else None
    try:
        if args.once:
            asyncio.run(_run(config, event_logger=event_logger))
        else:
            asyncio.run(
                _run_forever(
                    config,
                    event_logger=event_logger,
                    reconnect_delay_seconds=reconnect_delay_seconds,
                )
            )
    except Exception as exc:
        print("worker failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


async def _run(config, event_logger=None) -> None:
    diagnostics = build_default_diagnostics(config)
    if event_logger is not None:
        event_logger("worker connecting worker_id=%s ws_url=%s simulate=%s" % (config.worker_id, config.ws_url, config.simulate))
    transport = await connect_json_transport(config)
    try:
        runtime = C360WorkerRuntime(
            config=config,
            transport=transport,
            handlers=build_c360_task_handlers(config, diagnostics),
            diagnostics=diagnostics,
            event_logger=event_logger,
            message_reporter=HttpWorkerMessageReporter(config),
        )
        await runtime.run_until_idle()
    finally:
        close = getattr(transport, "close", None)
        if close is not None:
            await close()


async def _run_forever(
    config,
    event_logger=None,
    reconnect_delay_seconds: float = 5.0,
    sleep=asyncio.sleep,
    run_once=None,
) -> None:
    runner = run_once or _run
    while True:
        try:
            await runner(config, event_logger=event_logger)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if event_logger is not None:
                event_logger("worker cycle failed: %s" % _redact_string(str(exc)))
        if event_logger is not None:
            event_logger("worker reconnecting in %ss" % _format_seconds(reconnect_delay_seconds))
        await sleep(reconnect_delay_seconds)


def _reconnect_delay_seconds_from_env(env: Optional[Mapping[str, str]] = None) -> float:
    source = env if env is not None else os.environ
    raw = source.get("RPA_WORKER_RECONNECT_DELAY_SECONDS", "5")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("RPA_WORKER_RECONNECT_DELAY_SECONDS must be a number") from exc
    if value < 0:
        raise ValueError("RPA_WORKER_RECONNECT_DELAY_SECONDS must be non-negative")
    return value


def _format_seconds(value: float) -> str:
    return "%g" % value


def _print_event(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
