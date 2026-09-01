import os
import sqlite3
import tempfile
import unittest

import app as lims


class XrfMonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=True)
        self.client = lims.app.test_client()
        self.meta = self.client.get("/api/meta").get_json()

    def tearDown(self):
        self.tmp.cleanup()

    def create_xrf_sample(self, name="矿石-XRF"):
        method_id = next(m["id"] for m in self.meta["methods"] if m["name"] == "WUNI0820")
        response = self.client.post("/api/samples", json={
            "name": name, "xrf": 1, "xrf_method_id": method_id,
            "xrf_report_items": "Fe,Al,Fe2O3,Al2O3",
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response.get_json()["id"]

    def import_analysis(self, sid=None, analysis_id="9001", batch="B-2026-08",
                        sample_name=None):
        if sid is not None and sample_name is None:
            sample = self.client.get(f"/api/samples/{sid}").get_json()["sample"]
            sample_name = sample["lims_no"]
        payload = {
            "analysis_id": analysis_id,
            "oxsas_sample_name": sample_name or "UNREGISTERED-9001",
            "method": "WUNI0820", "batch": batch,
            "analyzed_at": "2026-08-28T10:20:30",
            "results": [
                {"name": "Fe", "value": 42.5},
                {"name": "Al", "value": 8.1},
                {"name": "Si", "value": 3.2},
            ],
        }
        if sid is not None:
            payload["sample_id"] = sid
        return self.client.post("/api/instrument/xrf/import", json=payload)

    def assign_analysis(self, analysis_id, sample_id):
        response = self.client.put(f"/api/xrf/analyses/{analysis_id}/sample",
                                   json={"sample_id": sample_id})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response.get_json()

    @staticmethod
    def uq_payload(sample_name, processed=True):
        return {
            "general_id": "48", "job_id": "621", "sample_name": sample_name,
            "method": "X_UQ_FULL", "analyzed_at": "2026-08-28T11:30:00",
            "processed": processed,
            "options": {"chemistry": 1, "shape": "pellet", "atmosphere": 0,
                        "kappas": "AnySample", "report_level": 10,
                        "remark": "UQ key options remark"},
            "job": {"stripped_oxygen": 1},
            "results": [
                {"name": "Fe2O3", "value": 55.5},
                {"name": "Al2O3", "value": 12.25},
            ],
        }

    def oxide_factor(self, formula):
        reference = self.client.get("/api/xrf/reference").get_json()
        return next(oxide["element_to_oxide_factor"] for oxide in reference["oxides"]
                    if oxide["formula"] == formula)

    def set_targets(self, sid, targets):
        response = self.client.put(f"/api/xrf/samples/{sid}/targets",
                                   json={"targets": targets})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response.get_json()

    def test_status_heartbeat_upserts_and_audits_changes_only(self):
        payload = {
            "machine_name": "XRF-PC", "version": "1.0.0", "state": "reading",
            "current": {"sample": "LIMS-001", "method": "WUNI0820", "batch": "B-1",
                        "run_id": "48:621:1556", "position": "106",
                        "started_at": "2026-08-28 16:13:14"},
            "message": "测量中",
        }
        self.assertTrue(self.client.post("/api/instrument/xrf/status", json=payload).get_json()["ok"])
        self.assertTrue(self.client.post("/api/instrument/xrf/status", json=payload).get_json()["ok"])
        client = self.client.get("/api/xrf/monitor").get_json()["client"]
        self.assertEqual("XRF-PC", client["machine_name"])
        self.assertEqual("reading", client["state"])
        self.assertEqual("48:621:1556", client["current_run_id"])
        self.assertTrue(client["online"])
        heartbeats = [a for a in self.client.get("/api/audit?limit=50").get_json()
                      if a["action"] == "heartbeat"]
        self.assertEqual(1, len(heartbeats))
        changed = dict(payload)
        changed["state"] = "idle"
        self.client.post("/api/instrument/xrf/status", json=changed)
        heartbeats = [a for a in self.client.get("/api/audit?limit=50").get_json()
                      if a["action"] == "heartbeat"]
        self.assertEqual(2, len(heartbeats))

    def test_unknown_state_falls_back_to_idle(self):
        self.client.post("/api/instrument/xrf/status", json={
            "machine_name": "XRF-PC", "state": "flying",
        })
        client = self.client.get("/api/xrf/monitor").get_json()["client"]
        self.assertEqual("idle", client["state"])

    def test_import_requires_manual_assignment_and_lists_unified_scan(self):
        sid = self.create_xrf_sample()
        body = self.import_analysis(sid).get_json()
        self.assertTrue(body["ok"], body)
        self.assertFalse(body["matched"])
        self.assertTrue(body["manual_assignment_required"])
        self.assertIsNone(body["sample_id"])
        self.assertEqual([], self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"])
        self.assign_analysis(body["analysis_id"], sid)
        sample_results = self.client.get(f"/api/xrf/samples/{sid}").get_json()
        self.assertEqual("B-2026-08", sample_results["analyses"][0]["batch"])
        self.assertEqual(["Fe", "Al", "Si"],
                         [value["name"] for value in sample_results["analyses"][0]["values"]])
        monitor = self.client.get("/api/xrf/monitor").get_json()
        self.assertEqual(1, monitor["total"])
        row = monitor["scans"][0]
        self.assertEqual("quant", row["kind"])
        self.assertEqual(3, row["value_count"])
        self.assertIn("Fe 42.5%", row["top_values"])
        self.assertEqual([], self.client.get("/api/instrument/xrf/tasks").get_json()["samples"])

    def test_unregistered_ordinary_scan_stays_unlinked_until_manual_assignment(self):
        first = self.import_analysis(sample_name="UNREGISTERED-9001").get_json()
        self.assertTrue(first["ok"])
        self.assertFalse(first["matched"])
        scan = self.client.get("/api/xrf/monitor?match=unmatched").get_json()["scans"][0]
        self.assertEqual("UNREGISTERED-9001", scan["sample_name"])
        self.assertIsNone(scan["sample_id"])
        sid = self.create_xrf_sample("UNREGISTERED-9001")
        second = self.import_analysis(sample_name="UNREGISTERED-9001").get_json()
        self.assertTrue(second["duplicate"])
        self.assertIsNone(second["sample_id"])
        self.assertEqual(1, self.client.get("/api/xrf/monitor?match=unmatched").get_json()["total"])
        self.assign_analysis(second["analysis_id"], sid)
        self.assertEqual(1, self.client.get("/api/xrf/monitor?match=matched").get_json()["total"])

    def test_monitor_empty_state(self):
        monitor = self.client.get("/api/xrf/monitor").get_json()
        self.assertTrue(monitor["ok"])
        self.assertIsNone(monitor["client"])
        self.assertEqual([], monitor["scans"])
        self.assertEqual(0, monitor["total"])

    def test_unprocessed_uq_is_ignored(self):
        sid = self.create_xrf_sample("TY260900")
        response = self.client.post("/api/instrument/xrf/uq/import",
                                    json=self.uq_payload("TY260900 -  ", processed=False))
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["skipped"])
        self.assertFalse(body["processed"])
        self.assertEqual([], self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"])
        self.assertEqual(0, self.client.get("/api/xrf/monitor").get_json()["total"])

    def test_processed_uq_uses_final_named_composition_without_channels_or_film(self):
        sid = self.create_xrf_sample("TY260910")
        payload = self.uq_payload("TY260910 -   (1)")
        body = self.client.post("/api/instrument/xrf/uq/import", json=payload).get_json()
        self.assertTrue(body["processed"], body)
        self.assertEqual("TY260910", body["normalized_sample_name"])
        self.assertIsNone(body["sample_id"])
        self.assertEqual(["Fe2O3", "Al2O3"], [item["name"] for item in body["imported"]])
        self.assign_analysis(body["analysis_id"], sid)
        analyses = self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"]
        self.assertEqual("OXSAS-UniQuant", analyses[0]["source"])
        self.assertEqual("uq", analyses[0]["kind"])
        self.assertNotIn("Film", analyses[0]["remark"])
        self.assertEqual({"Fe2O3", "Al2O3"}, {value["name"] for value in analyses[0]["values"]})
        monitor = self.client.get("/api/xrf/monitor?kind=uq").get_json()
        self.assertEqual(1, monitor["total"])
        scan = monitor["scans"][0]
        self.assertTrue(scan["oxide"])
        self.assertNotIn("channels", scan)
        self.assertNotIn("film", {item["label"].casefold() for item in scan["option_details"]})

    def test_uq_idempotent_reimport_replaces_final_values(self):
        sid = self.create_xrf_sample("TY260920")
        payload = self.uq_payload("TY260920")
        first = self.client.post("/api/instrument/xrf/uq/import", json=payload).get_json()
        self.assign_analysis(first["analysis_id"], sid)
        payload["results"] = [{"name": "Fe2O3", "value": 61.25}]
        payload["options"]["remark"] = "recalculated"
        second = self.client.post("/api/instrument/xrf/uq/import", json=payload).get_json()
        self.assertEqual(first["analysis_id"], second["analysis_id"])
        self.assertTrue(second["duplicate"])
        analyses = self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"]
        self.assertEqual(1, len(analyses))
        self.assertTrue(analyses[0]["remark"].startswith("recalculated；"))
        self.assertEqual([61.25], [value["value"] for value in analyses[0]["values"]])

    def test_monitor_search_filters_and_paginates_unified_scans(self):
        self.import_analysis(analysis_id="1", sample_name="ALPHA")
        self.import_analysis(analysis_id="2", sample_name="BETA")
        uq = self.uq_payload("GAMMA")
        self.client.post("/api/instrument/xrf/uq/import", json=uq)
        found = self.client.get("/api/xrf/monitor?q=beta&kind=quant&match=unmatched&limit=10").get_json()
        self.assertEqual(1, found["total"])
        self.assertEqual("BETA", found["scans"][0]["sample_name"])
        uq_found = self.client.get("/api/xrf/monitor?kind=uq&limit=10").get_json()
        self.assertEqual(1, uq_found["total"])
        self.assertEqual("uq", uq_found["scans"][0]["kind"])

    def test_batch_import_and_sync_state(self):
        analyses = []
        for analysis_id in (10, 11):
            analyses.append({
                "analysis_id": analysis_id, "oxsas_sample_name": f"RAW-{analysis_id}",
                "method": "WUNI0820", "results": [{"name": "Fe", "value": analysis_id}],
            })
        batch = self.client.post("/api/instrument/xrf/import/batch",
                                 json={"analyses": analyses}).get_json()
        self.assertTrue(batch["ok"])
        self.assertEqual(2, batch["imported"])
        uq = self.uq_payload("UQ-RAW")
        uq["general_id"] = "52"
        self.client.post("/api/instrument/xrf/uq/import/batch", json={"analyses": [uq]})
        state = self.client.get("/api/instrument/xrf/sync-state").get_json()
        self.assertEqual(11, state["ordinary_after"])
        self.assertEqual(52, state["uq_after_general"])
        self.assertEqual(["10", "11"], state["ordinary_ids"])
        self.assertEqual(["52:621"], state["uq_ids"])

    def test_manual_assignment_applies_defaults_rejects_second_sample_and_audits(self):
        sid = self.create_xrf_sample("MANUAL-XRF-1")
        other_sid = self.create_xrf_sample("MANUAL-XRF-2")
        imported = self.import_analysis(sid, sample_name="DIFFERENT-NAME").get_json()
        assigned = self.assign_analysis(imported["analysis_id"], sid)
        self.assertEqual(sid, assigned["sample_id"])
        values = self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"][0]["values"]
        selected = {value["name"] for value in values if value["use_report"]}
        self.assertEqual({"Fe", "Al"}, selected)
        conflict = self.client.put(f"/api/xrf/analyses/{imported['analysis_id']}/sample",
                                   json={"sample_id": other_sid})
        self.assertEqual(409, conflict.status_code)
        connection = sqlite3.connect(lims.DB)
        connection.execute("UPDATE samples SET status='reviewed' WHERE id=?", (other_sid,))
        connection.commit()
        connection.close()
        second = self.import_analysis(analysis_id="9002", sample_name="MANUAL-XRF-2").get_json()
        locked = self.client.put(f"/api/xrf/analyses/{second['analysis_id']}/sample",
                                 json={"sample_id": other_sid})
        self.assertEqual(409, locked.status_code)
        audits = self.client.get("/api/audit?limit=50").get_json()
        self.assertTrue(any(item["action"] == "xrf_assign" for item in audits))

    def test_sample_accepts_one_scan_and_unassign_allows_replacement(self):
        sid = self.create_xrf_sample("SINGLE-XRF")
        first = self.import_analysis(analysis_id="9101", sample_name="FIRST").get_json()
        second = self.import_analysis(analysis_id="9102", sample_name="SECOND").get_json()
        self.assign_analysis(first["analysis_id"], sid)
        duplicate = self.client.put(f"/api/xrf/analyses/{second['analysis_id']}/sample",
                                    json={"sample_id": sid})
        self.assertEqual(409, duplicate.status_code)
        self.assertIn("请先解绑", duplicate.get_json()["error"])
        available = self.client.get("/api/samples?xrf=1&xrf_available=1").get_json()
        self.assertNotIn(sid, {sample["id"] for sample in available})

        unassigned = self.client.delete(f"/api/xrf/analyses/{first['analysis_id']}/sample")
        self.assertEqual(200, unassigned.status_code, unassigned.get_data(as_text=True))
        self.assertEqual([], self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"])
        available = self.client.get("/api/samples?xrf=1&xrf_available=1").get_json()
        self.assertIn(sid, {sample["id"] for sample in available})
        scan = next(item for item in self.client.get("/api/xrf/monitor").get_json()["scans"]
                    if item["id"] == first["analysis_id"])
        self.assertFalse(any(value["use_report"] for value in scan["values"]))
        self.assign_analysis(second["analysis_id"], sid)
        analyses = self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"]
        self.assertEqual([second["analysis_id"]], [analysis["id"] for analysis in analyses])
        audits = self.client.get("/api/audit?limit=50").get_json()
        self.assertTrue(any(item["action"] == "xrf_unassign" for item in audits))

    def test_startup_keeps_newest_duplicate_xrf_assignment(self):
        sid = self.create_xrf_sample("DUPLICATE-XRF")
        connection = sqlite3.connect(lims.DB)
        connection.execute("DROP INDEX uq_xrf_analysis_sample")
        first_id = connection.execute(
            "INSERT INTO xrf_analyses(sample_id,external_id) VALUES(?,?)", (sid, "OLD-XRF")).lastrowid
        second_id = connection.execute(
            "INSERT INTO xrf_analyses(sample_id,external_id) VALUES(?,?)", (sid, "NEW-XRF")).lastrowid
        connection.execute("INSERT INTO xrf_values(analysis_id,name,value,use_report) VALUES(?,?,?,1)",
                           (first_id, "Fe", 1.0))
        connection.commit()
        connection.close()

        lims.init_db()
        connection = sqlite3.connect(lims.DB)
        assignments = dict(connection.execute(
            "SELECT id,sample_id FROM xrf_analyses WHERE id IN (?,?)", (first_id, second_id)))
        old_use = connection.execute(
            "SELECT use_report FROM xrf_values WHERE analysis_id=?", (first_id,)).fetchone()[0]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(xrf_analyses)")}
        connection.close()
        self.assertIsNone(assignments[first_id])
        self.assertEqual(sid, assignments[second_id])
        self.assertEqual(0, old_use)
        self.assertIn("uq_xrf_analysis_sample", indexes)

    def test_legacy_sqlite_xrf_table_migrates_to_nullable_sample(self):
        connection = sqlite3.connect(lims.DB)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA legacy_alter_table=ON")
        connection.executescript("""ALTER TABLE xrf_analyses RENAME TO xrf_analyses_current;
            CREATE TABLE xrf_analyses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
                external_id TEXT NOT NULL,method TEXT DEFAULT '',batch TEXT DEFAULT '',
                analyzed_at TEXT,source TEXT DEFAULT 'OXSAS',kind TEXT DEFAULT '',
                remark TEXT DEFAULT '',options_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(source,external_id));
            DROP TABLE xrf_analyses_current;""")
        connection.close()
        lims.init_db()
        connection = sqlite3.connect(lims.DB)
        sample_id = next(row for row in connection.execute("PRAGMA table_info(xrf_analyses)")
                         if row[1] == "sample_id")
        self.assertEqual(0, sample_id[3])
        self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))
        connection.close()

    def test_historical_xrf_values_cleanup_and_rounding(self):
        sid = self.create_xrf_sample("HIST-1")
        response = self.import_analysis(sid)
        self.assertTrue(response.get_json()["ok"])
        self.assign_analysis(response.get_json()["analysis_id"], sid)
        connection = sqlite3.connect(lims.DB)
        analysis_id = connection.execute(
            "SELECT id FROM xrf_analyses WHERE external_id='9001'").fetchone()[0]
        connection.execute("INSERT INTO xrf_values(analysis_id,name,value,use_report) VALUES(?,?,?,1)",
                           (analysis_id, "BgNoise", 3696.964111328125))
        connection.execute("UPDATE xrf_values SET value=? WHERE analysis_id=? AND name='Fe'",
                           (35.20061785459892, analysis_id))
        connection.commit()
        connection.close()
        lims.init_db()
        monitor = self.client.get("/api/xrf/monitor").get_json()
        scan = monitor["scans"][0]
        self.assertEqual(3, scan["value_count"])
        self.assertEqual(["Fe", "Al", "Si"], [v["name"] for v in scan["values"]])
        self.assertEqual([35.201, 8.1, 3.2], [v["value"] for v in scan["values"]])
        self.assertEqual(["Fe 35.201%", "Al 8.1%", "Si 3.2%"], scan["top_values"])
        report = self.client.get(f"/api/report/{sid}").get_json()
        iron = next(group for group in report["groups"] if group["analyte"] == "Fe")
        self.assertEqual(35.201, iron["rows"][0]["value"])
        self.assertEqual(35.201, iron["final"]["value"])

    def test_targets_derive_from_report_items_and_convert_missing_oxide(self):
        method_id = next(m["id"] for m in self.meta["methods"] if m["name"] == "WUNI0820")
        response = self.client.post("/api/samples", json={
            "name": "氧化物口径", "xrf": 1, "xrf_method_id": method_id,
            "xrf_report_items": "SiO2,CaO",
        })
        sid = response.get_json()["id"]
        imported = self.import_analysis(sid).get_json()
        self.assign_analysis(imported["analysis_id"], sid)
        targets = self.client.get(f"/api/xrf/samples/{sid}").get_json()["targets"]
        self.assertEqual([("si", "SiO2"), ("ca", "CaO")],
                         [(target["family"], target["target"]) for target in targets])
        report = self.client.get(f"/api/report/{sid}").get_json()
        silica = next(group for group in report["groups"] if group["analyte"] == "SiO2")
        self.assertEqual(6.8458, round(silica["final"]["value"], 4))
        self.assertEqual("converted", silica["rows"][0]["xrf_resolution"]["via"])
        self.assertEqual("Si", silica["rows"][0]["xrf_resolution"]["source"])
        self.assertEqual(round(3.2 * self.oxide_factor("SiO2"), 4),
                         round(silica["final"]["value"], 4))
        self.assertFalse(any(group["analyte"] == "Al" for group in report["groups"]))

    def test_uq_name_pair_keeps_alternate_name_for_conversion(self):
        method_id = next(m["id"] for m in self.meta["methods"] if m["name"] == "WUNI0820")
        response = self.client.post("/api/samples", json={
            "name": "名称对", "xrf": 1, "xrf_method_id": method_id,
            "xrf_report_items": "Fe2O3",
        })
        sid = response.get_json()["id"]
        payload = self.uq_payload("UQ-PAIR")
        payload["results"] = [{"name": "Fe2O3", "value": 55.5,
                               "element_name": "Fe", "oxide_name": "Fe2O3"}]
        imported = self.client.post("/api/instrument/xrf/uq/import", json=payload).get_json()
        self.assign_analysis(imported["analysis_id"], sid)
        analyses = self.client.get(f"/api/xrf/samples/{sid}").get_json()["analyses"]
        self.assertEqual("Fe", analyses[0]["values"][0]["alt_name"])
        self.set_targets(sid, [{"family": "fe", "target": "Fe", "include": True}])
        report = self.client.get(f"/api/report/{sid}").get_json()
        iron = next(group for group in report["groups"] if group["analyte"] == "Fe")
        self.assertEqual(round(55.5 / self.oxide_factor("Fe2O3"), 3),
                         round(iron["final"]["value"], 3))
        self.assertEqual("Fe2O3", iron["rows"][0]["xrf_resolution"]["source"])

    def test_targets_endpoint_validates_duplicates_and_audits(self):
        sid = self.create_xrf_sample("TARGETS-1")
        body = self.set_targets(sid, [
            {"family": "fe", "target": "Fe2O3", "include": True},
            {"family": "si", "target": "SiO2", "include": False},
        ])
        self.assertEqual([("fe", "Fe2O3", 1), ("si", "SiO2", 0)],
                         [(target["family"], target["target"], target["include"])
                          for target in body["targets"]])
        sample = self.client.get(f"/api/xrf/samples/{sid}").get_json()["sample"]
        self.assertEqual("Fe2O3", sample["xrf_report_items"])
        duplicate = self.client.put(f"/api/xrf/samples/{sid}/targets", json={
            "targets": [{"family": "fe", "target": "Fe2O3"},
                        {"family": "fe", "target": "Fe"}]})
        self.assertEqual(400, duplicate.status_code)
        audits = self.client.get("/api/audit?limit=100").get_json()
        self.assertTrue(any(item["action"] == "xrf_targets_update" for item in audits))

    def test_consistency_warning_for_independent_oxide_and_element(self):
        sid = self.create_xrf_sample("CONSIST-1")
        connection = sqlite3.connect(lims.DB)
        analysis_id = connection.execute(
            "INSERT INTO xrf_analyses(sample_id,external_id,method) VALUES(?,?, 'WUNI0820')",
            (sid, "CONSIST-SCAN")).lastrowid
        for name, value in (("Fe", 40.0), ("Fe2O3", 50.0)):
            connection.execute(
                "INSERT INTO xrf_values(analysis_id,name,value,use_report) VALUES(?,?,?,1)",
                (analysis_id, name, value))
        connection.commit()
        connection.close()
        self.set_targets(sid, [{"family": "fe", "target": "Fe2O3", "include": True}])
        report = self.client.get(f"/api/report/{sid}").get_json()
        iron = next(group for group in report["groups"] if group["analyte"] == "Fe2O3")
        self.assertEqual(50.0, iron["final"]["value"])
        self.assertEqual("direct", iron["rows"][0]["xrf_resolution"]["via"])
        warnings = [warning for warning in report["xrf_warnings"]
                    if warning["code"] == "composition_mismatch"]
        self.assertEqual(1, len(warnings))
        self.assertIn("相对偏差", warnings[0]["message"])


if __name__ == "__main__":
    unittest.main()
