import unittest

from rpa_platform.worker.c360_worker_client import (
    C360WorkerConfigError,
    authorization_headers,
    build_c360_worker_ws_url,
    build_default_diagnostics,
    build_worker_hello,
    load_c360_worker_config_from_env,
)
from rpa_platform.worker.c360_worker import main


class C360WorkerClientConfigTest(unittest.TestCase):
    def test_builds_public_wss_endpoint_from_c360_base_url(self):
        url = build_c360_worker_ws_url("https://jdycsm.sre.jdydevelop.com/csm-c360-api")

        self.assertEqual(url, "wss://jdycsm.sre.jdydevelop.com/csm-c360-api/v1/rpa/workers/ws")

    def test_builds_local_ws_endpoint_from_http_base_url(self):
        url = build_c360_worker_ws_url("http://127.0.0.1:3601")

        self.assertEqual(url, "ws://127.0.0.1:3601/v1/rpa/workers/ws")

    def test_load_config_blocks_without_worker_token(self):
        with self.assertRaises(C360WorkerConfigError) as ctx:
            load_c360_worker_config_from_env(
                {
                    "C360_BASE_URL": "https://jdycsm.sre.jdydevelop.com/csm-c360-api",
                    "RPA_WORKER_ID": "win-sim-001",
                }
            )

        self.assertIn("RPA_WORKER_TOKEN is required", str(ctx.exception))
        self.assertNotIn("token=", str(ctx.exception).lower())

    def test_build_worker_hello_contains_identity_capabilities_simulate_and_diagnostics(self):
        config = load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "https://jdycsm.sre.jdydevelop.com/csm-c360-api",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-sim-001",
                "RPA_WORKER_SIMULATE": "true",
                "RPA_WORKER_CAPABILITIES": "wecom_bind_service,diagnostics,runtime_health_check",
            }
        )

        hello = build_worker_hello(
            config,
            diagnostics={
                "machine_id": "win-sim-001",
                "interactive_desktop": True,
                "session_name": "console",
                "resolution": "1920x1080",
                "dpi_scale": "100%",
            },
        )

        self.assertEqual(hello["type"], "worker.hello")
        self.assertEqual(hello["worker_id"], "win-sim-001")
        self.assertEqual(hello["capabilities"], ["wecom_bind_service", "diagnostics", "runtime_health_check"])
        self.assertTrue(hello["simulate"])
        self.assertEqual(hello["diagnostics"]["resolution"], "1920x1080")
        self.assertNotIn("secret-token", str(hello))

    def test_build_default_diagnostics_uses_env_without_sensitive_values(self):
        config = load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "http://127.0.0.1:3601",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-sim-001",
            }
        )

        diagnostics = build_default_diagnostics(
            config,
            {
                "SESSIONNAME": "console",
                "RPA_SCREEN_RESOLUTION": "1920x1080",
                "RPA_DPI_SCALE": "100%",
                "RPA_WORKER_TOKEN": "secret-token",
            },
        )

        self.assertEqual(diagnostics["machine_id"], "win-sim-001")
        self.assertEqual(diagnostics["session_name"], "console")
        self.assertEqual(diagnostics["resolution"], "1920x1080")
        self.assertNotIn("secret-token", str(diagnostics))

    def test_cli_blocks_without_token_and_does_not_print_token(self):
        exit_code = main([], env={"C360_BASE_URL": "http://127.0.0.1:3601"})

        self.assertEqual(exit_code, 2)

    def test_authorization_headers_use_csm_c360_worker_token_header(self):
        config = load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "http://127.0.0.1:3601",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-sim-001",
            }
        )

        headers = authorization_headers(config)

        self.assertEqual(headers, {"X-RPA-Worker-Token": "secret-token"})


if __name__ == "__main__":
    unittest.main()
