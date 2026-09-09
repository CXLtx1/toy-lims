"""Read-only raw-reading audit context, not a historical whole-state replay.

Rows always describe current tasks. A deleted target reading gets a blank stub
with historical_placeholder=True so the scene can locate it by reading ID and
overlay only values[mode].value. Never calculate historical results from rows.
"""

import json
import math
import re
import secrets

from flask import Blueprint, g, jsonify, make_response, render_template, request

from .samples import _AUDIT_ACTION_LABELS

bp = Blueprint("audit_context", __name__)
_RAW_TYPES = {"ppm", "ppb", "mol", "percent", "ph"}


def _positive_id(value):
    if isinstance(value, str):
        if not re.fullmatch(r"[1-9][0-9]{0,18}", value):
            return None
        value = int(value)
    if type(value) is int and 1 <= value <= 9223372036854775807:
        return value
    return None


def _object(value):
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _raw_value(value):
    if value is None:
        return {"available": True, "value": None}
    try:
        if type(value) in (int, float) and math.isfinite(value):
            return {"available": True, "value": value}
    except OverflowError:
        pass
    return {"available": False, "value": None}


def _numeric_object(value, aux=False):
    """Keep renderer inputs numeric; never interpolate stored strings as HTML."""
    obj = _object(value)
    clean = {}
    for key, item in (obj or {}).items():
        if aux and key == "use":
            clean[key] = item is True or type(item) is int and item == 1
        elif (isinstance(key, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key)
              and (not aux or key in {"expected", "measured"})
              and _raw_value(item)["available"]):
            clean[key] = item
    return json.dumps(clean, allow_nan=False), obj is None or clean != obj


_TASK_SELECT = """SELECT sa.id,sa.sample_id,sa.preparation_id,sa.instrument_id,
    a.name AS analyte,p.name AS prep_name,i.name AS instrument,i.itype,
    m.name AS method_name,m.formula,m.constants AS method_constants,
    p.mass_g AS prep_mass,p.volume_ml AS prep_vol,r.aux,sa.status
    FROM sample_analytes sa
    LEFT JOIN analytes a ON a.id=sa.analyte_id
    LEFT JOIN instruments i ON i.id=sa.instrument_id
    LEFT JOIN methods m ON m.id=sa.method_id
    LEFT JOIN preparations p ON p.id=sa.preparation_id
    LEFT JOIN results r ON r.sample_analyte_id=sa.id"""


def load_context(db, aid):
    """Return the public payload using SELECTs only; missing audits have ok=False."""
    aid = _positive_id(aid)
    event = None if aid is None else db.execute("""SELECT id,created_at,username,
        action,entity_type,entity_id,before_json,after_json
        FROM audit_logs WHERE id=%s""", (aid,)).fetchone()
    if event is None:
        return {"ok": False, "error": "Audit not found."}
    audit = {key: event[key] for key in ("id", "created_at", "username")}
    audit["action_label"] = _AUDIT_ACTION_LABELS.get(event["action"], event["action"])

    def unsupported(reason):
        return {"ok": True, "supported": False, "reason": reason, "audit": audit}

    if event["entity_type"] != "reading" or event["action"] != "update":
        return unsupported("Only plain reading raw updates are supported.")
    rid = _positive_id(event["entity_id"])
    if rid is None:
        return unsupported("Audit reading ID is not a positive 64-bit integer.")
    before, after = _object(event["before_json"]), _object(event["after_json"])
    if before is None or after is None or "raw" not in before or "raw" not in after:
        return unsupported("Both snapshots must contain raw; missing raw is not a blank value.")
    values = {"before": _raw_value(before["raw"]), "after": _raw_value(after["raw"])}
    if not all(value["available"] for value in values.values()):
        return unsupported("Snapshot raw must be a finite number or explicit null.")
    if before["raw"] == after["raw"]:
        return unsupported("The snapshots do not change raw.")
    said = _positive_id(before.get("sample_analyte_id"))
    if said is None or _positive_id(after.get("sample_analyte_id")) != said:
        return unsupported("Snapshot task parents are missing, invalid, or disagree.")
    for snapshot in (before, after):
        if "id" in snapshot and _positive_id(snapshot["id"]) != rid:
            return unsupported("Snapshot reading ID disagrees with the audit reading ID.")
        if (("itype" in snapshot and snapshot["itype"] not in _RAW_TYPES)
                or snapshot.get("formula")):
            return unsupported("Snapshot context is not a plain raw reading.")

    reading = db.execute("SELECT sample_analyte_id FROM readings WHERE id=%s", (rid,)).fetchone()
    if reading is not None and reading["sample_analyte_id"] != said:
        return unsupported("The current reading has been reassigned to another task.")
    target = db.execute(_TASK_SELECT + " WHERE sa.id=%s", (said,)).fetchone()
    if target is None:
        return unsupported("The original task is missing or deleted.")
    sid = _positive_id(target["sample_id"])
    if sid is None:
        return unsupported("The original task has no valid sample parent.")
    for snapshot in (before, after):
        if "sample_id" in snapshot and _positive_id(snapshot["sample_id"]) != sid:
            return unsupported("Snapshot sample parent disagrees with the current task.")
    sample = db.execute("SELECT id,name,lims_no,status FROM samples WHERE id=%s", (sid,)).fetchone()
    if sample is None:
        return unsupported("The original sample is missing or deleted.")
    if target["analyte"] is None:
        return unsupported("The current task analyte is missing.")
    if target["itype"] not in _RAW_TYPES or target["formula"]:
        return unsupported("The current instrument/method is not assigned to plain raw entry.")

    warnings = [
        "Labels, units, method, preparation, sample status and row context are CURRENT, not historical.",
        "Only before/after raw values come from snapshots. The event's old method is not recorded; "
        "no historical whole state or recalculated result is provided.",
        "Neighbors are up to two CURRENT tasks with the same sample, preparation and instrument, "
        "nearest by task ID (ties by ID), not necessarily the original visual neighbors.",
    ]
    # results has one row per task; readings are fetched separately to avoid fan-out.
    rows = [dict(row) for row in db.execute(_TASK_SELECT + """
        WHERE sa.sample_id=%s AND sa.instrument_id=%s
          AND (sa.preparation_id=%s OR (sa.preparation_id IS NULL AND CAST(%s AS BIGINT) IS NULL))
        ORDER BY ABS(sa.id - %s),sa.id LIMIT 3""",
        (sid, target["instrument_id"], target["preparation_id"], target["preparation_id"], said))]
    rows.sort(key=lambda row: row["id"])
    by_id = {row["id"]: row for row in rows}
    if said not in by_id:
        return unsupported("The current task context changed while loading; retry.")
    sanitized = False
    for row in rows:
        del row["preparation_id"], row["instrument_id"]
        for key in ("prep_mass", "prep_vol"):
            value = _raw_value(row[key])
            sanitized |= not value["available"]
            row[key] = value["value"]
        for key in ("aux", "method_constants"):
            row[key], changed = _numeric_object(row[key], aux=key == "aux")
            sanitized |= changed
        row["readings"] = []
    marks = ",".join("%s" for _ in rows)
    current = None
    for rd in db.execute(f"""SELECT id,sample_analyte_id,raw,extra,use_avg,is_final
            FROM readings WHERE sample_analyte_id IN ({marks}) ORDER BY id""", list(by_id)):
        rd = dict(rd)
        value = _raw_value(rd["raw"])
        if rd["id"] == rid:
            if rd["sample_analyte_id"] != said:
                return unsupported("The current reading has been reassigned to another task.")
            current = value
        sanitized |= not value["available"]
        rd["raw"] = value["value"]
        rd["extra"], changed = _numeric_object(rd["extra"])
        sanitized |= changed
        rd["use_avg"] = rd["use_avg"] == 1
        rd["is_final"] = rd["is_final"] == 1
        by_id[rd["sample_analyte_id"]]["readings"].append(rd)
    if current is None:
        warnings.append("The target reading is gone; current is unavailable. A blank historical_placeholder "
                        "reading preserves its locator for the before/after overlay only.")
        by_id[said]["readings"].append({
            "id": rid, "sample_analyte_id": said, "raw": None, "extra": "{}",
            "use_avg": False, "is_final": False, "historical_placeholder": True,
        })
        by_id[said]["readings"].sort(key=lambda rd: rd["id"])
    elif not current["available"]:
        warnings.append("The current target raw is malformed or non-finite; current is unavailable.")
    if sanitized:
        warnings.append("Malformed or non-numeric current raw/extra/aux/constants were sanitized for display.")
    values["current"] = current or {"available": False, "value": None}
    return {"ok": True, "supported": True, "audit": audit, "sample": dict(sample),
            "locator": {"sample_id": sid, "sample_analyte_id": said, "reading_id": rid, "field": "raw"},
            "values": values, "rows": rows, "warnings": warnings}


@bp.get("/audits/<int:aid>/context")
def audit_context(aid):
    payload = load_context(g.db, aid)
    response = jsonify(payload)
    response.status_code = 200 if payload["ok"] else 404
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/audits/<int:aid>/scene")
def audit_scene(aid):
    mode = request.args.get("mode", "before")
    nonce = secrets.token_urlsafe(24)
    if mode not in {"before", "after", "current"}:
        response = make_response(jsonify(ok=False, error="Invalid mode; use before, after or current."), 400)
    else:
        payload = load_context(g.db, aid)
        if not payload["ok"]:
            response = make_response(jsonify(payload), 404)
        else:
            status = 409 if payload["supported"] and not payload["values"][mode]["available"] else 200
            response = make_response(render_template("audit_scene.html", scene=payload, mode=mode, nonce=nonce), status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}' 'self'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; "
        "base-uri 'none'; frame-ancestors 'self'"
    )
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
