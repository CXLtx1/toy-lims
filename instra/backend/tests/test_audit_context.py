import json
import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask, g, render_template_string

from api import audit_context, samples


class TestAuditContext(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY, created_at TEXT, username TEXT, action TEXT,
                entity_type TEXT, entity_id TEXT, before_json TEXT, after_json TEXT,
                reason TEXT, ip_address TEXT, terminal_name TEXT);
            CREATE TABLE samples (id INTEGER PRIMARY KEY, name TEXT, lims_no TEXT, status TEXT);
            CREATE TABLE sample_analytes (
                id INTEGER PRIMARY KEY, sample_id INTEGER, analyte_id INTEGER,
                preparation_id INTEGER, instrument_id INTEGER, method_id INTEGER, status TEXT);
            CREATE TABLE analytes (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE preparations (
                id INTEGER PRIMARY KEY, sample_id INTEGER, name TEXT, mass_g REAL, volume_ml REAL);
            CREATE TABLE instruments (id INTEGER PRIMARY KEY, name TEXT, itype TEXT);
            CREATE TABLE methods (id INTEGER PRIMARY KEY, name TEXT, formula TEXT, constants TEXT);
            CREATE TABLE results (sample_analyte_id INTEGER PRIMARY KEY, raw REAL, extra TEXT, aux TEXT);
            CREATE TABLE readings (id INTEGER PRIMARY KEY, sample_analyte_id INTEGER,
                raw REAL, extra TEXT DEFAULT '{}', use_avg INTEGER DEFAULT 1, is_final INTEGER DEFAULT 0);
            CREATE TABLE xrf_analyses (id INTEGER PRIMARY KEY, sample_id INTEGER);
            CREATE TABLE xrf_values (id INTEGER PRIMARY KEY, analysis_id INTEGER);
            INSERT INTO samples VALUES (1,'Sample A','LIMS-001','measuring'), (2,'Other','LIMS-002','received');
            INSERT INTO analytes VALUES (1,'Fe');
            INSERT INTO preparations VALUES (1,1,'Digest A',0.5,100), (2,1,'Digest B',1,50);
            INSERT INTO instruments VALUES (1,'ICP','ppm'), (2,'ICP-MS','ppb');
            INSERT INTO sample_analytes VALUES
                (10,1,1,1,1,NULL,'pending'), (20,1,1,1,1,NULL,'completed'),
                (30,1,1,1,1,NULL,'pending'), (40,1,1,1,1,NULL,'pending'),
                (19,1,1,2,1,NULL,'pending'), (21,1,1,1,2,NULL,'pending'),
                (22,2,1,1,1,NULL,'pending');
            INSERT INTO results VALUES (20,999,'{}','{"use":true,"expected":10,"measured":5}');
            INSERT INTO readings(id,sample_analyte_id,raw,use_avg,is_final) VALUES
                (100,20,111,1,0), (101,20,7,0,1), (102,20,222,1,0),
                (103,10,10,1,0), (104,30,30,1,0), (105,40,40,1,0);
        """)
        self.before = {"id": 101, "sample_analyte_id": 20, "raw": 0, "extra": "{}", "use_avg": 1}
        self.after = {**self.before, "raw": None}
        self.event()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(audit_context.bp, url_prefix="/api")
        self.app.register_blueprint(samples.bp, url_prefix="/api")

        @self.app.before_request
        def inject_db():
            g.db = self.db
            self.db.execute("PRAGMA query_only=ON")

        @self.app.teardown_request
        def reset_read_only(exc):
            self.db.execute("PRAGMA query_only=OFF")

        self.client = self.app.test_client()

    def event(self, before=None, after=None, entity_id="101", entity_type="reading", action="update"):
        self.db.execute("""INSERT OR REPLACE INTO audit_logs VALUES
            (1,'2026-09-08 10:00:00','operator',?,?,?,?,?,'private-reason','private-ip','terminal')""",
            (action, entity_type, entity_id,
             json.dumps(self.before if before is None else before),
             json.dumps(self.after if after is None else after)))

    def load(self, aid=1):
        self.db.execute("PRAGMA query_only=ON")
        try:
            return audit_context.load_context(self.db, aid)
        finally:
            self.db.execute("PRAGMA query_only=OFF")

    def unsupported(self, reason):
        data = self.load()
        self.assertEqual(set(data), {"ok", "supported", "reason", "audit"})
        self.assertTrue(data["ok"])
        self.assertFalse(data["supported"])
        self.assertIn(reason, data["reason"])
        return data

    def test_exact_payload_zero_null_and_correct_parallel_reading(self):
        data = self.load()
        self.assertEqual(set(data), {"ok", "supported", "audit", "sample", "locator", "values", "rows", "warnings"})
        self.assertTrue(data["supported"])
        self.assertEqual(data["audit"], {"id": 1, "created_at": "2026-09-08 10:00:00",
                                       "username": "operator", "action_label": samples._AUDIT_ACTION_LABELS["update"]})
        self.assertEqual(data["sample"], {"id": 1, "name": "Sample A", "lims_no": "LIMS-001", "status": "measuring"})
        self.assertEqual(data["locator"], {"sample_id": 1, "sample_analyte_id": 20, "reading_id": 101, "field": "raw"})
        self.assertEqual(data["values"], {"before": {"available": True, "value": 0},
                                         "after": {"available": True, "value": None},
                                         "current": {"available": True, "value": 7}})
        self.assertEqual([row["id"] for row in data["rows"]], [10, 20, 30])
        target = data["rows"][1]
        self.assertEqual(set(target), {"id", "sample_id", "analyte", "prep_name", "instrument", "itype",
                                       "method_name", "formula", "method_constants", "prep_mass", "prep_vol",
                                       "raw", "extra", "aux", "status", "readings"})
        self.assertEqual(target["raw"], 999)
        self.assertEqual(target["readings"][1], {"id": 101, "sample_analyte_id": 20, "raw": 7,
                                                "extra": "{}", "use_avg": False, "is_final": True})
        self.assertEqual([rd["raw"] for rd in target["readings"]], [111, 7, 222])
        self.assertTrue(all(isinstance(warning, str) for warning in data["warnings"]))
        text = " ".join(data["warnings"])
        for expected in ("CURRENT", "units", "old method is not recorded", "no historical whole state",
                         "not necessarily the original visual neighbors"):
            self.assertIn(expected, text)

    def test_current_zero_and_blank_are_available(self):
        for raw in (0, None):
            with self.subTest(raw=raw):
                self.db.execute("UPDATE readings SET raw=? WHERE id=101", (raw,))
                self.assertEqual(self.load()["values"]["current"], {"available": True, "value": raw})

    def test_only_raw_updates_are_supported(self):
        for entity_type, action in (("sample", "update"), ("sample_analyte", "result_update"),
                                    ("reading", "create"), ("reading", "delete"), ("reading", "instrument_reading")):
            with self.subTest(entity_type=entity_type, action=action):
                self.event(entity_type=entity_type, action=action)
                self.unsupported("Only plain reading raw updates")
        for change in ({"aux": {"expected": 3}}, {"extra": '{"V":2}'}, {"use_avg": 0}, {"raw": 0.0}):
            self.event(after={**self.before, **change})
            self.unsupported("do not change raw")

    def test_missing_and_malformed_snapshots_are_not_blank(self):
        for bad in (None, "", "{", "null", "[]", '"text"', "false", "[" * 1100):
            for column in ("before_json", "after_json"):
                with self.subTest(bad=str(bad)[:20], column=column):
                    self.event()
                    self.db.execute(f"UPDATE audit_logs SET {column}=? WHERE id=1", (bad,))
                    self.unsupported("Both snapshots must contain raw")
        for snapshot in ({"id": 101, "sample_analyte_id": 20}, {}):
            self.event(before=snapshot)
            self.unsupported("Both snapshots must contain raw")

    def test_invalid_raw_scalars_do_not_leak_or_serialize_nonfinite(self):
        for raw in ({"secret": "hidden"}, [1], True, "0", float("nan"), float("inf"), -float("inf"), 10 ** 400):
            with self.subTest(raw=str(raw)[:30]):
                self.event(after={**self.after, "raw": raw})
                data = self.unsupported("finite number or explicit null")
                self.assertNotIn("hidden", json.dumps(data, allow_nan=False))

    def test_invalid_entity_ids_do_not_cast_or_fall_back_to_snapshot(self):
        for rid in (None, "", "0", "-1", "00101", " 101", "101.0", "1e2", "101 OR 1=1", "101x",
                    "9223372036854775808", "9" * 5000, "\u0661\u0660\u0661"):
            with self.subTest(rid=str(rid)[:30]):
                self.event(entity_id=rid)
                self.unsupported("positive 64-bit integer")

    def test_snapshot_ids_and_parents_must_agree(self):
        for key, bad in (("id", 100), ("id", None), ("id", True), ("id", 101.0), ("id", {}),
                         ("sample_analyte_id", 10), ("sample_analyte_id", None),
                         ("sample_analyte_id", True), ("sample_analyte_id", "20x"),
                         ("sample_id", 2), ("sample_id", None)):
            for side in ("before", "after"):
                with self.subTest(key=key, bad=bad, side=side):
                    snapshot = {**getattr(self, side), key: bad}
                    self.event(**{side: snapshot})
                    self.assertFalse(self.load()["supported"])
        self.event(before={"raw": 0}, after={"raw": 1})
        self.unsupported("Snapshot task parents")

    def test_numeric_string_snapshot_ids_are_resolved_safely(self):
        self.event(before={**self.before, "id": "101", "sample_analyte_id": "20", "sample_id": "1"})
        self.assertTrue(self.load()["supported"])

    def test_deleted_target_has_only_a_marked_blank_placeholder(self):
        self.db.execute("DELETE FROM readings WHERE id=101")
        data = self.load()
        self.assertTrue(data["supported"])
        self.assertEqual(data["values"]["current"], {"available": False, "value": None})
        self.assertEqual(data["values"]["before"], {"available": True, "value": 0})
        self.assertEqual(data["rows"][1]["readings"][1], {
            "id": 101, "sample_analyte_id": 20, "raw": None, "extra": "{}",
            "use_avg": False, "is_final": False, "historical_placeholder": True})
        self.assertIn("target reading is gone", " ".join(data["warnings"]))

    def test_reassigned_target_refuses_false_context(self):
        for parent in (10, 22, 999):
            self.db.execute("UPDATE readings SET sample_analyte_id=? WHERE id=101", (parent,))
            self.unsupported("reassigned")

    def test_deleted_task_or_sample_and_missing_analyte_refuse(self):
        self.db.execute("DELETE FROM samples WHERE id=1")
        self.unsupported("sample is missing or deleted")
        self.db.execute("INSERT INTO samples VALUES (1,'Sample A','LIMS-001','measuring')")
        self.db.execute("DELETE FROM analytes")
        self.unsupported("analyte is missing")
        self.db.execute("DELETE FROM sample_analytes WHERE id=20")
        self.unsupported("task is missing or deleted")

    def test_current_instrument_must_be_known_plain_raw_type(self):
        for itype in ("function", "xrf", "", None, "unknown", 'ppm" onmouseover="bad'):
            self.db.execute("UPDATE instruments SET itype=? WHERE id=1", (itype,))
            self.unsupported("not assigned to plain raw entry")
        self.db.execute("UPDATE sample_analytes SET instrument_id=NULL WHERE id=20")
        self.unsupported("not assigned to plain raw entry")
        self.db.execute("UPDATE sample_analytes SET instrument_id=999 WHERE id=20")
        self.unsupported("not assigned to plain raw entry")

    def test_formula_raw_is_unsupported(self):
        self.db.execute("INSERT INTO methods VALUES (1,'Formula','V/m','{}')")
        self.db.execute("UPDATE sample_analytes SET method_id=1 WHERE id=20")
        self.unsupported("not assigned to plain raw entry")
        self.db.execute("UPDATE sample_analytes SET method_id=NULL WHERE id=20")
        for extra in ({"itype": "function"}, {"formula": "V/m"}):
            self.event(before={**self.before, **extra})
            self.unsupported("Snapshot context is not a plain raw")

    def test_all_plain_raw_types_supported(self):
        for itype in ("ppm", "ppb", "mol", "percent", "ph"):
            self.db.execute("UPDATE instruments SET itype=? WHERE id=1", (itype,))
            self.assertTrue(self.load()["supported"])

    def test_neighbors_boundaries_null_prep_and_readings_are_batched(self):
        queries = []
        self.db.set_trace_callback(queries.append)
        self.load()
        select_count = sum(sql.lstrip().upper().startswith("SELECT") for sql in queries)
        reading_batches = [sql for sql in queries if "FROM readings WHERE sample_analyte_id IN" in sql]
        self.assertEqual(len(reading_batches), 1)
        self.db.execute("UPDATE sample_analytes SET preparation_id=NULL WHERE id IN (20,30,40)")
        queries.clear()
        data = self.load()
        self.assertEqual([row["id"] for row in data["rows"]], [20, 30, 40])
        self.assertEqual(sum(sql.lstrip().upper().startswith("SELECT") for sql in queries), select_count)
        self.db.execute("DELETE FROM sample_analytes WHERE id!=20")
        queries.clear()
        self.assertEqual(len(self.load()["rows"]), 1)
        self.assertEqual(sum(sql.lstrip().upper().startswith("SELECT") for sql in queries), select_count)

    def test_current_raw_and_json_fields_are_sanitized(self):
        attack = '\" autofocus onfocus=alert(1) x=\"'
        self.db.execute("UPDATE readings SET raw=?,extra=? WHERE id=101", (attack, '{"V":"secret","m":2,"bad":NaN}'))
        self.db.execute("UPDATE results SET raw=?,extra=?,aux=? WHERE sample_analyte_id=20",
                        (float("inf"), "[]", json.dumps({"use": True, "expected": attack, "measured": 2, "secret": "hidden"})))
        data = self.load()
        self.assertEqual(data["values"]["current"], {"available": False, "value": None})
        target = data["rows"][1]
        self.assertIsNone(target["raw"])
        self.assertEqual(json.loads(target["aux"]), {"use": True, "measured": 2})
        self.assertEqual(target["extra"], "{}")
        self.assertEqual(json.loads(target["readings"][1]["extra"]), {"m": 2})
        text = json.dumps(data, allow_nan=False)
        self.assertNotIn(attack, text)
        self.assertNotIn("hidden", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("historical_placeholder", target["readings"][1])

    def test_malformed_json_fields_do_not_crash_renderer(self):
        self.db.execute("INSERT INTO methods VALUES (1,'Current method','','{}')")
        self.db.execute("UPDATE sample_analytes SET method_id=1 WHERE id=20")
        for value in (None, "{", "null", "[]", '"text"', "false", "[" * 1100):
            with self.subTest(value=str(value)[:20]):
                self.db.execute("UPDATE methods SET constants=?", (value,))
                self.db.execute("UPDATE readings SET extra=?", (value,))
                self.db.execute("UPDATE results SET extra=?,aux=?", (value, value))
                row = self.load()["rows"][1]
                for key in ("extra", "aux", "method_constants"):
                    self.assertEqual(json.loads(row[key]), {})
                self.assertTrue(all(json.loads(rd["extra"]) == {} for rd in row["readings"]))

    def test_load_and_http_are_read_only_and_get_only(self):
        changes = self.db.total_changes
        denied = []

        def guard(action, arg1, arg2, database, trigger):
            if action not in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_PRAGMA}:
                denied.append(action)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.db.set_authorizer(guard)
        self.assertTrue(self.load()["supported"])
        self.assertEqual(self.client.get("/api/audits/1/context").status_code, 200)
        with patch.object(audit_context, "render_template", return_value="scene"):
            self.assertEqual(self.client.get("/api/audits/1/scene").status_code, 200)
        for endpoint in ("context", "scene"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                self.assertEqual(self.client.open(f"/api/audits/1/{endpoint}", method=method).status_code, 405)
        self.db.set_authorizer(None)
        self.assertEqual(denied, [])
        self.assertEqual(self.db.total_changes, changes)

    def test_missing_audit_and_oversize_route_id_are_404(self):
        self.assertEqual(self.load(999), {"ok": False, "error": "Audit not found."})
        for endpoint in ("context", "scene"):
            for aid in (999, 0, 9223372036854775808):
                response = self.client.get(f"/api/audits/{aid}/{endpoint}")
                self.assertEqual(response.status_code, 404)
                self.assertFalse(response.get_json()["ok"])

    def test_scene_modes_nonce_csp_and_unavailable_conflict(self):
        nonces = set()
        with patch.object(audit_context, "render_template", return_value="scene") as render:
            for mode in ("before", "after", "current"):
                response = self.client.get("/api/audits/1/scene", query_string={"mode": mode})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(render.call_args.args, ("audit_scene.html",))
                context = render.call_args.kwargs
                self.assertEqual(context["mode"], mode)
                self.assertEqual(context["scene"], self.load())
                nonce = context["nonce"]
                self.assertRegex(nonce, r"^[A-Za-z0-9_-]+$")
                nonces.add(nonce)
                csp = response.headers["Content-Security-Policy"]
                for directive in ("default-src 'none'", f"script-src 'nonce-{nonce}' 'self'",
                                  "style-src 'self' 'unsafe-inline'", "connect-src 'none'",
                                  "form-action 'none'", "base-uri 'none'", "frame-ancestors 'self'"):
                    self.assertIn(directive, csp)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(len(nonces), 3)
            self.client.get("/api/audits/1/scene")
            self.assertEqual(render.call_args.kwargs["mode"], "before")
            self.db.execute("DELETE FROM readings WHERE id=101")
            self.assertEqual(self.client.get("/api/audits/1/scene?mode=current").status_code, 409)
            self.assertFalse(render.call_args.kwargs["scene"]["values"]["current"]["available"])
            self.assertEqual(self.client.get("/api/audits/1/scene?mode=after").status_code, 200)

    def test_scene_invalid_mode_and_unsupported_have_no_false_locators(self):
        with patch.object(audit_context, "render_template", return_value="unsupported") as render:
            for mode in ("", "BEFORE", "invalid", '<script>alert(1)</script>'):
                response = self.client.get("/api/audits/1/scene", query_string={"mode": mode})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
            render.assert_not_called()
            self.event(action="delete")
            response = self.client.get("/api/audits/1/scene")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(render.call_args.kwargs["scene"]["supported"])
            self.assertNotIn("locator", render.call_args.kwargs["scene"])

    def test_public_payload_omits_snapshots_secrets_and_can_be_safely_embedded(self):
        attack = '</script><img src=x onerror=alert(1)>'
        self.event(before={**self.before, "password": "snapshot-secret", "nested": {"ip": "snapshot-ip"}})
        self.db.execute("UPDATE samples SET name=? WHERE id=1", (attack,))
        self.db.execute("UPDATE analytes SET name=?", (attack,))
        response = self.client.get("/api/audits/1/context")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.get_json()["sample"]["name"], attack)
        for secret in ("snapshot-secret", "snapshot-ip", "private-ip", "private-reason", "before_json", "after_json"):
            self.assertNotIn(secret, response.get_data(as_text=True))

        def render_stub(template, **context):
            return render_template_string('<p>{{ scene.sample.name }}</p><script nonce="{{ nonce }}">'
                                          'const scene = {{ scene|tojson }};</script>', **context)

        with patch.object(audit_context, "render_template", side_effect=render_stub):
            html = self.client.get("/api/audits/1/scene").get_data(as_text=True)
            self.assertNotIn(attack, html)
            self.assertIn(r"\u003c/script\u003e", html)
            self.assertIn("&lt;/script&gt;", html)

    def test_sample_audit_preserves_fields_and_adds_structured_locators(self):
        self.db.executemany("INSERT INTO audit_logs(id,entity_type,entity_id,action) VALUES (?,'reading',?,'update')",
                            [(2, "not-numeric"), (3, "9" * 5000), (4, "101x")])
        response = self.client.get("/api/samples/1/audit")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["entity_type"], "reading")
        self.assertEqual(item["entity_id"], "101")
        self.assertEqual(set(item), {"id", "created_at", "username", "terminal_name", "ip_address",
                                     "action", "action_label", "entity_type", "entity_id", "entity_label",
                                     "reason", "changes", "has_snapshot"})
        self.assertEqual(item["changes"][0]["field"], "raw")
        self.assertEqual(set(item["changes"][0]), {"field", "label", "before", "after"})
        self.assertEqual(item["ip_address"], "private-ip")
        self.assertTrue(item["has_snapshot"])


if __name__ == "__main__":
    unittest.main()
