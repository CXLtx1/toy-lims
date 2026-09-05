import os
import sqlite3
import tempfile
import unittest

import app as lims
from lims_auth import PASSWORD_METHOD
from werkzeug.security import generate_password_hash


class TerminalAuthenticationTest(unittest.TestCase):
    USER_PASSWORD = "cxl-password-123"
    STANDARD_PASSWORD = "standard-terminal-123"
    ADMIN_PASSWORD = "admin-terminal-123"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=False)
        self.client = lims.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def initialize(self):
        response = self.client.post("/setup", data={
            "display_name": "CXL 管理员",
            "password": self.USER_PASSWORD,
            "normal_terminal_password": self.STANDARD_PASSWORD,
            "admin_terminal_password": self.ADMIN_PASSWORD,
        })
        self.assertEqual(302, response.status_code, response.get_data(as_text=True))
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def terminal_id(self, kind):
        db = sqlite3.connect(lims.DB)
        try:
            return db.execute("SELECT id FROM terminals WHERE kind=?", (kind,)).fetchone()[0]
        finally:
            db.close()

    def login(self, kind="standard", password=None):
        password = password or (self.STANDARD_PASSWORD if kind == "standard" else self.ADMIN_PASSWORD)
        return self.client.post("/login", data={
            "terminal_id": self.terminal_id(kind), "password": password,
        })

    def authorize(self, password=None):
        return self.client.post("/api/authorize", json={
            "password": password or self.USER_PASSWORD,
        })

    def test_setup_creates_fixed_user_and_two_distinct_terminals(self):
        self.initialize()
        db = sqlite3.connect(lims.DB)
        try:
            self.assertEqual([("cxl", "CXL 管理员")], db.execute(
                "SELECT username,display_name FROM users").fetchall())
            self.assertEqual([("二组", "standard"), ("管理终端", "admin")], db.execute(
                "SELECT name,kind FROM terminals ORDER BY id").fetchall())
            hashes = [row[0] for row in db.execute("SELECT password_hash FROM users")] + [
                row[0] for row in db.execute("SELECT password_hash FROM terminals")]
            self.assertTrue(all(value.startswith(PASSWORD_METHOD + "$") for value in hashes))
        finally:
            db.close()

    def test_successful_login_and_authorization_upgrade_legacy_hashes(self):
        self.initialize()
        legacy_user_hash = generate_password_hash(self.USER_PASSWORD)
        legacy_terminal_hash = generate_password_hash(self.STANDARD_PASSWORD)
        db = sqlite3.connect(lims.DB)
        try:
            db.execute("UPDATE users SET password_hash=? WHERE username='cxl'", (legacy_user_hash,))
            db.execute("UPDATE terminals SET password_hash=? WHERE kind='standard'", (legacy_terminal_hash,))
            db.commit()
        finally:
            db.close()

        self.assertEqual(302, self.login().status_code)
        self.assertEqual(200, self.authorize().status_code)
        db = sqlite3.connect(lims.DB)
        try:
            user_hash = db.execute(
                "SELECT password_hash FROM users WHERE username='cxl'").fetchone()[0]
            terminal_hash = db.execute(
                "SELECT password_hash FROM terminals WHERE kind='standard'").fetchone()[0]
        finally:
            db.close()
        self.assertTrue(user_hash.startswith(PASSWORD_METHOD + "$"))
        self.assertTrue(terminal_hash.startswith(PASSWORD_METHOD + "$"))

    def test_setup_accepts_short_nonempty_passwords(self):
        response = self.client.post("/setup", data={
            "display_name": "CXL 管理员",
            "password": "u",
            "normal_terminal_password": "s",
            "admin_terminal_password": "a",
        })
        self.assertEqual(302, response.status_code, response.get_data(as_text=True))
        self.assertEqual(302, self.login("admin", "a").status_code)

    def test_user_page_is_between_audit_and_settings(self):
        self.initialize()
        self.login("admin")
        page = self.client.get("/").get_data(as_text=True)
        self.assertLess(page.index('data-page="audit"'), page.index('data-page="users"'))
        self.assertLess(page.index('data-page="users"'), page.index('data-page="settings"'))
        users_start = page.index('id="page-users"')
        settings_start = page.index('id="page-settings"')
        self.assertLess(users_start, page.index('id="u-table"'))
        self.assertLess(page.index('id="terminal-table"'), settings_start)

    def test_existing_database_setup_requires_unique_active_admin_password(self):
        db = sqlite3.connect(lims.DB)
        try:
            db.execute("INSERT INTO users(username,password_hash,display_name,role) VALUES(?,?,?,'admin')",
                       ("cxl", generate_password_hash(self.USER_PASSWORD), "原管理员"))
            db.commit()
        finally:
            db.close()
        rejected = self.client.post("/setup", data={
            "password": "wrong-password", "normal_terminal_password": self.STANDARD_PASSWORD,
            "admin_terminal_password": self.ADMIN_PASSWORD,
        })
        self.assertEqual(200, rejected.status_code)
        accepted = self.client.post("/setup", data={
            "password": self.USER_PASSWORD, "normal_terminal_password": self.STANDARD_PASSWORD,
            "admin_terminal_password": self.ADMIN_PASSWORD,
        })
        self.assertEqual(302, accepted.status_code)
        db = sqlite3.connect(lims.DB)
        try:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM users WHERE username='cxl'").fetchone()[0])
            self.assertEqual(2, db.execute("SELECT COUNT(*) FROM terminals").fetchone()[0])
        finally:
            db.close()

    def test_terminal_selection_password_and_free_reads(self):
        self.initialize()
        wrong = self.login(password="incorrect-terminal-password")
        self.assertEqual(200, wrong.status_code)
        self.assertNotIn("terminal_id", self._session())
        self.assertEqual(302, self.login().status_code)
        self.assertEqual(200, self.client.get("/api/users").status_code)
        meta = self.client.get("/api/meta").get_json()
        self.assertEqual("二组", meta["terminal"]["name"])
        self.assertTrue(meta["authorization_required"])
        self.assertEqual(set(lims.CAPABILITIES), set(meta["current_user"]["permissions"]))

    def test_standard_write_requires_password_only_authorization_and_expires(self):
        self.initialize()
        self.login()
        required = self.client.post("/api/analytes", json={"name": "AuthRequired"})
        self.assertEqual(428, required.status_code)
        self.assertEqual("authorization_required", required.get_json()["code"])
        self.assertEqual(401, self.authorize("wrong-user-password").status_code)
        authorized = self.authorize()
        self.assertEqual("cxl", authorized.get_json()["user"]["username"])
        meta = self.client.get("/api/meta").get_json()
        self.assertTrue(meta["current_user"]["is_authorized"])
        self.assertFalse(meta["authorization_required"])
        with self.client.session_transaction() as session:
            session["last_write"] = 0
        self.assertEqual(428, self.client.post(
            "/api/analytes", json={"name": "Expired"}).status_code)

    def test_successful_write_extends_authorization_but_failed_write_does_not(self):
        self.initialize()
        self.login()
        self.authorize()
        with self.client.session_transaction() as session:
            session["last_write"] = __import__("time").time() - 1
            failed_write_time = session["last_write"]
        failed = self.client.post("/api/instruments", json={"name": "bad", "itype": "invalid"})
        self.assertEqual(400, failed.status_code)
        self.assertEqual(failed_write_time, self._session()["last_write"])
        with self.client.session_transaction() as session:
            session["last_write"] = __import__("time").time() - 1
            old = session["last_write"]
        succeeded = self.client.post("/api/analytes", json={"name": "AllowedWrite"})
        self.assertEqual(200, succeeded.status_code)
        self.assertGreater(self._session()["last_write"], old)
        self.client.post("/api/authorization/clear")
        self.assertEqual(428, self.client.post(
            "/api/analytes", json={"name": "RetryNeedsPassword"}).status_code)

    def test_ambiguous_password_is_rejected(self):
        self.initialize()
        db = sqlite3.connect(lims.DB)
        try:
            password_hash = db.execute("SELECT password_hash FROM users WHERE username='cxl'").fetchone()[0]
            db.execute("INSERT INTO users(username,password_hash,display_name,role) VALUES(?,?,?,'analyst')",
                       ("duplicate", password_hash, "重复密码用户"))
            db.commit()
        finally:
            db.close()
        self.login()
        self.assertEqual(401, self.authorize().status_code)

    def test_admin_terminal_bypasses_authorization_and_audits_terminal(self):
        self.initialize()
        self.assertEqual(302, self.login("admin").status_code)
        created = self.client.post("/api/analytes", json={"name": "AdminTerminalWrite"})
        self.assertEqual(200, created.status_code)
        audit = self.client.get("/api/audit").get_json()
        event = next(row for row in audit if row["action"] == "create" and
                     row["entity_type"] == "analyte")
        self.assertEqual("管理终端", event["terminal_name"])
        self.assertEqual("terminal:管理终端", event["username"])
        self.assertIsNone(event.get("user_id"))

    def test_manual_report_requires_one_time_user_password_on_admin_terminal(self):
        self.initialize()
        self.login("admin")
        db = sqlite3.connect(lims.DB)
        try:
            db.execute("INSERT INTO samples(name,status,workflow_type) VALUES('强授权报告','completed','regular')")
            sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()
        finally:
            db.close()
        rows = [{"item": "Cu", "result": "1.23", "unit": "%", "note": "", "include": True}]

        missing_reason = self.client.put(f"/api/reports/{sid}/manual", json={"rows": rows})
        self.assertEqual(400, missing_reason.status_code)
        required = self.client.put(f"/api/reports/{sid}/manual", json={
            "rows": rows, "reason": "补录结果",
        })
        self.assertEqual(428, required.status_code)
        self.assertEqual("forced_authorization_required", required.get_json()["code"])
        self.assertEqual(401, self.client.post("/api/authorize", json={
            "password": "wrong-user-password", "purpose": "result_override",
        }).status_code)
        confirmed = self.client.post("/api/authorize", json={
            "password": self.USER_PASSWORD, "purpose": "result_override",
        })
        self.assertEqual(200, confirmed.status_code)
        saved = self.client.put(f"/api/reports/{sid}/manual", json={
            "rows": rows, "reason": "补录结果",
        })
        self.assertEqual(200, saved.status_code)
        self.assertTrue(saved.get_json()["changed"])
        rows[0]["result"] = "2.34"
        self.assertEqual(428, self.client.put(
            f"/api/reports/{sid}/manual", json={"rows": rows, "reason": "再次修改"}).status_code)
        event = next(row for row in self.client.get("/api/audit").get_json()
                     if row["action"] == "result_override")
        self.assertEqual("cxl", event["username"])
        self.assertEqual("补录结果", event["reason"])

    def test_duplicate_user_password_is_rejected_on_add_and_update(self):
        self.initialize()
        self.login("admin")
        first = self.client.post("/api/users", json={
            "username": "analyst1", "display_name": "分析一",
            "password": "unique-analyst-pass", "permissions": ["result_edit"],
        })
        self.assertEqual(200, first.status_code)
        duplicate = self.client.post("/api/users", json={
            "username": "analyst2", "display_name": "分析二",
            "password": "unique-analyst-pass", "permissions": ["result_edit"],
        })
        self.assertEqual(409, duplicate.status_code)
        second = self.client.post("/api/users", json={
            "username": "analyst2", "display_name": "分析二",
            "password": "other-analyst-pass", "permissions": ["result_edit"],
        }).get_json()
        updated = self.client.put(f"/api/users/{second['id']}", json={
            "password": "unique-analyst-pass",
        })
        self.assertEqual(409, updated.status_code)
        self.assertIn("其他启用用户", updated.get_json()["error"])

    def test_admin_can_edit_user_login_name(self):
        self.initialize()
        self.login("admin")
        user_id = self.client.post("/api/users", json={
            "username": "analyst1", "display_name": "分析一",
            "password": "unique-analyst-pass", "permissions": ["result_edit"],
        }).get_json()["id"]
        updated = self.client.put(f"/api/users/{user_id}", json={
            "username": "analyst-renamed", "display_name": "分析员一",
        })
        self.assertEqual(200, updated.status_code, updated.get_data(as_text=True))
        user = next(item for item in self.client.get("/api/users").get_json()
                    if item["id"] == user_id)
        self.assertEqual("analyst-renamed", user["username"])
        self.assertEqual("分析员一", user["display_name"])
        self.assertEqual(["result_edit"], user["permissions"])

    def test_permissions_are_independent_and_api_exposes_no_role(self):
        self.initialize()
        self.login("admin")
        created = self.client.post("/api/users", json={
            "username": "data-only", "display_name": "只录数据",
            "password": "data-only-password", "permissions": ["result_edit"],
        })
        self.assertEqual(200, created.status_code)
        listed = next(user for user in self.client.get("/api/users").get_json()
                      if user["username"] == "data-only")
        self.assertNotIn("role", listed)
        self.assertEqual(["result_edit"], listed["permissions"])

        self.client.post("/logout")
        self.login("standard")
        self.authorize("data-only-password")
        denied = self.client.post("/api/samples", json={"name": "无样品能力"})
        self.assertEqual(403, denied.status_code)
        self.assertEqual("permission_denied", denied.get_json()["code"])
        self.assertEqual("sample_manage", denied.get_json()["capability"])
        self.assertIn("样品登记与修改", denied.get_json()["error"])
        allowed_to_reach_result_validation = self.client.post(
            "/api/results", json={"sample_analyte_id": -1, "raw": 1})
        self.assertEqual(404, allowed_to_reach_result_validation.status_code)

        unknown = self.client.get("/api/not-a-real-endpoint")
        self.assertEqual(404, unknown.status_code)
        self.assertEqual("api_not_found", unknown.get_json()["code"])

    def test_personal_terminal_uses_persistent_real_user_login(self):
        self.initialize()
        self.login("admin")
        user_id = self.client.post("/api/users", json={
            "username": "personal-user", "display_name": "个人用户",
            "password": "p", "permissions": ["result_edit"],
        }).get_json()["id"]
        self.client.post("/logout")
        login_page = self.client.get("/login").get_data(as_text=True)
        self.assertIn("所有启用用户均可使用自己的用户名和用户密码登录", login_page)

        wrong = self.client.post("/login", data={
            "terminal_kind": "personal", "username": "personal-user", "password": "wrong",
        })
        self.assertEqual(200, wrong.status_code)
        logged_in = self.client.post("/login", data={
            "terminal_kind": "personal", "username": "personal-user", "password": "p",
        })
        self.assertEqual(302, logged_in.status_code)
        self.assertEqual(user_id, self._session()["personal_user_id"])
        self.assertNotIn("last_write", self._session())

        meta = self.client.get("/api/meta").get_json()
        self.assertEqual("personal", meta["terminal"]["kind"])
        self.assertEqual("personal-user", meta["current_user"]["username"])
        self.assertFalse(meta["authorization_required"])
        self.client.post("/api/authorization/clear")
        allowed = self.client.post("/api/results", json={"sample_analyte_id": -1, "raw": 1})
        self.assertEqual(404, allowed.status_code)
        denied = self.client.post("/api/analytes", json={"name": "NotAllowed"})
        self.assertEqual(403, denied.status_code)

        audit = self.client.get("/api/audit").get_json()
        login_event = next(row for row in audit if row["action"] == "login" and
                           row["terminal_name"] == "个人终端")
        self.assertEqual(user_id, login_event["user_id"])
        self.assertEqual("personal-user", login_event["username"])

        db = sqlite3.connect(lims.DB)
        try:
            db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
            db.commit()
        finally:
            db.close()
        self.assertEqual(302, self.client.get("/").status_code)
        self.assertNotIn("terminal_id", self._session())

    def test_user_permissions_are_inherited_from_personal_manager(self):
        self.initialize()
        self.login("admin")
        manager_id = self.client.post("/api/users", json={
            "username": "delegated-manager", "display_name": "委派管理员",
            "password": "m", "permissions": ["user_manage", "result_edit"],
        }).get_json()["id"]
        self.client.post("/logout")
        self.assertEqual(302, self.client.post("/login", data={
            "terminal_kind": "personal", "username": "delegated-manager", "password": "m",
        }).status_code)

        excessive = self.client.post("/api/users", json={
            "username": "too-powerful", "display_name": "越权用户",
            "password": "x", "permissions": ["user_manage", "report_edit"],
        })
        self.assertEqual(403, excessive.status_code)
        self.assertEqual("permission_inheritance", excessive.get_json()["code"])
        child = self.client.post("/api/users", json={
            "username": "child-user", "display_name": "继承用户",
            "password": "c", "permissions": ["result_edit"],
        })
        self.assertEqual(200, child.status_code, child.get_data(as_text=True))
        child_id = child.get_json()["id"]
        self.assertEqual(403, self.client.put(f"/api/users/{child_id}", json={
            "permissions": ["result_edit", "report_edit"],
        }).status_code)
        self.assertEqual(403, self.client.put("/api/users/1", json={
            "display_name": "不应修改",
        }).status_code)
        self.assertEqual(manager_id, self._session()["personal_user_id"])

    def test_at_least_one_user_keeps_user_management_capability(self):
        self.initialize()
        self.login("admin")
        cxl = self.client.get("/api/users").get_json()[0]
        response = self.client.put(f"/api/users/{cxl['id']}", json={"permissions": []})
        self.assertEqual(400, response.status_code)
        self.assertIn("用户管理", response.get_json()["error"])

    def test_admin_can_add_and_edit_terminals_with_safety_constraints(self):
        self.initialize()
        self.login("admin")
        created = self.client.post("/api/terminals", json={
            "name": "仪器室", "password": "instrument-room-pass", "kind": "standard",
        })
        self.assertEqual(200, created.status_code, created.get_data(as_text=True))
        terminal_id = created.get_json()["id"]
        updated = self.client.put(f"/api/terminals/{terminal_id}", json={
            "name": "仪器室终端", "kind": "admin", "password": "instrument-admin-pass",
        })
        self.assertEqual(200, updated.status_code, updated.get_data(as_text=True))
        terminal = next(item for item in self.client.get("/api/terminals").get_json()
                        if item["id"] == terminal_id)
        self.assertEqual("仪器室终端", terminal["name"])
        self.assertEqual("admin", terminal["kind"])

        duplicate_password = self.client.post("/api/terminals", json={
            "name": "重复密码终端", "password": "instrument-admin-pass", "kind": "standard",
        })
        self.assertEqual(409, duplicate_password.status_code)

        personal = self.client.post("/api/terminals", json={
            "name": "不应创建", "kind": "personal",
        })
        self.assertEqual(400, personal.status_code)

        db = sqlite3.connect(lims.DB)
        try:
            db.execute("""INSERT INTO terminals(name,password_hash,kind,sort_order)
                VALUES('旧个人终端','legacy','personal',99)""")
            db.commit()
        finally:
            db.close()
        self.assertNotIn("旧个人终端", [
            item["name"] for item in self.client.get("/api/terminals").get_json()])

        current_id = self.terminal_id("admin")
        deactivate_current = self.client.put(
            f"/api/terminals/{current_id}", json={"active": False})
        self.assertEqual(400, deactivate_current.status_code)

    def test_admin_can_reorder_terminals_for_login_page(self):
        self.initialize()
        self.login("admin")
        third_id = self.client.post("/api/terminals", json={
            "name": "仪器室", "password": "instrument-room-pass", "kind": "standard",
        }).get_json()["id"]
        self.assertEqual(["二组", "管理终端", "仪器室"], [
            item["name"] for item in self.client.get("/api/terminals").get_json()])

        self.assertTrue(self.client.put(
            f"/api/terminals/{third_id}/order", json={"direction": "up"}).get_json()["changed"])
        self.assertTrue(self.client.put(
            f"/api/terminals/{third_id}/order", json={"direction": "up"}).get_json()["changed"])
        ordered = self.client.get("/api/terminals").get_json()
        self.assertEqual(["仪器室", "二组", "管理终端"], [item["name"] for item in ordered])
        self.assertEqual([1, 2, 3], [item["sort_order"] for item in ordered])
        self.assertEqual(400, self.client.put(
            f"/api/terminals/{third_id}/order", json={"direction": "sideways"}).status_code)

        self.client.post("/logout")
        login_page = self.client.get("/login").get_data(as_text=True)
        self.assertLess(login_page.index("仪器室"), login_page.index("二组"))
        self.assertLess(login_page.index("二组"), login_page.index("管理终端"))

    def test_last_admin_terminal_cannot_be_disabled(self):
        self.initialize()
        self.login("admin")
        admin_id = self.terminal_id("admin")
        standard_id = self.terminal_id("standard")
        self.client.put(f"/api/terminals/{standard_id}", json={"kind": "standard"})
        conn = sqlite3.connect(lims.DB)
        try:
            token = conn.execute(
                "SELECT session_token FROM terminals WHERE id=?", (standard_id,)).fetchone()[0]
        finally:
            conn.close()
        with self.client.session_transaction() as session:
            session["terminal_id"] = standard_id
            session["session_token"] = token
            session["authorized_user_id"] = 1
            session["last_write"] = __import__("time").time()
        response = self.client.put(f"/api/terminals/{admin_id}", json={"active": False})
        self.assertEqual(400, response.status_code)
        self.assertIn("至少保留", response.get_json()["error"])

    def _session(self):
        with self.client.session_transaction() as session:
            return dict(session)


if __name__ == "__main__":
    unittest.main()
