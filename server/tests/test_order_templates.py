import os
import sqlite3
import tempfile
import unittest

import app as lims


class UniversalOrderTemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=False)
        self.client = lims.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def setup_admin(self):
        response = self.client.post("/setup", data={
            "display_name": "管理员", "password": "safe-pass-123",
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

    def meta(self):
        return self.client.get("/api/meta").get_json()

    def analyte_id(self, name):
        return next(item["id"] for item in self.meta()["analytes"] if item["name"] == name)

    def instrument_id(self, aid):
        return next(item["id"] for item in self.meta()["instruments"]
                    if item["itype"] == "ppm" and aid in item["analytes"])

    def create_sample(self, name, analytes=("Cu", "Ag", "Pb"), order_template_id=None):
        preps = []
        for index, analyte in enumerate(analytes, 1):
            aid = self.analyte_id(analyte)
            preps.append({
                "name": f"{analyte}.{name}*1", "mass_g": 1, "volume_ml": 100,
                "dilution_id": self.meta()["dilutions"][0]["id"], "analyte_ids": [aid],
                "instrument_map": {str(aid): {"instrument_id": self.instrument_id(aid)}},
            })
        payload = {"name": name, "preps": preps}
        if order_template_id is not None:
            payload["order_template_id"] = order_template_id
        response = self.client.post("/api/samples", json=payload)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response.get_json()["id"]

    def test_default_order_template_is_seeded(self):
        self.setup_admin()
        meta = self.meta()
        default_id = meta["default_order_template_id"]
        self.assertIsNotNone(default_id)
        default = next(item for item in meta["result_order_templates"]
                       if item["id"] == default_id)
        self.assertTrue(default["is_default"])
        self.assertIn("Fe", default["items"])

    def test_new_sample_gets_default_template_and_sorted_detail(self):
        self.setup_admin()
        sid = self.create_sample("排序样品", analytes=("Zn", "Cu", "Ag"))
        detail = self.client.get(f"/api/samples/{sid}").get_json()
        sample = detail["sample"]
        self.assertEqual(self.meta()["default_order_template_id"],
                         sample["order_template_id"])
        names = [item["analyte"] for item in detail["items"]]
        self.assertEqual(["Cu", "Zn", "Ag"], names)

    def test_sample_template_carries_order_template(self):
        self.setup_admin()
        meta = self.meta()
        custom = self.client.post("/api/result-order-templates", json={
            "name": "铜优先", "items": ["Cu", "Ag", "Pb"],
        }).get_json()
        aid = self.analyte_id("Cu")
        created = self.client.post("/api/templates", json={
            "name": "带顺序模板", "is_liquid": 0, "xrf": 0,
            "analyte_ids": [aid], "preps": [{}],
            "instrument_map": {}, "order_template_id": custom["id"],
        })
        self.assertEqual(200, created.status_code, created.get_data(as_text=True))
        template = next(item for item in self.meta()["templates"]
                        if item["name"] == "带顺序模板")
        self.assertEqual(custom["id"], template["order_template_id"])

    def test_report_group_order_follows_sample_template(self):
        self.setup_admin()
        custom = self.client.post("/api/result-order-templates", json={
            "name": "铅铜银", "items": ["Pb", "Cu", "Ag"],
        }).get_json()
        sid = self.create_sample("报告排序", analytes=("Ag", "Cu", "Pb"),
                                 order_template_id=custom["id"])
        groups = self.client.get(f"/api/report/{sid}").get_json()["groups"]
        self.assertEqual(["Pb", "Cu", "Ag"],
                         [group["analyte"] for group in groups])

    def test_report_order_endpoint_updates_template(self):
        self.setup_admin()
        custom = self.client.post("/api/result-order-templates", json={
            "name": "银铅铜", "items": ["Ag", "Pb", "Cu"],
        }).get_json()
        sid = self.create_sample("切换模板")
        response = self.client.put(f"/api/samples/{sid}/report-order", json={
            "order_template_id": custom["id"], "analyte_ids": [],
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        sample = self.client.get(f"/api/samples/{sid}").get_json()["sample"]
        self.assertEqual(custom["id"], sample["order_template_id"])
        groups = self.client.get(f"/api/report/{sid}").get_json()["groups"]
        self.assertEqual(["Ag", "Pb", "Cu"],
                         [group["analyte"] for group in groups])

    def test_manual_report_order_still_overrides(self):
        self.setup_admin()
        sid = self.create_sample("手工微调", analytes=("Cu", "Ag", "Pb"))
        response = self.client.put(f"/api/samples/{sid}/report-order", json={
            "analyte_ids": [self.analyte_id("Pb"), self.analyte_id("Cu"),
                            self.analyte_id("Ag")],
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        groups = self.client.get(f"/api/report/{sid}").get_json()["groups"]
        self.assertEqual(["Pb", "Cu", "Ag"],
                         [group["analyte"] for group in groups])
        cleared = self.client.put(f"/api/samples/{sid}/report-order", json={
            "analyte_ids": []})
        self.assertEqual(200, cleared.status_code)
        groups = self.client.get(f"/api/report/{sid}").get_json()["groups"]
        self.assertEqual(["Cu", "Ag", "Pb"],
                         [group["analyte"] for group in groups])

    def test_unknown_items_append_after_template(self):
        self.setup_admin()
        custom = self.client.post("/api/result-order-templates", json={
            "name": "只有铜", "items": ["Cu"],
        }).get_json()
        sid = self.create_sample("追加顺序", analytes=("Zn", "Cu", "Ag"),
                                 order_template_id=custom["id"])
        groups = self.client.get(f"/api/report/{sid}").get_json()["groups"]
        self.assertEqual(["Cu", "Zn", "Ag"],
                         [group["analyte"] for group in groups])

    def test_default_template_cannot_be_deleted(self):
        self.setup_admin()
        default_id = self.meta()["default_order_template_id"]
        response = self.client.delete(f"/api/result-order-templates/{default_id}")
        self.assertEqual(409, response.status_code)
        self.assertIsNotNone(self.meta()["default_order_template_id"])

    def test_update_template_can_become_default(self):
        self.setup_admin()
        custom = self.client.post("/api/result-order-templates", json={
            "name": "新默认", "items": ["Cu"],
        }).get_json()
        response = self.client.put(f"/api/result-order-templates/{custom['id']}", json={
            "name": "新默认", "items": ["Cu"], "is_default": True,
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        meta = self.meta()
        self.assertEqual(custom["id"], meta["default_order_template_id"])
        old_default = next(item for item in meta["result_order_templates"]
                           if item["name"] == "系统默认")
        self.assertFalse(old_default["is_default"])


if __name__ == "__main__":
    unittest.main()
