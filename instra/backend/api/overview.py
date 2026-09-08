"""Read-only workload overview. Counts describe tasks, not instrument telemetry."""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify

from api.samples import _AUDIT_ACTION_LABELS, _AUDIT_ENTITY_LABELS, _positive_int_arg

bp = Blueprint("overview", __name__)


def _recent_audits(before_id=None, limit=30):
    where = "WHERE id < ?" if before_id is not None else ""
    params = [before_id] if before_id is not None else []
    # Deliberately never load snapshots, terminal details or IP addresses.
    rows = g.db.execute(f"""SELECT id,created_at,username,action,entity_type,entity_id,reason
        FROM audit_logs {where} ORDER BY id DESC LIMIT ?""", params + [limit + 1]).fetchall()
    items = []
    for row in rows[:limit]:
        action, entity_type = row["action"] or "", row["entity_type"] or ""
        items.append({
            "id": row["id"], "created_at": row["created_at"],
            "username": row["username"] or "", "action": action,
            "action_label": _AUDIT_ACTION_LABELS.get(action, action),
            "entity_type": entity_type,
            "entity_id": str(row["entity_id"]) if row["entity_id"] is not None else "",
            "entity_label": _AUDIT_ENTITY_LABELS.get(entity_type, entity_type),
            "reason": row["reason"] or "",
        })
    has_more = len(rows) > limit
    return {"items": items, "has_more": has_more,
            "next_before_id": items[-1]["id"] if has_more else None}


@bp.get("/overview/audits")
def overview_audits():
    try:
        before_id = _positive_int_arg("before_id")
        limit = min(_positive_int_arg("limit", 30), 100)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=True, **_recent_audits(before_id, limit))


@bp.get("/overview")
def overview():
    db = g.db
    by_status = {row["status"]: row["c"] for row in db.execute("""SELECT
        COALESCE(status,'received') AS status,COUNT(*) AS c
        FROM samples GROUP BY COALESCE(status,'received')""")}

    # Aggregate each task once. Historical totals include cancelled tasks;
    # only open workload excludes closed tasks and closed samples.
    task_counts = {}
    for row in db.execute("""SELECT instrument_id,COUNT(*) AS task_total,
        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
        SUM(is_open) AS open_tasks,
        COUNT(DISTINCT CASE WHEN is_open=1 THEN sample_id END) AS open_samples
        FROM (
            SELECT sa.instrument_id,sa.sample_id,sa.status,
                CASE WHEN COALESCE(sa.status,'pending') NOT IN ('completed','cancelled')
                    AND COALESCE(s.status,'received') NOT IN ('reviewed','reported','cancelled')
                    THEN 1 ELSE 0 END AS is_open
            FROM sample_analytes sa JOIN samples s ON s.id=sa.sample_id
        ) tasks GROUP BY instrument_id"""):
        task_counts[row["instrument_id"]] = {
            key: row[key] for key in ("task_total", "open_tasks", "open_samples", "completed")
        }
    empty = {"task_total": 0, "open_tasks": 0, "open_samples": 0, "completed": 0}
    instruments = [{**dict(row), **task_counts.get(row["id"], empty)} for row in db.execute(
        "SELECT id,name,itype FROM instruments ORDER BY sort_order,id")]
    unassigned = task_counts.get(None, empty)

    # XRF is sample-level work, independent of sample_analytes and instrument IDs.
    xrf = dict(db.execute("""SELECT
        COALESCE(SUM(CASE WHEN xrf=1 THEN 1 ELSE 0 END),0) AS requested_samples,
        COALESCE(SUM(CASE WHEN xrf=1 AND has_scan=0
            AND COALESCE(status,'received') NOT IN ('reviewed','reported','cancelled')
            THEN 1 ELSE 0 END),0) AS awaiting_scan,
        COALESCE(SUM(has_scan),0) AS linked_samples
        FROM (
            SELECT s.xrf,s.status,
                CASE WHEN EXISTS(SELECT 1 FROM xrf_analyses xa WHERE xa.sample_id=s.id)
                    THEN 1 ELSE 0 END AS has_scan
            FROM samples s
        ) workload""").fetchone())

    return jsonify(
        ok=True, generated_at=datetime.now(timezone.utc).isoformat(),
        samples={"total": sum(by_status.values()), "by_status": by_status},
        instruments=instruments,
        unassigned={key: unassigned[key] for key in ("open_tasks", "open_samples")},
        xrf=xrf, recent_audits=_recent_audits(),
    )
