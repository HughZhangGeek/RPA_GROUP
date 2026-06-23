import asyncio
import unittest
from unittest.mock import patch

from rpa_platform.worker.c360_worker_client import load_c360_worker_config_from_env
from rpa_platform.worker import c360_worker
from rpa_platform.worker.c360_worker_runtime import AioHttpJsonTransport, C360WorkerRuntime, WorkerTaskResult
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


class FakeTransport:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if not self.incoming:
            return None
        return self.incoming.pop(0)


class C360WorkerRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def _config(self, simulate=True):
        return load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "http://127.0.0.1:3601",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-sim-001",
                "RPA_WORKER_SIMULATE": "true" if simulate else "false",
            }
        )

    async def test_connect_sends_hello_then_completes_supported_dispatch(self):
        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-001",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "idempotency_key": "idem-001",
                    "simulate": True,
                    "payload": {
                        "task_type": "wecom_bind_service",
                        "enterprise_name": "zh_test_模拟客户",
                        "plain_corp_id": "ww_test",
                    },
                },
            ]
        )
        runtime = C360WorkerRuntime(
            config=self._config(),
            transport=transport,
            handlers=SimulatedTaskHandlers(
                diagnostics={
                    "machine_id": "win-sim-001",
                    "interactive_desktop": True,
                    "session_name": "console",
                    "resolution": "1920x1080",
                    "dpi_scale": "100%",
                }
            ),
        )

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[0]["type"], "worker.hello")
        self.assertEqual([item["type"] for item in transport.sent[1:]], ["task.accepted", "task.progress", "task.completed"])
        self.assertEqual(transport.sent[1]["task_id"], "task-001")
        self.assertEqual(transport.sent[2]["status"], "running")
        self.assertEqual(transport.sent[3]["status"], "succeeded")
        self.assertEqual(transport.sent[3]["result"], {"simulated": True, "handler": "wecom_bind_service"})

    async def test_unknown_task_type_fails_without_crashing(self):
        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-unknown",
                    "task_type": "unsupported",
                    "route_key": "unsupported",
                    "simulate": True,
                    "payload": {},
                },
            ]
        )
        runtime = C360WorkerRuntime(config=self._config(), transport=transport, handlers=SimulatedTaskHandlers({}))

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-1]["type"], "task.completed")
        self.assertEqual(transport.sent[-1]["status"], "failed")
        self.assertIn("Unsupported task_type", transport.sent[-1]["error_message"])
        self.assertNotIn("secret-token", str(transport.sent))

    async def test_handler_exception_is_reported_as_failed_with_redacted_message(self):
        class ExplodingHandlers(SimulatedTaskHandlers):
            async def handle(self, dispatch):
                raise RuntimeError("Authorization: Bearer secret-value")

        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-failed",
                    "task_type": "runtime_health_check",
                    "route_key": "runtime_health_check",
                    "simulate": True,
                    "payload": {},
                },
            ]
        )
        runtime = C360WorkerRuntime(config=self._config(), transport=transport, handlers=ExplodingHandlers({}))

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-1]["status"], "failed")
        self.assertIn("Bearer [REDACTED]", transport.sent[-1]["error_message"])
        self.assertNotIn("secret-value", str(transport.sent))

    async def test_handler_can_report_waiting_login_without_marking_task_succeeded(self):
        class WaitingLoginHandlers(SimulatedTaskHandlers):
            async def handle(self, dispatch):
                return WorkerTaskResult(
                    status="manual_action_required",
                    result={
                        "reason": "wecom_session_expired",
                        "manual_action": "scan_wecom_admin_qr",
                    },
                    progress=[
                        {
                            "status": "waiting_login",
                            "message": "wecom admin QR notification sent",
                        }
                    ],
                )

        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-login",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "simulate": False,
                    "payload": {"task_type": "wecom_bind_service"},
                },
            ]
        )
        runtime = C360WorkerRuntime(config=self._config(), transport=transport, handlers=WaitingLoginHandlers({}))

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-2]["type"], "task.progress")
        self.assertEqual(transport.sent[-2]["status"], "waiting_login")
        self.assertEqual(transport.sent[-1]["type"], "task.completed")
        self.assertEqual(transport.sent[-1]["status"], "succeeded")
        self.assertEqual(transport.sent[-1]["result"]["manual_action"], "scan_wecom_admin_qr")

    async def test_non_simulate_wecom_handler_progress_is_sent_before_completed(self):
        class RealReadonlyHandlers:
            async def handle(self, dispatch):
                return WorkerTaskResult(
                    status="ready_for_real_bind",
                    result={"status": "ready_for_real_bind", "reason": "ready_for_confirm_write"},
                    progress=[
                        {"status": "readonly_preflight_started", "message": "wecom bind readonly preflight started"},
                        {
                            "status": "readonly_preflight_completed",
                            "message": "wecom bind readonly preflight completed",
                            "queue_control": {"action": "resume", "scope": "wecom_bind_service"},
                        },
                    ],
                )

        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-server-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-real",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "simulate": False,
                    "payload": {"task_type": "wecom_bind_service", "enterprise_name": "zh_test_上海测试客户"},
                },
            ]
        )

        runtime = C360WorkerRuntime(config=self._config(simulate=False), transport=transport, handlers=RealReadonlyHandlers())

        await runtime.run_until_idle()

        sent_after_hello = transport.sent[1:]
        self.assertEqual(
            [item["type"] for item in sent_after_hello],
            [
                "task.accepted",
                "task.progress",
                "task.progress",
                "task.progress",
                "task.completed",
            ],
        )
        self.assertEqual(sent_after_hello[2]["status"], "readonly_preflight_started")
        self.assertEqual(sent_after_hello[3]["status"], "readonly_preflight_completed")
        self.assertEqual(sent_after_hello[-1]["status"], "succeeded")
        self.assertEqual(sent_after_hello[-1]["result"]["status"], "ready_for_real_bind")

    async def test_worker_task_result_blocked_is_reported_as_failed_with_domain_status_in_result(self):
        class BlockedHandlers:
            async def handle(self, dispatch):
                return WorkerTaskResult(
                    status="blocked",
                    result={"status": "blocked", "reason": "missing_required_bind_context"},
                    progress=[{"status": "blocked", "message": "wecom bind readonly preflight completed"}],
                )

        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-server-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-blocked",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "simulate": False,
                    "payload": {"task_type": "wecom_bind_service"},
                },
            ]
        )

        runtime = C360WorkerRuntime(config=self._config(simulate=False), transport=transport, handlers=BlockedHandlers())

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-1]["type"], "task.completed")
        self.assertEqual(transport.sent[-1]["status"], "failed")
        self.assertEqual(transport.sent[-1]["result"]["status"], "blocked")
        self.assertEqual(transport.sent[-1]["result"]["reason"], "missing_required_bind_context")

    async def test_business_unexecutable_stays_structured_in_result_with_succeeded_wire_status(self):
        class BusinessUnexecutableHandlers:
            async def handle(self, dispatch):
                return WorkerTaskResult(
                    status="business_unexecutable",
                    result={"status": "business_unexecutable", "reason": "missing_corp_id"},
                    progress=[{"status": "business_unexecutable", "message": "wecom bind cannot execute"}],
                )

        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-server-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-business-unexecutable",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "simulate": False,
                    "payload": {"task_type": "wecom_bind_service", "enterprise_name": "zh_test_上海测试客户"},
                },
            ]
        )

        runtime = C360WorkerRuntime(
            config=self._config(simulate=False),
            transport=transport,
            handlers=BusinessUnexecutableHandlers(),
        )

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-1]["type"], "task.completed")
        self.assertEqual(transport.sent[-1]["status"], "succeeded")
        self.assertEqual(transport.sent[-1]["result"]["status"], "business_unexecutable")
        self.assertEqual(transport.sent[-1]["result"]["reason"], "missing_corp_id")

    async def test_verbose_logger_reports_lifecycle_without_sensitive_payload(self):
        events = []
        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-verbose",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "simulate": True,
                    "payload": {
                        "task_type": "wecom_bind_service",
                        "enterprise_name": "zh_test_模拟客户",
                        "plain_corp_id": "ww_secret_should_not_print",
                    },
                },
            ]
        )
        runtime = C360WorkerRuntime(
            config=self._config(),
            transport=transport,
            handlers=SimulatedTaskHandlers({}),
            event_logger=events.append,
        )

        await runtime.run_until_idle()

        joined = "\n".join(events)
        self.assertIn("worker hello sent worker_id=win-sim-001 simulate=True", joined)
        self.assertIn("worker accepted worker_id=win-sim-001", joined)
        self.assertIn("task received task_id=task-verbose task_type=wecom_bind_service simulate=True", joined)
        self.assertIn("task accepted task_id=task-verbose", joined)
        self.assertIn("task progress task_id=task-verbose status=running", joined)
        self.assertIn("task completed task_id=task-verbose status=succeeded", joined)
        self.assertIn("worker idle", joined)
        self.assertNotIn("zh_test_模拟客户", joined)
        self.assertNotIn("ww_secret_should_not_print", joined)
        self.assertNotIn("secret-token", joined)


class C360WorkerCliTest(unittest.TestCase):
    def test_default_cli_uses_persistent_runner_with_reconnect_delay(self):
        calls = []

        async def fake_run_forever(config, event_logger=None, reconnect_delay_seconds=0):
            calls.append(
                {
                    "worker_id": config.worker_id,
                    "event_logger": event_logger,
                    "reconnect_delay_seconds": reconnect_delay_seconds,
                }
            )

        async def unexpected_run(config, event_logger=None):
            raise AssertionError("default CLI should use persistent runner")

        with patch.object(c360_worker, "_run_forever", side_effect=fake_run_forever, create=True):
            with patch.object(c360_worker, "_run", side_effect=unexpected_run):
                exit_code = c360_worker.main(
                    ["--verbose"],
                    env={
                        "C360_BASE_URL": "http://127.0.0.1:3601",
                        "RPA_WORKER_TOKEN": "secret-token",
                        "RPA_WORKER_ID": "win-sim-001",
                        "RPA_WORKER_RECONNECT_DELAY_SECONDS": "0.25",
                    },
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0]["worker_id"], "win-sim-001")
        self.assertIsNotNone(calls[0]["event_logger"])
        self.assertEqual(calls[0]["reconnect_delay_seconds"], 0.25)

    def test_verbose_flag_passes_event_logger_to_runner(self):
        calls = []

        async def fake_run(config, event_logger=None):
            calls.append({"worker_id": config.worker_id, "event_logger": event_logger})

        with patch.object(c360_worker, "_run", side_effect=fake_run):
            exit_code = c360_worker.main(
                ["--once", "--verbose"],
                env={
                    "C360_BASE_URL": "http://127.0.0.1:3601",
                    "RPA_WORKER_TOKEN": "secret-token",
                    "RPA_WORKER_ID": "win-sim-001",
                },
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0]["worker_id"], "win-sim-001")
        self.assertIsNotNone(calls[0]["event_logger"])

    def test_runner_closes_transport_after_idle(self):
        class ClosableTransport(FakeTransport):
            def __init__(self):
                super().__init__(incoming=[])
                self.closed = False

            async def close(self):
                self.closed = True

        captured = {}

        async def fake_connect(_config):
            transport = ClosableTransport()
            captured["transport"] = transport
            return transport

        with patch.object(c360_worker, "connect_json_transport", side_effect=fake_connect):
            exit_code = c360_worker.main(
                ["--once"],
                env={
                    "C360_BASE_URL": "http://127.0.0.1:3601",
                    "RPA_WORKER_TOKEN": "secret-token",
                    "RPA_WORKER_ID": "win-sim-001",
                },
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(captured["transport"].closed)


class C360WorkerPersistentLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_forever_reconnects_after_idle_until_cancelled(self):
        calls = []
        sleeps = []
        events = []
        config = load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "http://127.0.0.1:3601",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-sim-001",
            }
        )

        async def fake_run(config, event_logger=None):
            calls.append(config.worker_id)
            if len(calls) >= 2:
                raise asyncio.CancelledError()

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        with patch.object(c360_worker, "_run", side_effect=fake_run):
            with self.assertRaises(asyncio.CancelledError):
                await c360_worker._run_forever(
                    config,
                    event_logger=events.append,
                    reconnect_delay_seconds=0.25,
                    sleep=fake_sleep,
                )

        self.assertEqual(calls, ["win-sim-001", "win-sim-001"])
        self.assertEqual(sleeps, [0.25])
        self.assertIn("worker reconnecting in 0.25s", "\n".join(events))


class SimulatedTaskHandlersTest(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_health_check_returns_simulated_ok(self):
        result = await SimulatedTaskHandlers({}).handle({"task_type": "runtime_health_check", "payload": {}})

        self.assertEqual(result["ok"], True)
        self.assertEqual(result["simulated"], True)

    async def test_diagnostics_returns_redacted_summary(self):
        result = await SimulatedTaskHandlers(
            {
                "machine_id": "win-sim-001",
                "session_name": "console",
                "recent_error": "token: secret-value",
            }
        ).handle({"task_type": "diagnostics", "payload": {}})

        self.assertEqual(result["machine_id"], "win-sim-001")
        self.assertNotIn("secret-value", str(result))

    async def test_wecom_bind_service_returns_fixed_simulated_result(self):
        result = await SimulatedTaskHandlers({}).handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "zh_test_模拟客户", "plain_corp_id": "ww_test"},
            }
        )

        self.assertEqual(result, {"simulated": True, "handler": "wecom_bind_service"})


class AioHttpJsonTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_and_receives_json_with_aiohttp_websocket(self):
        class Message:
            def __init__(self, data):
                self.data = data

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_str(self, data):
                self.sent.append(data)

            async def receive(self):
                return Message('{"type": "worker.accepted", "worker_id": "win-sim-001"}')

        websocket = FakeWebSocket()
        transport = AioHttpJsonTransport(websocket, session=None)

        await transport.send_json({"type": "worker.hello", "worker_id": "win-sim-001"})
        received = await transport.receive_json()

        self.assertIn('"worker.hello"', websocket.sent[0])
        self.assertEqual(received["type"], "worker.accepted")

    async def test_receive_json_returns_none_for_aiohttp_close_frame(self):
        class Message:
            data = 1000

        class FakeWebSocket:
            async def receive(self):
                return Message()

        transport = AioHttpJsonTransport(FakeWebSocket(), session=None)

        self.assertIsNone(await transport.receive_json())


if __name__ == "__main__":
    unittest.main()
