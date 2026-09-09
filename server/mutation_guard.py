"""Small transaction helpers for browser mutations; callers own commit/rollback."""

import hashlib
import json
from datetime import datetime, timedelta


def stable_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def reading_version(row):
    # Hash the stored values, not a request or a wall-clock timestamp.
    return stable_hash({key: row[key] for key in ("raw", "extra", "use_avg", "is_final")})


def locked_row(db, sql, params):
    return db.execute(sql + " FOR UPDATE", params).fetchone()


def lock_reading_task(db, task_id):
    # Sample first: progress recomputation writes it too. Serialize sibling final
    # selections before locking individual readings to avoid lock-order inversion.
    task = db.execute("SELECT sample_id FROM sample_analytes WHERE id=%s", (task_id,)).fetchone()
    if task:
        locked_row(db, "SELECT * FROM samples WHERE id=%s", (task["sample_id"],))
        locked_row(db, "SELECT * FROM sample_analytes WHERE id=%s", (task_id,))


def lock_reading(db, reading_id):
    row = db.execute("SELECT sample_analyte_id FROM readings WHERE id=%s", (reading_id,)).fetchone()
    if row:
        lock_reading_task(db, row["sample_analyte_id"])
    return locked_row(db, "SELECT * FROM readings WHERE id=%s", (reading_id,))


def next_updated_at(previous):
    now = datetime.now()
    if previous:
        now = max(now, datetime.fromisoformat(previous) + timedelta(microseconds=1))
    return now.isoformat(" ", timespec="microseconds")
