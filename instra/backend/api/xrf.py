"""XRF 扫描浏览 API：定量 / UniQuant 列表与详情。全部只读。"""

import json

from flask import Blueprint, g, jsonify, request

from domain.conversion import composition_pairs, load_reference

bp = Blueprint("xrf", __name__)


def _paging():
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = min(max(int(request.args.get("per_page", 25) or 25), 1), 100)
    return page, per_page


def _date_range(conditions, params, column):
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    if date_from:
        conditions.append(f"{column} >= %s")
        params.append(date_from)
    if date_to:
        conditions.append(f"{column} <= %s")
        params.append(date_to + "T23:59:59" if "T" in (date_to or "") else date_to + " 23:59:59")


@bp.get("/xrf/quant")
def list_quant():
    keyword = (request.args.get("keyword") or "").strip()
    sample_id = (request.args.get("sample_id") or "").strip()
    page, per_page = _paging()

    conditions = ["COALESCE(xa.kind,'quant')='quant'"]
    params = []
    if keyword:
        like = f"%{keyword}%"
        conditions.append("""(xa.sample_name ILIKE %s OR xa.method ILIKE %s OR xa.batch ILIKE %s
            OR xa.external_id ILIKE %s OR s.name ILIKE %s OR s.lims_no ILIKE %s)""")
        params.extend([like] * 6)
    if sample_id:
        conditions.append("xa.sample_id=%s")
        params.append(int(sample_id))
    _date_range(conditions, params, "xa.analyzed_at")
    where = "WHERE " + " AND ".join(conditions)

    db = g.db
    total = db.execute(f"""SELECT COUNT(*) AS c FROM xrf_analyses xa
        LEFT JOIN samples s ON s.id=xa.sample_id {where}""", params).fetchone()["c"]
    rows = db.execute(f"""SELECT xa.id,xa.external_id,xa.sample_id,xa.sample_name,xa.method,
        xa.batch,xa.analyzed_at,xa.remark,s.name AS lims_name,s.lims_no
        FROM xrf_analyses xa LEFT JOIN samples s ON s.id=xa.sample_id {where}
        ORDER BY xa.analyzed_at DESC NULLS LAST, xa.id DESC LIMIT %s OFFSET %s""",
        params + [per_page, (page - 1) * per_page]).fetchall()

    items = []
    for row in rows:
        values = db.execute("""SELECT name,value,use_report,alt_name FROM xrf_values
            WHERE analysis_id=%s ORDER BY value DESC""", (row["id"],)).fetchall()
        items.append({
            **dict(row), "kind": "quant",
            "value_count": len(values),
            "top_values": [dict(v) for v in values[:6]],
        })
    return jsonify(ok=True, total=total, page=page, per_page=per_page, items=items)


@bp.get("/xrf/quant/<int:aid>")
def quant_detail(aid):
    db = g.db
    row = db.execute("""SELECT xa.id,xa.external_id,xa.sample_id,xa.sample_name,xa.method,
        xa.batch,xa.analyzed_at,xa.remark,xa.options_json,s.name AS lims_name,s.lims_no
        FROM xrf_analyses xa LEFT JOIN samples s ON s.id=xa.sample_id
        WHERE xa.id=%s AND COALESCE(xa.kind,'quant')='quant'""", (aid,)).fetchone()
    if row is None:
        return jsonify(ok=False, error="扫描不存在"), 404
    values = [dict(v) for v in db.execute("""SELECT name,value,use_report,alt_name
        FROM xrf_values WHERE analysis_id=%s ORDER BY value DESC""", (aid,))]
    return jsonify(ok=True, item={**dict(row), "kind": "quant", "values": values})


@bp.get("/xrf/uq")
def list_uq():
    """UQ 列表以 xrf_analyses（kind='uq'）为准——uq_analyses 明细表可能缺行。"""
    keyword = (request.args.get("keyword") or "").strip()
    sample_id = (request.args.get("sample_id") or "").strip()
    page, per_page = _paging()

    conditions = ["COALESCE(xa.kind,'quant')='uq'"]
    params = []
    if keyword:
        like = f"%{keyword}%"
        conditions.append("""(xa.sample_name ILIKE %s OR xa.method ILIKE %s OR xa.external_id ILIKE %s
            OR s.name ILIKE %s OR s.lims_no ILIKE %s)""")
        params.extend([like] * 5)
    if sample_id:
        conditions.append("xa.sample_id=%s")
        params.append(int(sample_id))
    _date_range(conditions, params, "xa.analyzed_at")
    where = "WHERE " + " AND ".join(conditions)

    db = g.db
    total = db.execute(f"""SELECT COUNT(*) AS c FROM xrf_analyses xa
        LEFT JOIN samples s ON s.id=xa.sample_id {where}""", params).fetchone()["c"]
    rows = db.execute(f"""SELECT xa.id,xa.external_id,xa.sample_id,xa.sample_name,xa.method,
        xa.analyzed_at,xa.remark,ua.film,ua.processed,ua.general_id,ua.job_id,
        s.name AS lims_name,s.lims_no
        FROM xrf_analyses xa
        LEFT JOIN uq_analyses ua ON ua.external_id=xa.external_id
        LEFT JOIN samples s ON s.id=xa.sample_id {where}
        ORDER BY xa.analyzed_at DESC NULLS LAST, xa.id DESC LIMIT %s OFFSET %s""",
        params + [per_page, (page - 1) * per_page]).fetchall()

    items = []
    for row in rows:
        values = db.execute("""SELECT name,value,alt_name FROM xrf_values
            WHERE analysis_id=%s ORDER BY value DESC""", (row["id"],)).fetchall()
        items.append({
            **dict(row), "kind": "uq",
            "processed": bool(row["processed"]) if row["processed"] is not None else None,
            "general_id": row["general_id"] or row["external_id"].split(":")[0],
            "job_id": row["job_id"] or (row["external_id"].split(":")[1]
                                        if ":" in row["external_id"] else ""),
            "value_count": len(values),
            "top_values": [dict(v) for v in values[:6]],
        })
    return jsonify(ok=True, total=total, page=page, per_page=per_page, items=items)


def load_uq_detail(db, aid):
    """UQ 全量数据（导出与详情共用）。aid 是 xrf_analyses.id。

    options 以 xrf_analyses.options_json 为准（与生产语义一致），
    uq_analyses 明细缺行时 channels/job 回退为空；
    composition 另按 common_oxides 系数生成「左氧化物 / 右元素」pairs。
    """
    row = db.execute("""SELECT xa.id,xa.external_id,xa.sample_id,xa.sample_name,xa.method,
        xa.analyzed_at,xa.remark,xa.options_json,s.name AS lims_name,s.lims_no
        FROM xrf_analyses xa LEFT JOIN samples s ON s.id=xa.sample_id
        WHERE xa.id=%s AND COALESCE(xa.kind,'quant')='uq'""", (aid,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["kind"] = "uq"

    def _parse_json(text):
        try:
            parsed = json.loads(text or "{}")
        except (TypeError, ValueError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    options = _parse_json(item.pop("options_json"))
    composition = [dict(v) for v in db.execute("""SELECT name,value,alt_name,use_report
        FROM xrf_values WHERE analysis_id=%s ORDER BY value DESC""", (aid,))]
    item["composition"] = composition

    detail = db.execute("SELECT * FROM uq_analyses WHERE external_id=%s",
                        (item["external_id"],)).fetchone()
    channels, job = [], {}
    item["film"] = options.get("film")
    item["processed"] = None
    item["general_id"] = item["external_id"].split(":")[0]
    item["job_id"] = item["external_id"].split(":")[1] if ":" in item["external_id"] else ""
    item["job_result"] = ""
    if detail is not None:
        alt_names = {c["name"]: c.get("alt_name") or "" for c in composition}
        channels = [dict(c) for c in db.execute("""SELECT name,int_cps,conc,sigma_conc,std_err,
            counting_time,overlapping_elements,is_reported FROM uq_channels
            WHERE uq_analysis_id=%s ORDER BY conc DESC NULLS LAST""", (detail["id"],))]
        for channel in channels:
            channel["alt_name"] = alt_names.get(channel["name"], "")
            channel["is_reported"] = bool(channel["is_reported"])
        detail_options = _parse_json(detail["options_json"])
        if not options:
            options = detail_options
        if "film" not in options:
            options["film"] = detail["film"]
        job = _parse_json(detail["job_json"])
        item["processed"] = bool(detail["processed"]) if detail["processed"] is not None else None
        item["general_id"] = detail["general_id"] or item["general_id"]
        item["job_id"] = detail["job_id"] or item["job_id"]
        item["job_result"] = detail["job_result"] or ""
    elements, oxides = load_reference(db)
    item["pairs"] = composition_pairs(composition, elements, oxides)
    item["channels"] = channels
    item["options"] = options
    item["job"] = job
    return item


@bp.get("/xrf/uq/<int:uid>")
def uq_detail(uid):
    item = load_uq_detail(g.db, uid)
    if item is None:
        return jsonify(ok=False, error="UniQuant 分析不存在"), 404
    return jsonify(ok=True, item=item)
