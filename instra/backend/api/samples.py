"""样品浏览 API：列表 + 聚合详情 + 审计时间线。全部只读。"""

import json
import sys
from pathlib import Path

from flask import Blueprint, g, jsonify, request

# 复用 toy-lims 的审计比较（纯函数，无副作用；字段中文标签由 audit_changes 内部完成）
SERVER_DIR = Path(__file__).resolve().parents[3] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
from lims_workflow import audit_changes  # noqa: E402

from domain import compute, ordering  # noqa: E402

bp = Blueprint("samples", __name__)


def _placeholders(count):
    return ",".join("?" for _ in range(count))


def _positive_int_arg(name, default=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"{name} must be a positive integer")
    value = int(raw)
    if not 1 <= value <= 9223372036854775807:
        raise ValueError(f"{name} must be a positive 64-bit integer")
    return value


def _sample_type(row):
    if row["workflow_type"] == "special":
        return "其他样"
    if row["is_water_quality"]:
        return "水质样"
    if row["is_liquid"]:
        return "液体样"
    return "固体"


@bp.get("/samples")
def list_samples():
    try:
        instrument_id = _positive_int_arg("instrument_id")
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    keyword = (request.args.get("keyword") or "").strip()
    status = (request.args.get("status") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = min(max(int(request.args.get("per_page", 30) or 30), 1), 100)

    conditions, params = [], []
    if instrument_id is not None:
        conditions.append("""EXISTS(SELECT 1 FROM sample_analytes sa
            WHERE sa.sample_id=s.id AND sa.instrument_id=?)""")
        params.append(instrument_id)
    if keyword:
        like = f"%{keyword}%"
        conditions.append("""(s.name ILIKE ? OR s.lims_no ILIKE ? OR s.category ILIKE ?
            OR EXISTS(SELECT 1 FROM sample_tags st WHERE st.sample_id=s.id AND st.tag ILIKE ?))""")
        params.extend([like, like, like, like])
    # 标签筛选：选中的每个标签都必须存在于样品上（AND 语义）
    for tag in request.args.getlist("tag"):
        tag = tag.strip()
        if tag:
            conditions.append("EXISTS(SELECT 1 FROM sample_tags st WHERE st.sample_id=s.id AND st.tag=?)")
            params.append(tag)
    if status:
        conditions.append("COALESCE(s.status,'received')=?")
        params.append(status)
    if date_from:
        conditions.append("s.created_at >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        conditions.append("s.created_at <= ?")
        params.append(date_to + " 23:59:59")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    db = g.db
    total = db.execute(f"SELECT COUNT(*) AS c FROM samples s {where}", params).fetchone()["c"]
    rows = db.execute(f"""SELECT s.id,s.lims_no,s.name,s.category,s.is_liquid,s.is_water_quality,
        s.workflow_type,s.xrf,s.status,s.created_at,s.customer,s.analysis_date,s.analyst,s.reviewer
        FROM samples s {where} ORDER BY s.id DESC LIMIT ? OFFSET ?""",
        params + [per_page, (page - 1) * per_page]).fetchall()

    ids = [row["id"] for row in rows]
    tags, analytes, prep_counts, xrf_counts = {}, {}, {}, {}
    task_counts, instrument_ids = {}, {}
    if ids:
        marks = _placeholders(len(ids))
        for row in db.execute(f"SELECT sample_id,tag FROM sample_tags WHERE sample_id IN ({marks})", ids):
            tags.setdefault(row["sample_id"], []).append(row["tag"])
        for row in db.execute(f"""SELECT DISTINCT sa.sample_id,a.name FROM sample_analytes sa
            JOIN analytes a ON a.id=sa.analyte_id WHERE sa.sample_id IN ({marks})""", ids):
            analytes.setdefault(row["sample_id"], []).append(row["name"])
        for row in db.execute(f"""SELECT sample_id,COUNT(*) AS c FROM preparations
            WHERE sample_id IN ({marks}) GROUP BY sample_id""", ids):
            prep_counts[row["sample_id"]] = row["c"]
        for row in db.execute(f"""SELECT sample_id,COUNT(*) AS c FROM xrf_analyses
            WHERE sample_id IN ({marks}) GROUP BY sample_id""", ids):
            xrf_counts[row["sample_id"]] = row["c"]
        for row in db.execute(f"""SELECT sample_id,instrument_id,COUNT(*) AS task_total,
            SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS task_completed
            FROM sample_analytes WHERE sample_id IN ({marks})
            GROUP BY sample_id,instrument_id ORDER BY sample_id,instrument_id""", ids):
            counts = task_counts.setdefault(row["sample_id"], [0, 0])
            counts[0] += row["task_total"]
            counts[1] += row["task_completed"]
            if row["instrument_id"] is not None:
                instrument_ids.setdefault(row["sample_id"], []).append(row["instrument_id"])

    order_list = ordering.load_order_list(db)
    items = []
    for row in rows:
        items.append({
            "id": row["id"], "lims_no": row["lims_no"], "name": row["name"],
            "category": row["category"], "type": _sample_type(row),
            "status": row["status"] or "received", "xrf": bool(row["xrf"]),
            "created_at": row["created_at"], "customer": row["customer"],
            "analysis_date": row["analysis_date"],
            "analyst": row["analyst"], "reviewer": row["reviewer"],
            "tags": tags.get(row["id"], []),
            "analytes": ordering.order_items(analytes.get(row["id"], []), order_list),
            "prep_count": prep_counts.get(row["id"], 0),
            "xrf_scan_count": xrf_counts.get(row["id"], 0),
            "task_total": task_counts.get(row["id"], [0, 0])[0],
            "task_completed": task_counts.get(row["id"], [0, 0])[1],
            "instrument_ids": instrument_ids.get(row["id"], []),
        })
    return jsonify(ok=True, total=total, page=page, per_page=per_page, items=items)


@bp.get("/tags")
def list_tags():
    """全部样品标签（按使用次数排序），供筛选下拉。"""
    rows = g.db.execute("""SELECT tag, COUNT(*) AS c FROM sample_tags
        GROUP BY tag ORDER BY c DESC, tag""").fetchall()
    return jsonify(ok=True, items=[{"tag": row["tag"], "count": row["c"]} for row in rows])


@bp.get("/samples/<int:sid>/aggregate")
def sample_aggregate(sid):
    db = g.db
    sample = db.execute("SELECT * FROM samples WHERE id=?", (sid,)).fetchone()
    if sample is None:
        return jsonify(ok=False, error="样品不存在"), 404

    tags = [row["tag"] for row in db.execute(
        "SELECT tag FROM sample_tags WHERE sample_id=? ORDER BY tag", (sid,))]

    sa_rows = db.execute("""SELECT sa.id,sa.preparation_id,sa.analyte_id,a.name AS analyte,
        a.default_unit AS analyte_default_unit,
        sa.instrument_id,i.name AS instrument,i.itype,
        sa.method_id,m.name AS method_name,m.formula,m.constants AS method_constants,
        m.output_unit AS method_output_unit,
        sa.selection,sa.status AS task_status,
        r.raw,r.extra,r.aux,
        p.name AS prep,p.mass_g AS prep_mass,p.volume_ml AS prep_vol,
        p.dilution_factor AS prep_factor,p.dilution_label
        FROM sample_analytes sa
        JOIN analytes a ON a.id=sa.analyte_id
        LEFT JOIN instruments i ON i.id=sa.instrument_id
        LEFT JOIN methods m ON m.id=sa.method_id
        LEFT JOIN preparations p ON p.id=sa.preparation_id
        LEFT JOIN results r ON r.sample_analyte_id=sa.id
        WHERE sa.sample_id=? ORDER BY sa.id""", (sid,)).fetchall()

    readings_by_sa = {}
    sa_ids = [row["id"] for row in sa_rows]
    if sa_ids:
        marks = _placeholders(len(sa_ids))
        for rd in db.execute(f"""SELECT sample_analyte_id,raw,extra,use_avg,is_final
            FROM readings WHERE sample_analyte_id IN ({marks}) ORDER BY id""", sa_ids):
            readings_by_sa.setdefault(rd["sample_analyte_id"], []).append(dict(rd))

    is_liquid = bool(sample["is_liquid"])
    density = sample["density_g_ml"] if is_liquid else None

    by_analyte = {}
    for row in sa_rows:
        sa = dict(row)
        sa["readings"] = readings_by_sa.get(sa["id"], [])
        value, unit, details = compute.calc_result(sa, is_liquid)
        entry = {
            "sample_analyte_id": sa["id"], "analyte": sa["analyte"],
            "prep": sa["prep"] or "原样", "mass_g": sa["prep_mass"],
            "volume_ml": sa["prep_vol"], "dilution": sa["dilution_label"] or "原液",
            "instrument": sa["instrument"] or "", "method": sa["method_name"] or "",
            "task_status": sa["task_status"], "selection": sa["selection"],
            "value": value, "unit": unit, "readings": details,
        }
        by_analyte.setdefault(sa["analyte"], []).append(entry)

    # 组顺序：样品 report_order 覆盖 > 系统默认模板
    sample_order = ordering.load_sample_report_order(db, sid)
    order_list = sample_order or ordering.load_order_list(db)
    ordered_names = ordering.order_items(list(by_analyte), order_list)

    groups = []
    for analyte in ordered_names:
        rows = by_analyte[analyte]
        rows.sort(key=lambda r: (r["prep"], r["sample_analyte_id"]))
        quant = [r for r in rows if isinstance(r["value"], (int, float))]
        chosen = [r for r in quant if r["selection"] != "exclude"] or quant
        final = None
        available_units = []
        if chosen:
            source_units = [r["unit"] for r in chosen]
            available_units = compute.result_unit_options(source_units[0], density)
            for unit in source_units[1:]:
                compatible = set(compute.result_unit_options(unit, density))
                available_units = [u for u in available_units if u in compatible]
            average = sum(r["value"] for r in chosen) / len(chosen)
            final = {"value": round(average, 4), "unit": chosen[0]["unit"],
                     "based_on": len(chosen),
                     "mode": "单值" if len(chosen) == 1 else "自动平均"}
        groups.append({"analyte": analyte, "final": final,
                       "available_units": available_units, "rows": rows})

    # 关联 XRF 扫描（定量与 UQ 双写都在 xrf_analyses）
    analyses = []
    for xa in db.execute("""SELECT id,external_id,sample_name,method,batch,analyzed_at,
        COALESCE(kind,'quant') AS kind,remark FROM xrf_analyses
        WHERE sample_id=? ORDER BY analyzed_at DESC NULLS LAST, id DESC""", (sid,)):
        values = [dict(v) for v in db.execute(
            "SELECT id,name,value,use_report,alt_name FROM xrf_values WHERE analysis_id=?",
            (xa["id"],))]
        analyses.append({**dict(xa), "values": values})

    # 溶样方案：每路的称样/定容/稀释 + 测定项目与仪器分配
    preps = []
    prep_rows = db.execute("""SELECT id,name,mass_g,volume_ml,dilution_label,dilution_factor,
        dilution_steps FROM preparations WHERE sample_id=? ORDER BY id""", (sid,)).fetchall()
    tasks_by_prep = {}
    for row in sa_rows:
        if row["preparation_id"]:
            tasks_by_prep.setdefault(row["preparation_id"], []).append({
                "analyte": row["analyte"], "instrument": row["instrument"] or "",
                "method": row["method_name"] or "", "status": row["task_status"],
            })
    for prep in prep_rows:
        try:
            steps = json.loads(prep["dilution_steps"] or "[]")
        except (TypeError, ValueError):
            steps = []
        tasks = sorted(tasks_by_prep.get(prep["id"], []), key=lambda t: t["analyte"])
        preps.append({
            "id": prep["id"], "name": prep["name"], "mass_g": prep["mass_g"],
            "volume_ml": prep["volume_ml"], "dilution_label": prep["dilution_label"] or "原液",
            "dilution_factor": prep["dilution_factor"], "dilution_steps": steps,
            "tasks": tasks,
        })

    return jsonify(ok=True, sample={
        "id": sample["id"], "lims_no": sample["lims_no"], "name": sample["name"],
        "category": sample["category"], "type": _sample_type(sample),
        "status": sample["status"], "xrf": bool(sample["xrf"]),
        "created_at": sample["created_at"], "customer": sample["customer"],
        "analysis_date": sample["analysis_date"], "analyst": sample["analyst"],
        "reviewer": sample["reviewer"], "density_g_ml": sample["density_g_ml"],
        "cancel_reason": sample["cancel_reason"],
    }, tags=tags, groups=groups, xrf_analyses=analyses, preps=preps)


_AUDIT_ACTION_LABELS = {
    "create": "新建", "update": "修改", "delete": "删除", "disable": "停用",
    "restore": "恢复", "status_change": "修改状态", "cancel": "作废",
    "result_update": "修改结果", "report_use": "修改结果参与计算",
    "report_meta": "修改报告信息", "report_order": "修改报告顺序",
    "report_print": "修改报告打印项", "report_override": "旧版手工修改报告",
    "result_override": "特权补录结果", "instrument_import": "导入仪器结果",
    "instrument_reading": "仪器录入读数", "instrument_submit": "仪器批量提交",
    "xrf_assign": "关联 XRF 扫描", "xrf_unassign": "解绑 XRF 扫描",
    "xrf_report_use": "修改 XRF 结果参与计算", "special_result": "修改专项检测数据",
    "excel_plan_create": "用 Excel 新建样品", "excel_plan_overwrite": "用 Excel 覆盖样品方案",
    "excel_data_overwrite": "用 Excel 覆盖检测数据",
    "result_unit": "修改结果显示单位", "login": "登录", "logout": "退出登录",
    "session_replaced": "替换终端会话",
}

_AUDIT_ENTITY_LABELS = {
    "sample": "样品", "sample_analyte": "检测任务", "reading": "读数",
    "xrf_analysis": "XRF 扫描", "xrf_value": "XRF 结果",
    "instrument_import": "仪器导入", "special_result": "专项检测",
    "session": "终端会话", "user": "用户", "instrument": "仪器",
}


@bp.get("/samples/<int:sid>/audit")
def sample_audit(sid):
    """样品的完整审计时间线：样品本体 + 检测任务 + 读数 + 关联 XRF 的全部事件。"""
    db = g.db
    # Compare text IDs rather than casting untrusted audit IDs to integers.
    rows = db.execute("""SELECT al.id,al.username,al.terminal_name,al.action,al.entity_type,
        al.entity_id,al.before_json,al.after_json,al.reason,al.ip_address,al.created_at
        FROM audit_logs al WHERE
          (al.entity_type='sample' AND al.entity_id=?)
          OR (al.entity_type='instrument_import' AND al.entity_id=?)
          OR (al.entity_type='sample_analyte' AND al.entity_id IN (
                SELECT CAST(id AS TEXT) FROM sample_analytes WHERE sample_id=?))
          OR (al.entity_type='reading' AND al.entity_id IN (
                SELECT CAST(r.id AS TEXT) FROM readings r JOIN sample_analytes sa
                  ON sa.id=r.sample_analyte_id WHERE sa.sample_id=?))
          OR (al.entity_type='xrf_analysis' AND al.entity_id IN (
                SELECT CAST(id AS TEXT) FROM xrf_analyses WHERE sample_id=?))
          OR (al.entity_type='xrf_value' AND al.entity_id IN (
                SELECT CAST(xv.id AS TEXT) FROM xrf_values xv JOIN xrf_analyses xa
                  ON xa.id=xv.analysis_id WHERE xa.sample_id=?))
        ORDER BY al.id DESC LIMIT 300""",
        (str(sid), str(sid), sid, sid, sid, sid)).fetchall()

    def parse(raw):
        try:
            return json.loads(raw) if raw else None
        except (TypeError, ValueError):
            return None

    items = []
    for row in rows:
        before, after = parse(row["before_json"]), parse(row["after_json"])
        changes = []
        if before is not None and after is not None:
            for change in audit_changes(before, after, limit=20):
                changes.append({
                    "field": change.get("field", ""),
                    "label": change.get("label") or change.get("field", ""),
                    "before": change.get("before"),
                    "after": change.get("after"),
                })
        items.append({
            "id": row["id"], "created_at": row["created_at"],
            "username": row["username"], "terminal_name": row["terminal_name"],
            "ip_address": row["ip_address"],
            "action": row["action"],
            "entity_type": row["entity_type"], "entity_id": row["entity_id"],
            "action_label": _AUDIT_ACTION_LABELS.get(row["action"], row["action"]),
            "entity_label": _AUDIT_ENTITY_LABELS.get(row["entity_type"], row["entity_type"]),
            "reason": row["reason"] or "", "changes": changes,
            "has_snapshot": before is not None or after is not None,
        })
    return jsonify(ok=True, total=len(items), items=items)
