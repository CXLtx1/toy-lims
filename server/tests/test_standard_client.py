import os
import json
import sqlite3
import tempfile
import time
import unittest

import app as lims
from client_helpers import browser_client
from werkzeug.security import generate_password_hash


class StandardInstrumentClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=True)
        self.client = browser_client(self, lims.app)
        self.meta = self.client.get("/api/meta").get_json()

    def tearDown(self):
        self.tmp.cleanup()

    def create_queued_sample(self):
        analytes = [next(item["id"] for item in self.meta["analytes"] if item["name"] == name)
                    for name in ("Ag", "Cu")]
        instrument = next(item for item in self.meta["instruments"]
                          if item["itype"] == "ppm" and all(aid in item["analytes"] for aid in analytes))
        dilution = next(item["id"] for item in self.meta["dilutions"] if item["active"])
        created = self.client.post("/api/samples", json={
            "name": "标准客户端样品", "preps": [{
                "name": "Ag.标准客户端样品*1", "mass_g": 1, "volume_ml": 100,
                "dilution_id": dilution, "analyte_ids": analytes,
                "instrument_map": {str(aid): {"instrument_id": instrument["id"]}
                                   for aid in analytes},
            }],
        }).get_json()
        sid = created["id"]
        self.client.put(f"/api/samples/{sid}/status", json={"status": "queued"})
        return sid, instrument

    def create_measuring_sample(self):
        sid, instrument = self.create_queued_sample()
        self.client.put(f"/api/samples/{sid}/status", json={"status": "measuring"})
        return sid, instrument

    def test_task_download_atomic_submit_and_idempotent_retry(self):
        sid, instrument = self.create_measuring_sample()
        listed = self.client.get(
            f"/api/instrument/standard/tasks?instrument_id={instrument['id']}")
        self.assertEqual(200, listed.status_code, listed.get_data(as_text=True))
        payload = listed.get_json()
        self.assertEqual([sid], [sample["sample_id"] for sample in payload["samples"]])
        tasks = payload["samples"][0]["tasks"]
        self.assertEqual({"Ag", "Cu"}, {task["analyte"] for task in tasks})
        self.assertTrue(all(task["input_unit"] == "mg/L" for task in tasks))

        submission = {
            "client_id": "ICP-OES-PC", "submission_id": "batch-001",
            "instrument_id": instrument["id"],
            "readings": [{"task_id": task["task_id"], "value": index + 1.25}
                         for index, task in enumerate(tasks)],
        }
        saved = self.client.post("/api/instrument/standard/submit", json=submission)
        self.assertEqual(200, saved.status_code, saved.get_data(as_text=True))
        self.assertEqual(2, len(saved.get_json()["imported"]))

        retried = self.client.post("/api/instrument/standard/submit", json=submission)
        self.assertTrue(retried.get_json()["duplicate"])
        connection = sqlite3.connect(lims.DB)
        try:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0])
        finally:
            connection.close()

        invalid = dict(submission)
        invalid["submission_id"] = "batch-invalid"
        invalid["readings"] = [{"task_id": tasks[0]["task_id"], "value": 9.9},
                               {"task_id": -1, "value": 8.8}]
        rejected = self.client.post("/api/instrument/standard/submit", json=invalid)
        self.assertEqual(409, rejected.status_code)
        connection = sqlite3.connect(lims.DB)
        try:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0])
        finally:
            connection.close()

    def test_mol_instrument_is_available_as_moles_per_liter(self):
        created = self.client.post("/api/instruments", json={
            "name": "摩尔浓度仪", "itype": "mol",
        })
        self.assertEqual(200, created.status_code, created.get_data(as_text=True))
        instruments = self.client.get("/api/instrument/standard/instruments").get_json()["instruments"]
        mol = next(item for item in instruments if item["name"] == "摩尔浓度仪")
        self.assertEqual("mol", mol["itype"])
        self.assertEqual("mol/L", mol["input_unit"])
        task = {"itype": "mol", "prep_factor": 99}
        self.assertEqual((0.025, "mol/L"), lims.reading_value(task, False, 0.025, {}))

    def test_user_login_start_measurement_and_expiry(self):
        sid, instrument = self.create_queued_sample()
        connection = sqlite3.connect(lims.DB)
        try:
            connection.execute("""INSERT INTO users(
                username,password_hash,display_name,role,permissions)
                VALUES(?,?,?,'custom',?)""", (
                    "standard-analyst", generate_password_hash("standard-user-password"),
                    "标准分析员", json.dumps(["result_edit"])))
            connection.commit()
        finally:
            connection.close()
        lims.app.config["AUTH_DISABLED"] = False

        unauthorized = self.client.get(
            f"/api/instrument/standard/tasks?instrument_id={instrument['id']}")
        self.assertEqual(401, unauthorized.status_code)
        rejected = self.client.post("/api/instrument/standard/authorize", json={
            "password": "wrong-password", "client_id": "standard-test-pc",
        })
        self.assertEqual(401, rejected.status_code)

        authorized = self.client.post("/api/instrument/standard/authorize", json={
            "password": "standard-user-password", "client_id": "standard-test-pc",
        })
        self.assertEqual(200, authorized.status_code, authorized.get_data(as_text=True))
        token = authorized.get_json()["token"]
        headers = {"X-User-Authorization": token}
        status = self.client.post("/api/instrument/standard/status", headers=headers, json={
            "client_id": "standard-test-pc", "machine_name": "ICP-PC",
            "version": "1.2.3", "instrument_id": instrument["id"],
        })
        self.assertEqual(200, status.status_code, status.get_data(as_text=True))
        listed = self.client.get(
            f"/api/instrument/standard/tasks?instrument_id={instrument['id']}",
            headers=headers).get_json()
        self.assertEqual("queued", listed["samples"][0]["sample_status"])

        started = self.client.post(f"/api/instrument/standard/samples/{sid}/start",
                                   json={"instrument_id": instrument["id"]}, headers=headers)
        self.assertEqual(200, started.status_code, started.get_data(as_text=True))
        submitted = self.client.post("/api/instrument/standard/submit", headers=headers, json={
            "client_id": "standard-test-pc", "submission_id": "authorized-batch",
            "instrument_id": instrument["id"],
            "readings": [{"task_id": listed["samples"][0]["tasks"][0]["task_id"], "value": 2.5}],
        })
        self.assertEqual(200, submitted.status_code, submitted.get_data(as_text=True))
        touched = self.client.post("/api/instrument/standard/session/touch", json={}, headers=headers)
        self.assertEqual(200, touched.status_code)
        connection = sqlite3.connect(lims.DB)
        try:
            sample = connection.execute(
                "SELECT status,analyst,status_operator FROM samples WHERE id=?", (sid,)).fetchone()
            self.assertEqual(("partially_done", "标准分析员", "标准分析员"), sample)
            audit = connection.execute("""SELECT username FROM audit_logs
                WHERE action='status_change' AND entity_type='sample' AND entity_id=?
                ORDER BY id DESC LIMIT 1""", (str(sid),)).fetchone()
            self.assertEqual("standard-analyst", audit[0])
            reading_audit = connection.execute("""SELECT username FROM audit_logs
                WHERE action='instrument_reading' ORDER BY id DESC LIMIT 1""").fetchone()
            self.assertEqual("standard-analyst", reading_audit[0])
            connection.execute("UPDATE standard_client_sessions SET last_activity=?",
                               (time.time() - 601,))
            connection.commit()
        finally:
            connection.close()

        expired = self.client.get(
            f"/api/instrument/standard/tasks?instrument_id={instrument['id']}", headers=headers)
        self.assertEqual(401, expired.status_code)
        self.assertEqual("user_authorization_required", expired.get_json()["code"])
        lims.app.config["AUTH_DISABLED"] = True
        site_status = self.client.get("/api/site-status").get_json()
        self.assertGreater(site_status["revision"], 0)
        monitor = self.client.get("/api/xrf/monitor").get_json()
        standard_client = monitor["standard_clients"][0]
        self.assertEqual("ICP-PC", standard_client["machine_name"])
        self.assertEqual("127.0.0.1", standard_client["network_position"])
        self.assertEqual("标准分析员", standard_client["display_name"])
        self.assertEqual(1, standard_client["recent_entry"]["count"])
        self.assertIn("2.5", standard_client["recent_entry"]["items"][0])

if __name__ == "__main__":
    unittest.main()
