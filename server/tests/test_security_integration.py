"""Exercise the real application boundary without any database connection."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import app as lims
import run
from security import INSTRUMENT_ENDPOINTS, RateLimiter, protect_request


class SecurityIntegrationTest(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.dict(lims.app.config, {
                "TESTING": True, "AUTH_DISABLED": False,
                "LIMS_DATABASE_URL": None, "DATABASE_URL": None,
                "XRF_CLIENT_TOKEN": "", "STANDARD_CLIENT_TOKEN": "",
                "SECURITY_REQUIRE_HTTPS": True, "SECURITY_COOKIE_SECURE": None,
            }),
            patch.dict(lims.app.extensions, {"security_rate_limiter": RateLimiter()}),
            patch.object(lims, "DB", None),
            patch.object(lims, "connect_database", side_effect=AssertionError("Unexpected database access")),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = lims.app.test_client()

    def test_security_hook_precedes_authentication_and_database_access(self):
        hooks = lims.app.before_request_funcs[None]
        self.assertLess(hooks.index(protect_request), hooks.index(lims.load_user))
        for disabled in (False, True):
            lims.app.config["AUTH_DISABLED"] = disabled
            response = self.client.post("/api/samples", json={})
            self.assertEqual(403, response.status_code)
            self.assertEqual("csrf_origin", response.json["code"])
            self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])

    def test_every_instrument_exemption_requires_token_even_on_loopback(self):
        adapter = lims.app.url_map.bind("localhost")
        for endpoint in INSTRUMENT_ENDPOINTS:
            rule = next(rule for rule in lims.app.url_map.iter_rules() if rule.endpoint == endpoint)
            method = "POST" if "POST" in rule.methods else "GET"
            path = adapter.build(endpoint, {argument: 1 for argument in rule.arguments})
            for disabled in (False, True):
                lims.app.config["AUTH_DISABLED"] = disabled
                with self.subTest(endpoint=endpoint, auth_disabled=disabled):
                    response = self.client.open(path, method=method, json={})
                    self.assertEqual(503, response.status_code)
                    with patch.dict(lims.app.config, {
                        "XRF_CLIENT_TOKEN": "test-device-token",
                        "STANDARD_CLIENT_TOKEN": "test-device-token",
                    }):
                        for token in ("", "wrong", "\u00e9"):
                            response = self.client.open(path, method=method, json={},
                                                        headers={"X-Instrument-Token": token})
                            self.assertEqual(401, response.status_code)

    def test_external_http_is_rejected_before_database_access(self):
        response = self.client.get("/api/session", base_url="http://lims.example",
                                   environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual(403, response.status_code)
        self.assertEqual("https_required", response.json["code"])

    def test_database_configuration_is_required_at_startup_not_import(self):
        with patch.object(lims, "initialize_database") as initialize:
            with self.assertRaisesRegex(RuntimeError, "Configure LIMS_DATABASE_URL"):
                lims.init_db()
            with self.assertRaisesRegex(RuntimeError, "Configure LIMS_DATABASE_URL"):
                run.main()
            initialize.assert_not_called()

    def test_flask_database_configuration_is_used_for_initialization_and_requests(self):
        with patch.dict(lims.app.config, {"DATABASE_URL": ":memory:"}), \
                patch.object(lims, "initialize_database") as initialize, \
                patch.object(lims, "connect_database") as connect:
            lims.init_db()
            initialize.assert_called_once_with(":memory:")
            with lims.app.app_context():
                self.assertIs(connect.return_value, lims.get_db())
                self.assertIs(connect.return_value, lims.get_db())
            connect.assert_called_once_with(":memory:")
            connect.return_value.close.assert_called_once()

    def test_database_errors_are_generic_in_real_app(self):
        lims.app.config["PROPAGATE_EXCEPTIONS"] = False
        with patch.object(lims, "connect_database", side_effect=RuntimeError("private-database-details")), \
                patch.object(lims, "DB", ":memory:"), self.assertLogs(lims.app.logger, level="ERROR"):
            response = self.client.get("/api/session")
        self.assertEqual(500, response.status_code)
        self.assertEqual("internal_error", response.json["code"])
        self.assertNotIn("private-database-details", response.get_data(as_text=True))

    def test_startup_database_error_does_not_print_connection_details(self):
        with patch.object(lims, "DB", ":memory:"), \
                patch.object(lims, "init_db", side_effect=RuntimeError("private-database-details")):
            with self.assertRaises(SystemExit) as error:
                run.main()
        self.assertNotIn("private-database-details", str(error.exception))

    def test_proxy_configuration_honors_forwarded_https_without_database_import_access(self):
        env = {key: value for key, value in os.environ.items()
               if key not in {"LIMS_DATABASE_URL", "LIMS_DB"}}
        env.update(LIMS_TRUST_PROXY="TRUE", LIMS_REQUIRE_HTTPS="1",
                   LIMS_SECRET_KEY="isolated-integration-test-key")
        code = """
from unittest.mock import patch
from werkzeug.test import EnvironBuilder
from flask import Request
with patch('db_backend.connect_database', side_effect=AssertionError('database accessed')), \
     patch('db_schema.initialize_database', side_effect=AssertionError('database initialized')):
    import app
    assert app.DB is None
    middleware = app.app.wsgi_app
    assert middleware.x_proto == 1 and middleware.x_for == 1
    assert middleware.x_host == 0
    def probe(environ, start_response):
        request = Request(environ)
        assert request.is_secure
        assert request.remote_addr == '192.0.2.10'
        start_response('200 OK', [])
        return [b'ok']
    middleware.app = probe
    environ = EnvironBuilder(headers={'X-Forwarded-Proto': 'https',
                                      'X-Forwarded-For': '192.0.2.10'}).get_environ()
    assert middleware(environ, lambda *args: None) == [b'ok']
"""
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
