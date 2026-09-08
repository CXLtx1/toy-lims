import json
import os
import sqlite3
import tempfile
import unittest

import app as lims
from client_helpers import browser_client
from maintenance import create_backup


class PhaseOneWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=False)
        self.client = browser_client(self, lims.app)

    def tearDown(self):
        self.tmp.cleanup()

    def setup_admin(self):
        response = self.client.post("/setup", data={
            "display_name": "系统管理员", "password": "safe-pass-123",
            "standard_password": "standard-pass-123",
            "admin_password": "terminal-admin-123",
        })
        self.assertEqual(302, response.status_code)
        db = sqlite3.connect(lims.DB)
        try:
            terminal_id = db.execute(
                "SELECT id FROM terminals WHERE kind='admin'").fetchone()[0]
        finally:
            db.close()
        response = self.client.post("/login", data={
            "terminal_id": terminal_id, "password": "terminal-admin-123",
        })
        self.assertEqual(302, response.status_code)

    def create_sample(self, name="真实流程样品"):
        meta = self.client.get("/api/meta").get_json()
        aid = next(item["id"] for item in meta["analytes"] if item["name"] == "Ag")
        dilution = next(item["id"] for item in meta["dilutions"] if item["active"])
        instrument = next(item for item in meta["instruments"]
                          if item["itype"] == "ppm" and aid in item["analytes"])
        response = self.client.post("/api/samples", json={
            "name": name, "preps": [{
                "name": name + "*1", "mass_g": 1, "volume_ml": 100,
                "dilution_id": dilution, "analyte_ids": [aid],
                "instrument_map": {str(aid): {"instrument_id": instrument["id"]}},
            }],
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response.get_json()

    def test_first_run_setup_login_and_admin_permissions(self):
        self.assertEqual(302, self.client.get("/").status_code)
        self.assertEqual(503, self.client.get("/api/meta").status_code)
        self.setup_admin()
        users = self.client.get("/api/users").get_json()
        self.assertEqual("cxl", users[0]["username"])
        created = self.client.post("/api/users", json={
            "username": "receiver1", "display_name": "收样员甲",
            "password": "receiver-pass", "permissions": ["sample_manage"],
        })
        self.assertEqual(200, created.status_code)
        self.client.post("/logout")
        db = sqlite3.connect(lims.DB)
        try:
            terminal_id = db.execute(
                "SELECT id FROM terminals WHERE kind='standard'").fetchone()[0]
        finally:
            db.close()
        self.client.post("/login", data={
            "terminal_id": terminal_id, "password": "standard-pass-123"})
        self.client.post("/api/authorize", json={"password": "receiver-pass"})
        forbidden = self.client.post("/api/analytes", json={"name": "NoPermission"})
        self.assertEqual(403, forbidden.status_code)

    def test_template_preserves_separate_xrf_method_and_report_items(self):
        self.setup_admin()
        meta = self.client.get("/api/meta").get_json()
        method_id = next(item["id"] for item in meta["methods"] if item["itype"] == "xrf")
        fe_id = next(item["id"] for item in meta["analytes"] if item["name"] == "Fe")
        created = self.client.post("/api/templates", json={
            "name": "仅 XRF 模板", "is_liquid": 0, "xrf": 1,
            "analyte_ids": [], "preps": [{}],
            "instrument_map": {
                "__xrf_method_id": method_id,
                "__xrf_report_items": "Fe, SiO2",
                "__xrf_analyte_ids": [fe_id],
                "__report_order": [],
            },
        })
        self.assertEqual(200, created.status_code, created.get_data(as_text=True))
        template = next(item for item in self.client.get("/api/meta").get_json()["templates"]
                        if item["name"] == "仅 XRF 模板")
        config = json.loads(template["instrument_config"])
        self.assertEqual(method_id, config["__xrf_method_id"])
        self.assertEqual("Fe, SiO2", config["__xrf_report_items"])
        self.assertEqual([fe_id], config["__xrf_analyte_ids"])

    def test_number_status_cancel_and_audit_history(self):
        self.setup_admin()
        first = self.create_sample("样品A")
        second = self.create_sample("样品B")
        self.assertEqual("received", first["status"])
        self.assertRegex(first["lims_no"], r"^\d{8}-001$")
        self.assertTrue(second["lims_no"].endswith("-002"))

        sid = first["id"]
        for status in ("queued", "measuring"):
            response = self.client.put(f"/api/samples/{sid}/status", json={"status": status})
            self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        measuring_sample = self.client.get(f"/api/samples/{sid}").get_json()["sample"]
        self.assertEqual(measuring_sample["status_operator"], measuring_sample["analyst"])
        rolled_back = self.client.put(f"/api/samples/{sid}/status", json={"status": "queued"})
        self.assertEqual(200, rolled_back.status_code, rolled_back.get_data(as_text=True))
        cancelled = self.client.delete(f"/api/samples/{sid}", json={"reason": "客户撤回"})
        self.assertTrue(cancelled.get_json()["cancelled"])
        detail = self.client.get(f"/api/samples/{sid}").get_json()
        self.assertEqual("cancelled", detail["sample"]["status"])
        self.assertEqual("cancelled", detail["sample"]["status_action"])
        self.assertTrue(detail["sample"]["status_operator"])
        self.assertEqual(["received", "queued", "measuring", "queued", "cancelled"],
                         [item["action"] for item in detail["sample"]["status_history"]])
        self.assertTrue(detail["sample"]["status_history"][3]["rollback"])
        self.assertEqual("客户撤回", detail["sample"]["cancel_reason"])
        self.assertTrue(detail["preps"])
        default_list = self.client.get("/api/samples").get_json()
        self.assertNotIn(sid, [sample["id"] for sample in default_list])
        with_cancelled = self.client.get("/api/samples?include_cancelled=1").get_json()
        self.assertIn(sid, [sample["id"] for sample in with_cancelled])
        actions = [row["action"] for row in self.client.get("/api/audit").get_json()]
        self.assertIn("cancel", actions)
        self.assertIn("status_change", actions)

    def test_reviewed_sample_locks_result_writes(self):
        self.setup_admin()
        created = self.create_sample()
        sid = created["id"]
        task = self.client.get(f"/api/samples/{sid}").get_json()["items"][0]
        for status in ("queued", "measuring"):
            response = self.client.put(f"/api/samples/{sid}/status", json={"status": status})
            self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        saved = self.client.post("/api/results", json={
            "sample_analyte_id": task["id"], "raw": 9.5,
        })
        self.assertEqual(200, saved.status_code)
        response = self.client.put(f"/api/samples/{sid}/status", json={"status": "reviewed"})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        reviewed = self.client.get(f"/api/samples/{sid}").get_json()["sample"]
        self.assertEqual(reviewed["status_operator"], reviewed["reviewer"])
        locked = self.client.post("/api/results", json={
            "sample_analyte_id": task["id"], "raw": 10,
        })
        self.assertEqual(409, locked.status_code)
        self.assertEqual(409, self.client.delete(
            f"/api/samples/{sid}", json={"reason": "不允许作废"}).status_code)
        self.assertEqual(400, self.client.put(
            f"/api/samples/{sid}/status", json={"status": "completed"}).status_code)
        authorized = self.client.post("/api/authorize", json={
            "password": "safe-pass-123", "purpose": "result_override",
        })
        self.assertEqual(200, authorized.status_code, authorized.get_data(as_text=True))
        rolled_back = self.client.put(f"/api/samples/{sid}/status", json={
            "status": "completed", "reason": "审核发现异常",
        })
        self.assertEqual(200, rolled_back.status_code, rolled_back.get_data(as_text=True))
        detail = self.client.get(f"/api/samples/{sid}").get_json()["sample"]
        self.assertEqual("completed", detail["status"])
        self.assertEqual("", detail["reviewer"])
        self.assertEqual("审核发现异常", detail["status_history"][-1]["reason"])
        self.assertTrue(detail["status_history"][-1]["rollback"])

    def test_reviewed_sample_composition_and_print_toggle(self):
        self.setup_admin()
        sid = self.create_sample()["id"]
        task = self.client.get(f"/api/samples/{sid}").get_json()["items"][0]
        for status in ("queued", "measuring"):
            self.client.put(f"/api/samples/{sid}/status", json={"status": status})
        self.client.post("/api/results", json={"sample_analyte_id": task["id"], "raw": 9.5})
        reviewed = self.client.put(f"/api/samples/{sid}/status", json={"status": "reviewed"})
        self.assertEqual(200, reviewed.status_code, reviewed.get_data(as_text=True))
        payload = self.client.get(f"/api/report/{sid}").get_json()
        group = payload["groups"][0]
        self.assertTrue(group["print"])

        # 报告编排(顺序/票面/打印选择)在审核后仍可调整；结果参与在审核后锁定。
        self.assertEqual(200, self.client.put(f"/api/samples/{sid}/report-order", json={
            "analyte_ids": [group["analyte_id"]]}).status_code)
        self.assertEqual(200, self.client.put(f"/api/samples/{sid}/report-meta", json={
            "customer": "审核后客户"}).status_code)
        locked = self.client.put(f"/api/sample-analytes/{task['id']}/report-use", json={"use": False})
        self.assertEqual(409, locked.status_code)

        excluded = self.client.put(f"/api/samples/{sid}/report-print", json={
            "excludes": [group["key"], "x:不存在"]})
        self.assertEqual(200, excluded.status_code, excluded.get_data(as_text=True))
        payload = self.client.get(f"/api/report/{sid}").get_json()
        self.assertFalse(payload["groups"][0]["print"])
        self.assertEqual([], payload["default_report_rows"])
        restored = self.client.put(f"/api/samples/{sid}/report-print", json={"excludes": []})
        self.assertEqual(200, restored.status_code)
        payload = self.client.get(f"/api/report/{sid}").get_json()
        self.assertTrue(payload["groups"][0]["print"])
        self.assertEqual(1, len(payload["default_report_rows"]))

    def test_online_backup_is_valid_sqlite_copy(self):
        self.setup_admin()
        self.create_sample()
        target = create_backup(lims.DB, os.path.join(self.tmp.name, "backups"), keep_days=30)
        connection = sqlite3.connect(target)
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
