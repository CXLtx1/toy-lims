import sqlite3
import unittest
from datetime import datetime

from flask import Flask, g

from api import overview, samples


class TestOverview(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE samples (
                id INTEGER PRIMARY KEY, name TEXT, lims_no TEXT, category TEXT DEFAULT '',
                is_liquid INTEGER DEFAULT 0, is_water_quality INTEGER DEFAULT 0,
                workflow_type TEXT DEFAULT 'regular', xrf INTEGER DEFAULT 0,
                status TEXT DEFAULT 'received', created_at TEXT, customer TEXT DEFAULT '',
                analysis_date TEXT DEFAULT '', analyst TEXT DEFAULT '', reviewer TEXT DEFAULT '');
            CREATE TABLE instruments (
                id INTEGER PRIMARY KEY, name TEXT, itype TEXT, sort_order INTEGER DEFAULT 0);
            CREATE TABLE sample_analytes (
                id INTEGER PRIMARY KEY, sample_id INTEGER, analyte_id INTEGER DEFAULT 1,
                instrument_id INTEGER, status TEXT DEFAULT 'pending');
            CREATE TABLE analytes (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE readings (id INTEGER PRIMARY KEY, sample_analyte_id INTEGER, raw REAL);
            CREATE TABLE sample_tags (sample_id INTEGER, tag TEXT);
            CREATE TABLE preparations (id INTEGER PRIMARY KEY, sample_id INTEGER);
            CREATE TABLE xrf_analyses (id INTEGER PRIMARY KEY, sample_id INTEGER, kind TEXT);
            CREATE TABLE result_order_templates (
                id INTEGER PRIMARY KEY, items_json TEXT, is_default INTEGER);
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY, created_at TEXT, username TEXT, action TEXT,
                entity_type TEXT, entity_id TEXT, reason TEXT, before_json TEXT,
                after_json TEXT, ip_address TEXT, terminal_name TEXT);
            INSERT INTO analytes VALUES (1, 'Fe');
        """)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(overview.bp, url_prefix="/api")
        app.register_blueprint(samples.bp, url_prefix="/api")

        @app.before_request
        def inject_db():
            g.db = self.db
            self.db.execute("PRAGMA query_only=ON")

        @app.teardown_request
        def reset_read_only(exc):
            self.db.execute("PRAGMA query_only=OFF")

        self.client = app.test_client()

    def get(self, path, **params):
        response = self.client.get(path, query_string=params)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def seed_workload(self):
        self.db.executemany("INSERT INTO instruments VALUES (?,?,?,?)", [
            (1, "ICP", "ppm", 2), (2, "Balance", "percent", 1), (3, "XRF", "xrf", 3),
        ])
        self.db.executemany("INSERT INTO samples(id,name,status,xrf) VALUES (?,?,?,?)", [
            (1, "A", "measuring", 1), (2, "B", "queued", 1),
            (3, "C", "reviewed", 1), (4, "D", "cancelled", 1),
            (5, "E", "reported", 1), (6, "F", "completed", 1),
            (7, "G", "received", 0), (8, "H", "received", 0),
        ])
        self.db.executemany("""INSERT INTO sample_analytes(id,sample_id,instrument_id,status)
            VALUES (?,?,?,?)""", [
            (1, 1, 1, "pending"), (2, 1, 1, "pending"), (3, 1, 1, "completed"),
            (4, 1, 1, "cancelled"), (5, 2, 1, "in_progress"),
            (6, 3, 1, "pending"), (7, 4, 1, "pending"), (8, 5, 1, "pending"),
            (9, 1, 2, "completed"), (10, 2, 2, "pending"),
            (11, 1, None, "pending"), (12, 1, None, "pending"),
            (13, 1, None, "completed"), (14, 2, None, "cancelled"),
            (15, 3, None, "pending"), (16, 4, None, "pending"), (17, 5, None, "pending"),
        ])
        self.db.executemany("INSERT INTO readings(sample_analyte_id,raw) VALUES (?,?)",
                            [(task, value) for task in range(1, 18) for value in range(4)])
        self.db.executemany("INSERT INTO xrf_analyses(sample_id,kind) VALUES (?,?)", [
            (1, "quant"), (1, "uq"), (1, "uq"), (4, "quant"), (7, "uq"), (None, "quant"),
        ])
        self.db.execute("INSERT INTO sample_tags VALUES (1,'priority')")
        self.db.execute("INSERT INTO preparations(sample_id) VALUES (1)")

    def test_empty_overview_and_zero_station(self):
        data = self.get("/api/overview")
        self.assertEqual(set(data), {"ok", "generated_at", "samples", "instruments",
                                     "unassigned", "xrf", "recent_audits"})
        self.assertTrue(data["ok"])
        self.assertIsNotNone(datetime.fromisoformat(data["generated_at"]).tzinfo)
        self.assertEqual(data["samples"], {"total": 0, "by_status": {}})
        self.assertEqual(data["instruments"], [])
        self.assertEqual(data["unassigned"], {"open_tasks": 0, "open_samples": 0})
        self.assertEqual(data["xrf"], {"requested_samples": 0, "awaiting_scan": 0, "linked_samples": 0})
        self.assertEqual(data["recent_audits"], {"items": [], "has_more": False, "next_before_id": None})
        self.db.execute("INSERT INTO instruments VALUES (1,'Idle','ppm',0)")
        self.assertEqual(self.get("/api/overview")["instruments"], [{
            "id": 1, "name": "Idle", "itype": "ppm", "task_total": 0,
            "completed": 0, "open_tasks": 0, "open_samples": 0,
        }])

    def test_task_counts_exclude_closed_work_without_reading_multiplication(self):
        self.seed_workload()
        data = self.get("/api/overview")
        self.assertEqual(data["samples"], {"total": 8, "by_status": {
            "measuring": 1, "queued": 1, "reviewed": 1, "cancelled": 1,
            "reported": 1, "completed": 1, "received": 2,
        }})
        self.assertEqual([row["id"] for row in data["instruments"]], [2, 1, 3])
        self.assertEqual(data["instruments"][1], {
            "id": 1, "name": "ICP", "itype": "ppm", "task_total": 8,
            "completed": 1, "open_tasks": 3, "open_samples": 2,
        })
        self.assertEqual(data["instruments"][0], {
            "id": 2, "name": "Balance", "itype": "percent", "task_total": 2,
            "completed": 1, "open_tasks": 1, "open_samples": 1,
        })
        self.assertEqual(data["unassigned"], {"open_tasks": 2, "open_samples": 1})
        self.assertEqual(data["xrf"], {"requested_samples": 6, "awaiting_scan": 2, "linked_samples": 3})
        self.assertEqual(data["instruments"][2]["task_total"], 0)

    def test_null_statuses_use_schema_defaults(self):
        self.db.execute("INSERT INTO samples(id,name,status,xrf) VALUES (1,'A',NULL,1)")
        self.db.execute("INSERT INTO sample_analytes(sample_id,status) VALUES (1,NULL)")
        data = self.get("/api/overview")
        self.assertEqual(data["samples"], {"total": 1, "by_status": {"received": 1}})
        self.assertEqual(data["unassigned"], {"open_tasks": 1, "open_samples": 1})
        self.assertEqual(data["xrf"]["awaiting_scan"], 1)
        registered = self.get("/api/samples", status="received")
        self.assertEqual(registered["total"], 1)
        self.assertEqual(registered["items"][0]["status"], "received")

    def test_audit_keyset_and_safe_exact_fields(self):
        self.db.executemany("""INSERT INTO audit_logs VALUES
            (?,NULL,'operator','create','sample',?,NULL,'secret-before','secret-after','private-ip','terminal')""",
                            [(10, "1"), (30, "2"), (50, "scan:abc")])
        first = self.get("/api/overview/audits", limit=2)
        self.assertEqual(set(first), {"ok", "items", "has_more", "next_before_id"})
        self.assertEqual([row["id"] for row in first["items"]], [50, 30])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_before_id"], 30)
        self.assertEqual(first["items"][0], {
            "id": 50, "created_at": None, "username": "operator", "action": "create",
            "action_label": samples._AUDIT_ACTION_LABELS["create"], "entity_type": "sample",
            "entity_id": "scan:abc", "entity_label": samples._AUDIT_ENTITY_LABELS["sample"], "reason": "",
        })
        self.db.execute("""INSERT INTO audit_logs(id,created_at,action,entity_type)
            VALUES (60,'2026-09-07 12:00:00','future_action','future_entity')""")
        last = self.get("/api/overview/audits", limit=2, before_id=first["next_before_id"])
        self.assertEqual([row["id"] for row in last["items"]], [10])
        self.assertFalse(last["has_more"])
        self.assertIsNone(last["next_before_id"])
        empty = self.get("/api/overview/audits", before_id=10)
        self.assertEqual(empty, {"ok": True, "items": [], "has_more": False, "next_before_id": None})
        newest = self.get("/api/overview/audits")["items"][0]
        self.assertEqual(newest["action_label"], "future_action")
        self.assertEqual(newest["entity_label"], "future_entity")
        self.assertEqual(newest["entity_id"], "")
        self.assertEqual(newest["username"], "")
        self.assertEqual(newest["created_at"], "2026-09-07 12:00:00")

    def test_audit_default_limit_cap_and_exact_page_boundary(self):
        self.db.executemany("INSERT INTO audit_logs(id,action,entity_type) VALUES (?,'update','sample')",
                            [(i,) for i in range(1, 106)])
        first = self.get("/api/overview/audits")
        self.assertEqual(len(first["items"]), 30)
        self.assertEqual(first["next_before_id"], 76)
        self.assertEqual(self.get("/api/overview")["recent_audits"],
                         {key: value for key, value in first.items() if key != "ok"})
        capped = self.get("/api/overview/audits", limit=101)
        self.assertEqual(len(capped["items"]), 100)
        self.assertEqual(capped["next_before_id"], 6)
        last = self.get("/api/overview/audits", limit=5, before_id=6)
        self.assertEqual(len(last["items"]), 5)
        self.assertFalse(last["has_more"])
        self.assertIsNone(last["next_before_id"])

    def test_invalid_integer_parameters_return_json_400(self):
        for path, param in [("/api/overview/audits", "before_id"),
                            ("/api/overview/audits", "limit"), ("/api/samples", "instrument_id")]:
            for value in ("", " ", "abc", "1.5", "0", "-1", "1e2", "1_0", "1 OR 1=1",
                          "9223372036854775808", "9" * 5000):
                with self.subTest(param=param, value=value[:30]):
                    response = self.client.get(path, query_string={param: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertFalse(response.get_json()["ok"])
                    self.assertIsInstance(response.get_json()["error"], str)

    def test_sample_filter_and_batched_enrichment_preserve_list(self):
        self.seed_workload()
        data = self.get("/api/samples", instrument_id=1)
        self.assertEqual((data["total"], data["page"], data["per_page"]), (5, 1, 30))
        self.assertEqual([row["id"] for row in data["items"]], [5, 4, 3, 2, 1])
        sample = data["items"][-1]
        self.assertEqual((sample["task_total"], sample["task_completed"], sample["instrument_ids"]),
                         (8, 3, [1, 2]))
        self.assertEqual(sample["tags"], ["priority"])
        self.assertEqual(sample["analytes"], ["Fe"])
        self.assertEqual(sample["prep_count"], 1)
        self.assertEqual(sample["xrf_scan_count"], 3)
        filtered = self.get("/api/samples", instrument_id=1, status="measuring", tag="priority")
        self.assertEqual(filtered["total"], 1)
        page = self.get("/api/samples", instrument_id=1, per_page=2, page=2)
        self.assertEqual(page["total"], 5)
        self.assertEqual([row["id"] for row in page["items"]], [3, 2])
        self.assertEqual(self.get("/api/samples", instrument_id=999)["items"], [])
        unfiltered = self.get("/api/samples")
        self.assertEqual(unfiltered["total"], 8)
        empty = unfiltered["items"][0]
        self.assertEqual((empty["task_total"], empty["task_completed"], empty["instrument_ids"]), (0, 0, []))
        queries = []
        self.db.set_trace_callback(queries.append)
        self.get("/api/samples", per_page=1)
        single_count = len(queries)
        queries.clear()
        self.get("/api/samples", per_page=100)
        self.assertEqual(len(queries), single_count)


if __name__ == "__main__":
    unittest.main()
