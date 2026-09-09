"""Isolated security tests: the auth layer runs against a throwaway PostgreSQL schema."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

import lims_auth as auth
from postgres_case import PostgresTestCase
from security import RateLimiter, init_security


class SecurityTest(PostgresTestCase):
    PASSWORD = "correct-password-123"

    def setUp(self):
        self.provision_database()
        self.db = self.connect()
        self.addCleanup(self.db.close)
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
        self.app.config.update(TESTING=True, SECRET_KEY="isolated-test-secret",
                               SECURITY_REQUIRE_HTTPS=True, SECURITY_COOKIE_SECURE=None)
        self.app.extensions["lims_get_db"] = lambda: self.db
        init_security(self.app)
        self.app.register_blueprint(auth.bp)
        self.app.before_request(auth.load_user)
        self.app.before_request(auth.login_required_before_request)
        self.app.after_request(auth.extend_write_authorization)
        self.app.add_url_rule("/", "index", lambda: "<h1>App</h1>")
        self.app.add_url_rule("/api/write", "write", lambda: jsonify(ok=True),
                              methods=["POST", "PUT", "PATCH", "DELETE"])

        def instrument():
            if request.headers.get("Authorization") != "Bearer test-device-token":
                return jsonify(ok=False), 401
            return jsonify(ok=True)

        self.app.add_url_rule("/api/instrument/xrf/import", "xrf_client_import", instrument,
                              methods=["POST"])
        self.app.add_url_rule("/api/instrument/standard/authorize", "standard_client_authorize",
                              instrument, methods=["POST"])
        self.app.add_url_rule("/api/instrument/xrf/not-exempt", "not_exempt",
                              lambda: jsonify(ok=True), methods=["POST"])

        def broken():
            raise RuntimeError("secret database password")

        self.app.add_url_rule("/api/broken", "broken", broken)
        self.audit = patch.object(auth, "audit_event").start()
        self.addCleanup(patch.stopall)
        self.client = self.app.test_client()

    def seed(self, password=PASSWORD, kind="admin"):
        hashed = generate_password_hash(password, method="pbkdf2:sha256:20000")
        self.db.execute("INSERT INTO users(id,username,password_hash,display_name,permissions) VALUES(1,%s,%s,%s,%s)",
                        ("admin", hashed, "Admin", json.dumps(sorted(auth.CAPABILITIES))))
        self.db.execute("INSERT INTO terminals(id,name,password_hash,kind) VALUES(1,%s,%s,%s)",
                        ("Terminal", hashed, kind))
        self.db.commit()
        return hashed

    def token(self):
        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        return response.json["csrf_token"]

    def write(self, path, *, method="POST", **kwargs):
        headers = {"Origin": "http://localhost", "X-CSRF-Token": self.token()}
        headers.update(kwargs.pop("headers", {}))
        return self.client.open(path, method=method, headers=headers, **kwargs)

    def login(self, password=PASSWORD):
        return self.write("/login", data={"terminal_id": 1, "password": password})

    def test_bootstrap_available_before_setup_and_anonymous_login(self):
        response = self.client.get("/api/session")
        self.assertTrue(response.json["setup_required"])
        self.assertFalse(response.json["authenticated"])
        self.assertEqual(6, response.json["min_password_length"])
        self.assertEqual("no-store", response.headers["Cache-Control"])
        self.seed()
        self.assertFalse(self.client.get("/api/session").json["setup_required"])

    def test_all_browser_unsafe_methods_require_token_and_origin(self):
        self.seed()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                response = self.client.open("/api/write", method=method)
                self.assertEqual(403, response.status_code)
                response = self.client.open("/api/write", method=method, headers={"Origin": "http://localhost"})
                self.assertEqual("csrf_invalid", response.json["code"])

    def test_login_setup_authorize_and_logout_are_not_exempt(self):
        for path in ("/login", "/setup", "/api/authorize", "/api/authorization/clear", "/logout"):
            with self.subTest(path=path):
                self.assertEqual(403, self.client.post(path).status_code)

    def test_valid_same_origin_token_allows_each_unsafe_method(self):
        self.seed()
        self.login()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertEqual(200, self.write("/api/write", method=method).status_code)

    def test_strict_origin_rejects_siblings_ports_schemes_and_null(self):
        token = self.token()
        for origin in ("https://localhost", "http://localhost:81", "http://evil.localhost",
                       "null", "http://localhost.evil", "http://user@localhost", "http://localhost/path"):
            with self.subTest(origin=origin):
                response = self.client.post("/setup", headers={"Origin": origin, "X-CSRF-Token": token})
                self.assertEqual("csrf_origin", response.json["code"])

    def test_referer_fallback_and_fetch_metadata(self):
        response = self.client.post("/setup", data={"csrf_token": self.token()},
                                    headers={"Referer": "http://localhost/setup"})
        self.assertEqual(200, response.status_code)
        for headers in ({"Sec-Fetch-Site": "same-site"}, {"Referer": "http://evil.test/"}):
            response = self.write("/setup", headers=headers)
            self.assertEqual("csrf_origin", response.json["code"])

    def test_token_is_bound_to_session_and_malformed_tokens_fail_closed(self):
        token = self.token()
        other = self.app.test_client()
        response = other.post("/setup", headers={"Origin": "http://localhost", "X-CSRF-Token": token})
        self.assertEqual("csrf_invalid", response.json["code"])
        response = self.write("/setup", headers={"X-CSRF-Token": "\u00e9"})
        self.assertEqual("csrf_invalid", response.json["code"])

    def test_token_rotates_at_login_logout_and_setup(self):
        before = self.token()
        response = self.write("/setup", data={"password": self.PASSWORD,
            "normal_terminal_password": "standard-password-123", "admin_terminal_password": "admin-password-123"})
        self.assertEqual(302, response.status_code)
        after_setup = self.token()
        self.assertNotEqual(before, after_setup)
        self.assertEqual(302, self.login("standard-password-123").status_code)
        after_login = self.token()
        self.assertNotEqual(after_setup, after_login)
        response = self.write("/api/authorize", json={"password": self.PASSWORD},
                              headers={"X-CSRF-Token": after_setup})
        self.assertEqual(403, response.status_code)
        self.assertEqual(302, self.write("/logout").status_code)
        self.assertNotEqual(after_login, self.token())

    def test_bootstrap_identity_contains_no_secrets(self):
        self.seed()
        self.login()
        data = self.client.get("/api/session").json
        self.assertTrue(data["authenticated"])
        self.assertEqual("admin", data["terminal"]["kind"])
        self.assertIn("user_manage", data["user"]["permissions"])
        self.assertNotIn("password_hash", json.dumps(data))
        self.assertNotIn("session_token", json.dumps(data))

    def test_get_logout_cannot_clear_session(self):
        self.seed()
        self.login()
        self.assertEqual(405, self.client.get("/logout").status_code)
        self.assertTrue(self.client.get("/api/session").json["authenticated"])

    def test_exempt_instrument_endpoint_still_needs_bearer(self):
        path = "/api/instrument/xrf/import"
        self.assertEqual(401, self.client.post(path).status_code)
        response = self.client.post(path, headers={"Authorization": "Bearer test-device-token"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(403, self.client.post("/api/instrument/xrf/not-exempt").status_code)

    def test_machine_authorization_is_also_rate_limited(self):
        self.app.config["SECURITY_RATE_LIMITS"]["authorize"] = (1, 60)
        path = "/api/instrument/standard/authorize"
        self.assertEqual(401, self.client.post(path).status_code)
        self.assertEqual(429, self.client.post(path).status_code)

    def test_security_headers_and_nonce_preserve_login_script(self):
        self.seed()
        response = self.client.get("/login")
        html = response.get_data(as_text=True)
        self.assertIn('name="csrf_token"', html)
        nonce = html.split('<script nonce="', 1)[1].split('"', 1)[0]
        csp = response.headers["Content-Security-Policy"]
        self.assertIn(f"script-src 'self' 'nonce-{nonce}'", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertEqual("no-store", response.headers["Cache-Control"])
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("; Secure", cookie)

    def test_https_required_outside_local_http_and_secure_cookie_default(self):
        response = self.client.get("/api/session", base_url="http://lims.example",
                                    environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual("https_required", response.json["code"])
        response = self.client.get("/api/session", base_url="https://lims.example",
                                    environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual(200, response.status_code)
        self.assertIn("; Secure", response.headers["Set-Cookie"])
        self.assertIn("max-age=", response.headers["Strict-Transport-Security"])

    def test_localhost_host_header_does_not_allow_remote_http(self):
        response = self.client.get("/api/session", environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual(403, response.status_code)

    def test_http_deployment_requires_explicit_config(self):
        self.app.config.update(SECURITY_REQUIRE_HTTPS=False, SECURITY_COOKIE_SECURE=False)
        response = self.client.get("/api/session", base_url="http://lims.example")
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json["requireHTTPS"])
        self.assertNotIn("; Secure", response.headers["Set-Cookie"])

    def test_auth_disabled_does_not_disable_csrf(self):
        self.app.config["AUTH_DISABLED"] = True
        self.assertEqual(403, self.client.post("/api/write").status_code)

    def test_rate_limit_returns_information_and_recovers(self):
        self.seed()
        clock = [0.0]
        self.app.extensions["security_rate_limiter"] = RateLimiter(clock=lambda: clock[0])
        self.app.config["SECURITY_RATE_LIMITS"]["login"] = (2, 10)
        for _ in range(2):
            self.assertEqual(200, self.login("wrong").status_code)
        response = self.login()
        self.assertEqual(429, response.status_code)
        self.assertEqual("10", response.headers["Retry-After"])
        self.assertEqual("0", response.headers["RateLimit-Remaining"])
        self.assertEqual(10, response.json["retry_after"])
        clock[0] = 10
        response = self.login()
        self.assertEqual(302, response.status_code)
        self.assertEqual("1", response.headers["RateLimit-Remaining"])

    def test_forwarded_for_is_not_trusted_by_limiter(self):
        self.seed()
        self.app.config["SECURITY_RATE_LIMITS"]["login"] = (1, 60)
        self.login("wrong")
        response = self.write("/login", data={"password": "wrong"},
                              headers={"X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(429, response.status_code)

    def test_login_and_authorize_limits_are_independent(self):
        self.seed(kind="standard")
        self.login()
        self.app.config["SECURITY_RATE_LIMITS"]["authorize"] = (1, 60)
        self.assertEqual(401, self.write("/api/authorize", json={"password": "wrong"}).status_code)
        self.assertEqual(429, self.write("/api/authorize", json={"password": self.PASSWORD}).status_code)
        self.assertEqual(302, self.login().status_code)

    def test_setup_attempts_are_rate_limited(self):
        self.app.config["SECURITY_RATE_LIMITS"]["setup"] = (1, 60)
        self.assertEqual(200, self.write("/setup").status_code)
        response = self.write("/setup")
        self.assertEqual(429, response.status_code)
        self.assertEqual("rate_limited", response.json["code"])

    def test_cookie_environment_options(self):
        app = Flask("configured-security-test")
        with patch.dict("os.environ", {"LIMS_REQUIRE_HTTPS": "0", "LIMS_SESSION_COOKIE_SECURE": "1"}):
            init_security(app)
        self.assertFalse(app.config["SECURITY_REQUIRE_HTTPS"])
        self.assertTrue(app.config["SECURITY_COOKIE_SECURE"])
        self.assertTrue(app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual("Strict", app.config["SESSION_COOKIE_SAMESITE"])

    def test_generic_server_error_does_not_expose_exception(self):
        self.seed()
        self.login()
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.get("/api/broken")
        self.assertEqual(500, response.status_code)
        self.assertEqual("internal_error", response.json["code"])
        self.assertNotIn("secret database", response.get_data(as_text=True))
        self.assertEqual("no-store", response.headers["Cache-Control"])

    def test_new_short_passwords_rejected_but_preexisting_hashes_still_authenticate(self):
        response = self.write("/setup", data={"password": "u", "normal_terminal_password": "s",
                                              "admin_terminal_password": "a"})
        self.assertEqual(200, response.status_code)
        self.assertFalse(self.db.execute("SELECT 1 FROM users").fetchone())
        seeded = self.seed("short")
        self.assertEqual(302, self.login("short").status_code)
        hashed = self.db.execute("SELECT password_hash FROM terminals").fetchone()[0]
        self.assertEqual(seeded, hashed)
        self.assertTrue(check_password_hash(hashed, "short"))

    def test_new_password_policy_on_user_and_terminal_create_update(self):
        self.seed()
        self.login()
        for path, method, data in (
            ("/api/users", "POST", {"username": "new", "permissions": []}),
            ("/api/users/1", "PUT", {}),
            ("/api/terminals", "POST", {"name": "New"}),
            ("/api/terminals/1", "PUT", {}),
        ):
            with self.subTest(path=path):
                response = self.write(path, method=method, json={**data, "password": "short"})
                self.assertEqual(400, response.status_code)
                self.assertIn("6", response.json["error"])

    def test_existing_short_admin_can_complete_setup_with_strong_new_passwords(self):
        self.seed("short")
        self.db.execute("DELETE FROM terminals")
        self.db.commit()
        response = self.write("/setup", data={"password": "short",
            "normal_terminal_password": "standard-password-123", "admin_terminal_password": "admin-password-123"})
        self.assertEqual(302, response.status_code)

    def test_failed_or_ambiguous_password_search_has_no_hash_writes(self):
        original = self.seed(kind="standard")
        self.login()
        self.db.execute("INSERT INTO users(username,password_hash,display_name) VALUES('duplicate',%s,'Other')",
                        (original,))
        self.db.commit()
        self.assertEqual([], auth._matching_users(self.db, "wrong"))
        self.assertEqual(2, len(auth._matching_users(self.db, self.PASSWORD)))
        self.assertTrue(auth._password_in_use(self.db, self.PASSWORD))
        self.assertEqual(401, self.write("/api/authorize", json={"password": self.PASSWORD}).status_code)
        hashes = [row[0] for row in self.db.execute("SELECT password_hash FROM users ORDER BY id")]
        self.assertEqual([original, original], hashes)

    def test_authorization_requires_unique_capable_match_and_keeps_hashes(self):
        original = self.seed(kind="standard")
        other = generate_password_hash("other-password", method="pbkdf2:sha256:20000")
        self.db.execute("INSERT INTO users(username,password_hash,display_name) VALUES('other',%s,'Other')", (other,))
        self.db.commit()
        self.login()
        denied = self.write("/api/authorize", json={"password": "other-password", "purpose": "user_manage"})
        self.assertEqual(403, denied.status_code)
        self.assertEqual(200, self.write("/api/authorize", json={"password": self.PASSWORD}).status_code)
        hashes = [row[0] for row in self.db.execute("SELECT password_hash FROM users ORDER BY id")]
        self.assertEqual([original, other], hashes)

    def test_capable_instrument_authentication_requires_capability(self):
        self.seed()
        user, error = auth.authenticate_capable_user(self.db, "wrong", "result_edit")
        self.assertIsNone(user)
        self.assertIsNotNone(error)
        user, error = auth.authenticate_capable_user(self.db, self.PASSWORD, "result_edit")
        self.assertIsNone(error)
        self.assertIsNotNone(user)
        limited = generate_password_hash("limited-password", method="pbkdf2:sha256:20000")
        self.db.execute("INSERT INTO users(username,password_hash,display_name,permissions) "
                        "VALUES('limited',%s,'Limited','[]')", (limited,))
        self.db.commit()
        user, error = auth.authenticate_capable_user(self.db, "limited-password", "result_edit")
        self.assertIsNone(user)
        self.assertIn("权限", error)

    def test_password_hash_helper_enforces_policy(self):
        for password in ("", "short", "x" * 1025):
            with self.assertRaises(ValueError):
                auth.hash_password(password)
        hashed = auth.hash_password("x" * 12)
        self.assertTrue(check_password_hash(hashed, "x" * 12))

    def test_invalid_hash_fails_closed(self):
        self.assertFalse(auth._password_matches({"password_hash": "unknown$salt$value"}, "password"))


class RateLimiterTest(unittest.TestCase):
    def test_bounded_capacity_does_not_evict_live_limits(self):
        clock = [0.0]
        limiter = RateLimiter(max_keys=2, clock=lambda: clock[0])
        self.assertTrue(limiter.check("a", "login", 1, 10)["allowed"])
        self.assertTrue(limiter.check("b", "login", 1, 10)["allowed"])
        self.assertFalse(limiter.check("c", "login", 1, 10)["allowed"])
        self.assertFalse(limiter.check("a", "login", 1, 10)["allowed"])
        self.assertEqual(2, len(limiter._entries))
        clock[0] = 10
        self.assertTrue(limiter.check("c", "login", 1, 10)["allowed"])
        self.assertEqual(1, len(limiter._entries))

    def test_rejected_attempts_do_not_extend_window(self):
        clock = [0.0]
        limiter = RateLimiter(clock=lambda: clock[0])
        limiter.check("a", "login", 1, 10)
        clock[0] = 9
        self.assertEqual(1, limiter.check("a", "login", 1, 10)["retry_after"])
        clock[0] = 10
        self.assertTrue(limiter.check("a", "login", 1, 10)["allowed"])

    def test_ip_and_action_independent(self):
        limiter = RateLimiter()
        for ip, action in (("a", "login"), ("b", "login"), ("a", "authorize")):
            self.assertTrue(limiter.check(ip, action, 1, 60)["allowed"])
            self.assertFalse(limiter.check(ip, action, 1, 60)["allowed"])

    def test_concurrent_attempts_cannot_exceed_limit(self):
        limiter = RateLimiter()
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(lambda _: limiter.check("a", "login", 10, 60), range(100)))
        self.assertEqual(10, sum(result["allowed"] for result in results))


if __name__ == "__main__":
    unittest.main()
