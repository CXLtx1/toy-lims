"""Reliable-write contracts against an isolated PostgreSQL schema, never app.init_db."""

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import app as lims
from client_helpers import BrowserClient, browser_client
from db_schema import SCHEMA, initialize_database
from mutation_guard import lock_reading, next_updated_at, reading_version
from postgres_case import PostgresTestCase


class MutationGuardTest(PostgresTestCase):
    def setUp(self):
        self.provision_database(lims)
        lims.app.config.update(TESTING=True, AUTH_DISABLED=False)
        db = self.connect()
        try:
            db.execute("INSERT INTO users(id,username,password_hash,display_name,permissions) "
                       "VALUES(1,'reader','unused','Reader','[]')")
            db.execute("INSERT INTO terminals(id,name,password_hash,kind) VALUES(1,'browser-a','unused','admin')")
            db.execute("INSERT INTO terminals(id,name,password_hash,kind) VALUES(2,'browser-b','unused','admin')")
            db.execute("INSERT INTO analytes(id,name) VALUES(1,'Ag')")
            db.execute("INSERT INTO instruments(id,name,itype) VALUES(1,'ICP','ppm')")
            db.execute("INSERT INTO samples(id,name,status,updated_at) "
                       "VALUES(1,'Sample','measuring','2026-01-01 00:00:00')")
            db.execute("INSERT INTO sample_analytes(id,sample_id,analyte_id,instrument_id) VALUES(1,1,1,1)")
            db.commit()
        finally:
            db.close()
        self.client = browser_client(self, lims.app)
        self.other = BrowserClient(lims.app, lims.app.response_class)
        for terminal_id, client in enumerate((self.client, self.other), 1):
            with client.session_transaction() as session:
                session["terminal_id"] = terminal_id
                session["session_token"] = ""

    def query(self, sql, params=()):
        db = self.connect()
        try:
            result = [dict(row) for row in db.execute(sql, params).fetchall()]
            db.commit()
            return result
        finally:
            db.close()

    def snapshot(self):
        return {table: self.query(f"SELECT * FROM {table}") for table in (
            "samples", "sample_analytes", "results", "readings", "reading_create_requests", "audit_logs")}

    def create(self, **values):
        payload = {"sample_analyte_id": 1, "client_reading_id": str(uuid4()), "raw": 12.5, **values}
        response = self.client.post("/api/readings", json=payload)
        self.assertEqual(200, response.status_code, response.json)
        return payload, response.json

    def detail(self):
        response = self.client.get("/api/samples/1")
        self.assertEqual(200, response.status_code, response.json)
        return response.json

    def assert_conflict_unchanged(self, call, code="version_conflict"):
        before = self.snapshot()
        response = call()
        self.assertEqual(409, response.status_code, response.json)
        if code is not None:
            self.assertEqual(code, response.json["code"])
        self.assertFalse(response.json["ok"])
        self.assertEqual(before, self.snapshot())

    def test_initial_create_and_detail_expose_stored_version(self):
        _, created = self.create(extra={"V": 4}, use_avg=False, is_final=True)
        row = self.detail()["items"][0]["readings"][0]
        self.assertEqual(created["id"], row["id"])
        self.assertEqual(12.5, row["raw"])
        self.assertEqual({"V": 4}, json.loads(row["extra"]))
        self.assertEqual((0, 1), (row["use_avg"], row["is_final"]))
        self.assertRegex(created["version"], r"^[0-9a-f]{64}$")
        self.assertEqual(created["version"], row["version"])
        self.assertEqual(reading_version(row), row["version"])
        self.assertEqual(row, self.detail()["items"][0]["readings"][0])

    def test_version_covers_every_mutable_field_and_no_unrelated_fields(self):
        row = {"raw": 1.0, "extra": "{}", "use_avg": 1, "is_final": 0}
        original = reading_version(row)
        self.assertEqual(original, reading_version({**row, "id": 999}))
        for field, value in (("raw", 2.0), ("extra", '{"V":1}'), ("use_avg", 0), ("is_final", 1)):
            self.assertNotEqual(original, reading_version({**row, field: value}))

    def test_replay_is_persisted_and_does_not_duplicate_audit_or_change_progress(self):
        payload, created = self.create(extra={"b": 2, "a": 1})
        before = self.snapshot()
        replay = self.other.post("/api/readings", json={**payload, "extra": {"a": 1, "b": 2}})
        self.assertEqual(200, replay.status_code, replay.json)
        self.assertEqual({**created, "replayed": True}, replay.json)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(1, len(before["audit_logs"]))
        self.assertEqual(1, len(before["reading_create_requests"]))

    def test_changed_key_payload_rejected_for_all_mutable_fields_and_task(self):
        payload, _ = self.create()
        for field, value in (("raw", 2), ("extra", {"V": 4}), ("use_avg", False),
                             ("is_final", True), ("sample_analyte_id", 99)):
            with self.subTest(field=field):
                self.assert_conflict_unchanged(lambda: self.other.post(
                    "/api/readings", json={**payload, field: value}), "idempotency_conflict")

    def test_replay_after_update_returns_original_version_not_permission_to_overwrite(self):
        payload, created = self.create()
        url = f"/api/readings/{created['id']}"
        updated = self.other.put(url, json={"raw": 44, "expected_version": created["version"]})
        self.assertEqual(200, updated.status_code)
        replay = self.client.post("/api/readings", json=payload)
        self.assertEqual(created["version"], replay.json["version"])
        self.assert_conflict_unchanged(lambda: self.client.put(url, json={
            "raw": 20, "expected_version": replay.json["version"]}))

    def test_replay_after_delete_and_cascade_cannot_resurrect_reading(self):
        for cascade in (False, True):
            payload, created = self.create()
            if cascade:
                self.query("DELETE FROM sample_analytes WHERE id=1")
            else:
                response = self.client.delete(f"/api/readings/{created['id']}",
                                              json={"expected_version": created["version"]})
                self.assertEqual(200, response.status_code)
            self.assert_conflict_unchanged(lambda: self.other.post("/api/readings", json=payload))

    def test_stale_put_and_delete_leave_readings_siblings_progress_and_audit_unchanged(self):
        _, first = self.create(is_final=True)
        _, second = self.create()
        url = f"/api/readings/{second['id']}"
        updated = self.client.put(url, json={"raw": 2, "expected_version": second["version"]})
        self.assertEqual(200, updated.status_code)
        self.assertNotEqual(second["version"], updated.json["version"])
        self.assert_conflict_unchanged(lambda: self.other.put(url, json={
            "raw": 3, "is_final": True, "expected_version": second["version"]}))
        self.assert_conflict_unchanged(lambda: self.other.delete(url, json={"expected_version": second["version"]}))
        self.assertEqual(1, self.query("SELECT is_final FROM readings WHERE id=%s", (first["id"],))[0]["is_final"])
        deleted = self.other.delete(url, json={"expected_version": updated.json["version"]})
        self.assertEqual(200, deleted.status_code)
        self.assert_conflict_unchanged(lambda: self.other.delete(url, json={"expected_version": updated.json["version"]}))
        self.assert_conflict_unchanged(lambda: self.other.put(url, json={"raw": 1, "expected_version": updated.json["version"]}))

    def test_final_selection_invalidates_displaced_sibling_version(self):
        _, first = self.create(is_final=True)
        self.create(is_final=True)
        row = self.query("SELECT * FROM readings WHERE id=%s", (first["id"],))[0]
        self.assertEqual(0, row["is_final"])
        self.assertNotEqual(first["version"], reading_version(row))
        self.assert_conflict_unchanged(lambda: self.client.put(f"/api/readings/{first['id']}", json={
            "is_final": True, "expected_version": first["version"]}))

    def test_create_put_delete_with_defaults_remains_supported(self):
        created = self.client.post("/api/readings", json={"sample_analyte_id": 1})
        self.assertEqual(200, created.status_code)
        row = self.query("SELECT * FROM readings")[0]
        self.assertEqual((None, "{}", 1, 0), (row["raw"], row["extra"], row["use_avg"], row["is_final"]))
        url = f"/api/readings/{created.json['id']}"
        self.assertEqual(200, self.client.put(url, json={"raw": 3}).status_code)
        self.assertEqual(200, self.client.delete(url).status_code)
        self.assertEqual(404, self.client.delete(url).status_code)
        self.assertEqual([], self.query("SELECT * FROM reading_create_requests"))

    def test_invalid_create_does_not_reserve_key(self):
        for value in (None, "", "not-a-uuid", 12, {}, str(uuid4()).replace("-", "")):
            response = self.client.post("/api/readings", json={"sample_analyte_id": 1, "client_reading_id": value})
            self.assertEqual(400, response.status_code, response.json)
        for field, value in (("raw", "bad"), ("raw", float("inf")), ("extra", []), ("extra", {"V": float("nan")})):
            response = self.client.post("/api/readings", json={"sample_analyte_id": 1, "client_reading_id": str(uuid4()), field: value})
            self.assertEqual(400, response.status_code, response.json)
        self.assertEqual([], self.query("SELECT * FROM reading_create_requests"))
        self.assertEqual([], self.query("SELECT * FROM readings"))

    def test_rejected_workflow_rolls_back_key_and_reading(self):
        payload = {"sample_analyte_id": 1, "client_reading_id": str(uuid4()), "raw": 1}
        self.query("UPDATE samples SET status='reviewed' WHERE id=1")
        self.assert_conflict_unchanged(lambda: self.client.post("/api/readings", json=payload), code=None)
        self.query("UPDATE samples SET status='measuring' WHERE id=1")
        self.assertEqual(200, self.client.post("/api/readings", json=payload).status_code)

    def test_failed_audit_rolls_back_create_and_allows_retry(self):
        payload = {"sample_analyte_id": 1, "client_reading_id": str(uuid4()), "raw": 1}
        before = self.snapshot()
        with patch.object(lims, "audit_event", side_effect=RuntimeError("audit failure")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/readings", json=payload)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(200, self.client.post("/api/readings", json=payload).status_code)

    def test_authentication_and_capability_are_required_even_for_replays(self):
        payload, created = self.create()
        anonymous = BrowserClient(lims.app, lims.app.response_class)
        reader = BrowserClient(lims.app, lims.app.response_class)
        with reader.session_transaction() as session:
            session["personal_user_id"] = 1
            session["session_token"] = ""
        before = self.snapshot()
        for client, status in ((anonymous, 401), (reader, 403)):
            for method, url, body in (("post", "/api/readings", payload),
                                      ("put", f"/api/readings/{created['id']}", {"raw": 1}),
                                      ("delete", f"/api/readings/{created['id']}", {})):
                response = getattr(client, method)(url, json=body)
                self.assertEqual(status, response.status_code, response.json)
        self.assertEqual(before, self.snapshot())

    def test_sample_report_meta_and_results_share_optional_timestamp_precondition(self):
        for url, method, payload in (("/api/results", "post", {"sample_analyte_id": 1, "aux": {"use": True}}),
                                     ("/api/samples/1/report-meta", "put", {"customer": "A"}),
                                     ("/api/samples/1", "put", {"name": "Renamed", "preps": []})):
            old = self.detail()["sample"]["updated_at"]
            response = getattr(self.client, method)(url, json={**payload, "expected_updated_at": old})
            self.assertEqual(200, response.status_code, response.json)
            self.assertNotEqual(old, response.json["updated_at"])
            self.assertEqual(response.json["updated_at"], self.detail()["sample"]["updated_at"])
            self.assert_conflict_unchanged(lambda: getattr(self.other, method)(url, json={**payload, "expected_updated_at": old}))
        token = self.detail()["sample"]["updated_at"]
        self.client.put("/api/samples/1/report-meta", json={"customer": "B"})
        self.assert_conflict_unchanged(lambda: self.other.put("/api/samples/1", json={"name": "Stale", "expected_updated_at": token}))

    def run_parallel(self, operation):
        barrier = threading.Barrier(2)

        def run(client):
            barrier.wait(timeout=10)
            return operation(client)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, client) for client in (self.client, self.other)]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_duplicate_creates_commit_one_reading_and_audit(self):
        payload = {"sample_analyte_id": 1, "client_reading_id": str(uuid4()), "raw": 3}
        responses = self.run_parallel(lambda client: client.post("/api/readings", json=payload))
        self.assertEqual([200, 200], [response.status_code for response in responses])
        self.assertEqual(responses[0].json["id"], responses[1].json["id"])
        self.assertEqual({False, True}, {response.json["replayed"] for response in responses})
        self.assertEqual(1, len(self.query("SELECT * FROM readings")))
        self.assertEqual(1, len(self.query("SELECT * FROM audit_logs")))

    def test_concurrent_conditional_updates_have_exactly_one_winner(self):
        _, created = self.create()
        responses = self.run_parallel(lambda client: client.put(f"/api/readings/{created['id']}", json={
            "raw": 2 if client is self.client else 3, "expected_version": created["version"]}))
        self.assertEqual([200, 409], sorted(response.status_code for response in responses))
        self.assertEqual(2, len(self.query("SELECT * FROM audit_logs")))

    def test_concurrent_metadata_updates_have_exactly_one_winner(self):
        token = self.detail()["sample"]["updated_at"]
        responses = self.run_parallel(lambda client: client.put("/api/samples/1/report-meta", json={
            "customer": "A" if client is self.client else "B", "expected_updated_at": token}))
        self.assertEqual([200, 409], sorted(response.status_code for response in responses))
        self.assertEqual(1, len(self.query("SELECT * FROM audit_logs")))

    def test_schema_reinitialization_is_idempotent_and_keeps_unique_key(self):
        payload, created = self.create()
        initialize_database(self.database)
        self.assertEqual(created["id"], self.other.post("/api/readings", json=payload).json["id"])
        self.assertIn("CREATE TABLE IF NOT EXISTS reading_create_requests(", SCHEMA)
        self.assertIn("client_reading_id TEXT PRIMARY KEY", SCHEMA)

    def test_lock_reading_orders_sample_task_reading_locks(self):
        _, created = self.create()
        db = self.connect()
        statements = []

        class RecordingConnection:
            def execute(self, sql, params=None):
                statements.append(sql)
                return db.execute(sql.removesuffix(" FOR UPDATE"), params)

        try:
            row = lock_reading(RecordingConnection(), created["id"])
            self.assertEqual(created["id"], row["id"])
            self.assertEqual(["SELECT * FROM samples WHERE id=%s FOR UPDATE",
                              "SELECT * FROM sample_analytes WHERE id=%s FOR UPDATE",
                              "SELECT * FROM readings WHERE id=%s FOR UPDATE"],
                             [sql for sql in statements if sql.endswith(" FOR UPDATE")])
        finally:
            db.close()

    def test_timestamp_token_advances_even_with_frozen_or_backward_clock(self):
        previous = "2099-01-01 00:00:00.123456"
        with patch("mutation_guard.datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            self.assertEqual("2099-01-01 00:00:00.123457", next_updated_at(previous))

    def test_reading_writes_advance_sample_token_and_invalidate_metadata_drafts(self):
        token = "2099-01-01 00:00:00.123456"
        self.query("UPDATE samples SET updated_at=%s WHERE id=1", (token,))
        _, created = self.create()
        url = f"/api/readings/{created['id']}"
        for write in (lambda: None,
                      lambda: self.client.put(url, json={"raw": 3}),
                      lambda: self.client.delete(url)):
            write()
            updated_at = self.detail()["sample"]["updated_at"]
            self.assertGreater(updated_at, token)
            self.assert_conflict_unchanged(lambda: self.other.put("/api/samples/1/report-meta", json={
                "customer": "Stale", "expected_updated_at": token}))
            token = updated_at


if __name__ == "__main__":
    unittest.main()
