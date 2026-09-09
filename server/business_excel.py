# -*- coding: utf-8 -*-
"""Versioned, human-oriented Excel workbooks for LIMS business operations."""

import json
import re
from datetime import date, datetime, time
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


FORMAT = "toy-lims-business-workbook"
VERSION = 1
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BLUE = "1F4E78"
LIGHT_BLUE = "D9EAF7"
GOLD = "D6B656"
GRAY = "E7E6E6"


class BusinessExcelError(ValueError):
    pass


def _set_value(cell, value):
    """Keep text unchanged while preventing spreadsheet formula execution."""
    cell.value = value
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        cell.quotePrefix = True


def _json(value):
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _loads(value, label):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise BusinessExcelError(f"{label}必须是有效的 JSON 对象") from exc
    if not isinstance(result, dict):
        raise BusinessExcelError(f"{label}必须是 JSON 对象")
    return result


def _new(profile, title, instructions, sample=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "说明"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 90
    ws.merge_cells("A1:B1")
    ws["A1"] = title
    ws["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=BLUE)
    ws["A1"].alignment = Alignment(horizontal="center")
    metadata = [
        ("工作簿格式", FORMAT), ("格式版本", VERSION), ("业务类型", profile),
        ("样品ID", sample.get("id") if sample else ""),
        ("样品编号", sample.get("lims_no") if sample else ""),
        ("更新标记", sample.get("updated_at") if sample else ""),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for row, (key, value) in enumerate(metadata, 3):
        ws.cell(row, 1, key).font = Font(bold=True, color=BLUE)
        _set_value(ws.cell(row, 2), value)
    start = 11
    ws.cell(start, 1, "使用说明").font = Font(bold=True, color=BLUE, size=12)
    for index, text in enumerate(instructions, start + 1):
        ws.cell(index, 1, f"{index - start}.")
        ws.cell(index, 2, text)
        ws.cell(index, 2).alignment = Alignment(wrap_text=True, vertical="top")
    return wb


def _sheet(wb, name, title, headers, widths=None, editable=True):
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.cell(1, 1, title)
    ws.cell(1, 1).font = Font(size=15, bold=True, color="FFFFFF")
    ws.cell(1, 1).fill = PatternFill("solid", fgColor=BLUE)
    ws.cell(1, 1).alignment = Alignment(horizontal="center")
    for col, header in enumerate(headers, 1):
        cell = ws.cell(3, col, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=BLUE if editable else "666666")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if "JSON" in header:
            cell.comment = Comment('请输入JSON对象，例如 {"V":12.3}；不要使用Excel公式。', "toy-lims")
        ws.column_dimensions[get_column_letter(col)].width = (widths or {}).get(header, max(12, min(28, len(header) * 2 + 4)))
    ws.freeze_panes = "A4"
    return ws


def _append(ws, values):
    ws.append(list(values))
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str) and cell.value.startswith(("=", "+", "-", "@")):
            cell.quotePrefix = True
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.border = Border(bottom=Side(style="hair", color="D9E2F3"))
        if isinstance(cell.value, datetime):
            cell.number_format = "yyyy-mm-dd hh:mm:ss"
        elif isinstance(cell.value, date):
            cell.number_format = "yyyy-mm-dd"
        elif isinstance(cell.value, float):
            cell.number_format = "0.0000"


def _finish_table(ws, name):
    if ws.max_row < 4:
        return
    ref = f"A3:{get_column_letter(ws.max_column)}{ws.max_row}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True,
                                         showFirstColumn=False, showLastColumn=False)
    ws.add_table(table)


def _bytes(wb):
    output = BytesIO()
    wb.save(output)
    wb.close()
    output.seek(0)
    return output


def _count(db, sql, sid):
    return db.execute(sql, (sid,)).fetchone()[0]


OVERVIEW_HEADERS = ["LIMS编号", "样品名称", "类别", "样品类型", "流程", "状态", "创建时间", "更新时间",
                    "专项方法", "XRF", "溶样数", "任务数", "完成任务数", "读数数", "XRF结果数", "分析项目",
                    "客户", "报告编号", "分析日期", "分析员", "审核员"]


def build_overview(db, date_from, date_to, sample_type="", query="", include_cancelled=False):
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except (TypeError, ValueError) as exc:
        raise BusinessExcelError("请选择有效的开始和结束日期（YYYY-MM-DD）") from exc
    if start > end:
        raise BusinessExcelError("开始日期不能晚于结束日期")
    conditions = ["s.created_at>=%s", "s.created_at<%s"]
    args = [start.isoformat(), date.fromordinal(end.toordinal() + 1).isoformat()]
    if not include_cancelled:
        conditions.append("COALESCE(s.status,'received')!='cancelled'")
    if sample_type == "solid":
        conditions.append("s.is_liquid=0 AND COALESCE(s.workflow_type,'regular')='regular'")
    elif sample_type == "liquid":
        conditions.append("s.is_liquid=1 AND COALESCE(s.is_water_quality,0)=0 AND COALESCE(s.workflow_type,'regular')='regular'")
    elif sample_type == "water_quality":
        conditions.append("COALESCE(s.is_water_quality,0)=1 AND COALESCE(s.workflow_type,'regular')='regular'")
    elif sample_type == "special":
        conditions.append("s.workflow_type='special'")
    elif sample_type not in ("", "all"):
        raise BusinessExcelError("样品类型筛选无效")
    if query:
        conditions.append("""(s.name LIKE %s OR s.lims_no LIKE %s OR s.category LIKE %s OR EXISTS(
            SELECT 1 FROM sample_analytes sx JOIN analytes ax ON ax.id=sx.analyte_id
            WHERE sx.sample_id=s.id AND ax.name LIKE %s) OR EXISTS(
            SELECT 1 FROM special_methods smx WHERE smx.id=s.special_method_id
            AND (smx.name LIKE %s OR smx.instrument LIKE %s)))""")
        args.extend([f"%{query}%"] * 6)
    records = db.execute(f"""SELECT s.*,sm.name special_method_name,
        (SELECT string_agg(name, ', ' ORDER BY sort_order,id) FROM (
         SELECT DISTINCT a.name,a.sort_order,a.id FROM sample_analytes sa
         JOIN analytes a ON a.id=sa.analyte_id WHERE sa.sample_id=s.id) AS sample_analytes) analytes
        FROM samples s LEFT JOIN special_methods sm ON sm.id=s.special_method_id
        WHERE {' AND '.join(conditions)} ORDER BY s.created_at,s.id""", args).fetchall()
    wb = _new("sample-overview", "样品业务总览", [
        f"统计范围为 {start.isoformat()} 至 {end.isoformat()}，按创建时间筛选，起止日期均包含。",
        "本文件用于业务查阅，不包含密码、权限配置或可用于替换数据库的原始表数据。",
        "筛选和排序不会改变系统数据。",
    ])
    ws = _sheet(wb, "样品总览", "样品总览", OVERVIEW_HEADERS,
                {"样品名称": 24, "分析项目": 30, "创建时间": 20, "更新时间": 20}, editable=False)
    for s in records:
        sid = s["id"]
        special = s["workflow_type"] == "special"
        sample_kind = "水质" if s["is_water_quality"] else ("液体" if s["is_liquid"] else "固体")
        _append(ws, [s["lims_no"], s["name"], s["category"], sample_kind,
                     "专项" if special else "常规", s["status"], s["created_at"], s["updated_at"],
                     s["special_method_name"] or "", "是" if s["xrf"] else "否",
                     _count(db, "SELECT COUNT(*) FROM preparations WHERE sample_id=%s", sid),
                     _count(db, "SELECT COUNT(*) FROM sample_analytes WHERE sample_id=%s", sid) + (1 if special else 0),
                     _count(db, "SELECT COUNT(*) FROM sample_analytes WHERE sample_id=%s AND status='completed'", sid) +
                     (_count(db, "SELECT COUNT(*) FROM special_results WHERE sample_id=%s AND status='completed'", sid) if special else 0),
                     _count(db, "SELECT COUNT(*) FROM readings r JOIN sample_analytes sa ON sa.id=r.sample_analyte_id WHERE sa.sample_id=%s", sid),
                     _count(db, "SELECT COUNT(*) FROM xrf_values xv JOIN xrf_analyses xa ON xa.id=xv.analysis_id WHERE xa.sample_id=%s", sid),
                     s["analytes"] or s["special_method_name"] or "", s["customer"], s["report_no"], s["analysis_date"],
                     s["analyst"], s["reviewer"]])
    _finish_table(ws, "SampleOverview")
    return _bytes(wb), len(records)


INFO_FIELDS = [("样品ID", "id"), ("LIMS编号", "lims_no"), ("更新标记", "updated_at"), ("样品名称", "name"),
               ("类别", "category"), ("流程", "workflow_type"), ("液体样", "is_liquid"),
               ("水质样", "is_water_quality"), ("启用XRF", "xrf"),
               ("XRF方法ID", "xrf_method_id"), ("XRF报告项目", "xrf_report_items"), ("客户", "customer"),
               ("报告编号", "report_no"), ("分析日期", "analysis_date"), ("分析员", "analyst"),
               ("审核员", "reviewer"), ("报告项目顺序(JSON)", "report_order")]


def build_plan(db, sid):
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        raise BusinessExcelError("样品不存在")
    sample = dict(sample)
    wb = _new("sample-plan", "样品方案工作簿", [
        "可修改浅蓝色业务表。名称便于阅读，ID用于无歧义定位；ID与名称冲突时导入会拒绝。",
        "新建样品时会忽略导出的样品ID、LIMS编号、状态和更新标记，并生成新编号。",
        "覆盖现有样品必须保持样品ID、LIMS编号和更新标记一致。未改变的检测任务ID及结果会保留；删除或改变任务会明确覆盖其结果。",
        "多级稀释在稀释ID中用逗号分隔，在稀释名称中用 × 分隔，例如 1,1 / 5/250 × 5/250。",
        "不要使用公式。导入发现任何可编辑区域的公式都会拒绝整个文件。",
    ], sample)
    info = _sheet(wb, "样品信息", "样品基本信息", ["字段", "值"], {"字段": 28, "值": 55})
    for label, key in INFO_FIELDS:
        value = sample.get(key)
        if key == "report_order":
            value = value or "[]"
        _append(info, [label, value])
    if sample["workflow_type"] == "special":
        method = db.execute("SELECT * FROM special_methods WHERE id=%s", (sample["special_method_id"],)).fetchone()
        if not method:
            raise BusinessExcelError("专项样品的专项方法不存在，请先修复样品方案")
        prep = _sheet(wb, "溶样方案", "专项样品（无需溶样）", ["溶样ID", "溶样名称", "称样量(g)", "定容体积(mL)", "稀释ID", "稀释名称"])
        detect = _sheet(wb, "检测方案", "专项检测方案", ["任务ID", "溶样ID", "溶样名称", "项目ID", "分析项目", "仪器ID", "仪器", "方法ID", "方法", "报告选择"])
        _append(detect, ["", "", "原样", "", "专项", "", method["instrument"], method["id"], method["name"], ""])
    else:
        prep = _sheet(wb, "溶样方案", "溶样方案", ["溶样ID", "溶样名称", "称样量(g)", "定容体积(mL)", "稀释ID", "稀释名称"])
        for row in db.execute("SELECT * FROM preparations WHERE sample_id=%s ORDER BY id", (sid,)):
            try:
                dilution_ids = json.loads(row["dilution_steps"] or "[]")
            except json.JSONDecodeError:
                dilution_ids = []
            if not dilution_ids and row["dilution_id"] is not None:
                dilution_ids = [row["dilution_id"]]
            _append(prep, [row["id"], row["name"], row["mass_g"], row["volume_ml"],
                           ",".join(str(item) for item in dilution_ids), row["dilution_label"]])
        detect = _sheet(wb, "检测方案", "检测方案", ["任务ID", "溶样ID", "溶样名称", "项目ID", "分析项目", "仪器ID", "仪器", "方法ID", "方法", "报告选择"])
        for row in db.execute("""SELECT sa.*,p.name prep,a.name analyte,i.name instrument,m.name method
            FROM sample_analytes sa LEFT JOIN preparations p ON p.id=sa.preparation_id JOIN analytes a ON a.id=sa.analyte_id
            LEFT JOIN instruments i ON i.id=sa.instrument_id LEFT JOIN methods m ON m.id=sa.method_id
            WHERE sa.sample_id=%s ORDER BY sa.id""", (sid,)):
            _append(detect, [row["id"], row["preparation_id"], row["prep"] or "原样", row["analyte_id"], row["analyte"],
                              row["instrument_id"], row["instrument"], row["method_id"], row["method"], row["selection"]])
    _finish_table(prep, "PreparationPlan")
    _finish_table(detect, "DetectionPlan")
    return _bytes(wb), sample


def _metadata(wb, profile):
    if "说明" not in wb.sheetnames:
        raise BusinessExcelError("缺少“说明”工作表")
    ws = wb["说明"]
    values = {ws.cell(row, 1).value: ws.cell(row, 2).value for row in range(3, 11)}
    if values.get("工作簿格式") != FORMAT:
        raise BusinessExcelError("不是 toy-lims 业务工作簿")
    if values.get("格式版本") != VERSION:
        raise BusinessExcelError(f"不支持的工作簿版本：{values.get('格式版本')}")
    if values.get("业务类型") != profile:
        raise BusinessExcelError(f"工作簿业务类型错误，需要 {profile}")
    return values


def _open(stream, profile, sheets):
    try:
        wb = load_workbook(stream, data_only=False)
    except Exception as exc:
        raise BusinessExcelError("无法读取 .xlsx 文件，文件可能已损坏") from exc
    try:
        meta = _metadata(wb, profile)
        missing = [name for name in sheets if name not in wb.sheetnames]
        if missing:
            raise BusinessExcelError("缺少工作表：" + "、".join(missing))
        return wb, meta
    except Exception:
        wb.close()
        raise


def _records(ws, expected):
    actual = [ws.cell(3, col).value for col in range(1, len(expected) + 1)]
    if actual != expected:
        raise BusinessExcelError(f"“{ws.title}”表头不正确，请使用系统导出的原始模板")
    records = []
    for row in range(4, ws.max_row + 1):
        values = [ws.cell(row, col).value for col in range(1, len(expected) + 1)]
        if any(value not in (None, "") for value in values):
            records.append(dict(zip(expected, values)))
    return records


def _reject_formulas(wb, sheets):
    for name in sheets:
        for row in wb[name].iter_rows(min_row=4):
            for cell in row:
                if cell.data_type == "f":
                    raise BusinessExcelError(f"“{name}”{cell.coordinate} 不允许使用公式")


def _integer(value, label, optional=True):
    if value in (None, "") and optional:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise BusinessExcelError(f"{label}必须是整数ID") from exc
    return result


def _number(value, label):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise BusinessExcelError(f"{label}必须是数字")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BusinessExcelError(f"{label}必须是数字") from exc


def _resolve(db, table, value_id, name, label, extra=""):
    value_id = _integer(value_id, f"{label}ID")
    name = str(name or "").strip()
    if value_id is not None:
        row = db.execute(f"SELECT * FROM {table} WHERE id=%s {extra}", (value_id,)).fetchone()
        if not row:
            raise BusinessExcelError(f"{label}ID {value_id} 不存在或不可用")
        display = row["label"] if table == "dilutions" else row["name"]
        if name and name != display:
            raise BusinessExcelError(f"{label}ID与名称不一致：{value_id} / {name}")
        return value_id
    if not name:
        return None
    column = "label" if table == "dilutions" else "name"
    found = db.execute(f"SELECT id FROM {table} WHERE {column}=%s {extra}", (name,)).fetchall()
    if not found:
        raise BusinessExcelError(f"找不到{label}“{name}”")
    if len(found) > 1:
        raise BusinessExcelError(f"{label}名称“{name}”不唯一，请填写ID")
    return found[0]["id"]


def _resolve_dilution_chain(db, value_ids, names):
    id_parts = ([part.strip() for part in re.split(r"[,，]", str(value_ids)) if part.strip()]
                if value_ids not in (None, "") else [])
    name_parts = ([part.strip() for part in re.split(r"\s*[×xX]\s*", str(names)) if part.strip()]
                  if names not in (None, "") else [])
    if len(id_parts) > 8 or len(name_parts) > 8:
        raise BusinessExcelError("每路溶样最多支持 8 级稀释")
    if id_parts and name_parts and len(id_parts) != len(name_parts):
        raise BusinessExcelError("稀释ID级数与稀释名称级数不一致")
    count = max(len(id_parts), len(name_parts))
    return [_resolve(db, "dilutions", id_parts[index] if id_parts else None,
                     name_parts[index] if name_parts else None, f"第 {index + 1} 级稀释")
            for index in range(count)]


def parse_plan(stream, db):
    wb, meta = _open(stream, "sample-plan", ["样品信息", "溶样方案", "检测方案"])
    try:
        _reject_formulas(wb, ["样品信息", "溶样方案", "检测方案"])
        info_rows = _records(wb["样品信息"], ["字段", "值"])
        info = {row["字段"]: row["值"] for row in info_rows}
        labels = dict(INFO_FIELDS)
        data = {key: info.get(label) for label, key in INFO_FIELDS}
        data["id"] = _integer(data["id"], "样品ID")
        meta_id = _integer(meta.get("样品ID"), "说明页样品ID")
        if data["id"] != meta_id or str(data.get("lims_no") or "") != str(meta.get("样品编号") or "") or \
                str(data.get("updated_at") or "") != str(meta.get("更新标记") or ""):
            raise BusinessExcelError("说明页与样品信息页的样品身份不一致")
        data["name"] = str(data.get("name") or "").strip()
        if not data["name"]:
            raise BusinessExcelError("来样序号不能为空")
        data["workflow_type"] = "special" if str(data.get("workflow_type")) == "special" else "regular"
        data["is_liquid"] = int(str(data.get("is_liquid") or "0").lower() in {"1", "true", "是"})
        data["is_water_quality"] = int(str(data.get("is_water_quality") or "0").lower() in {"1", "true", "是"})
        if data["is_water_quality"]:
            data["is_liquid"] = 1
        data["xrf"] = int(str(data.get("xrf") or "0").lower() in {"1", "true", "是"})
        try:
            data["report_order"] = json.loads(str(data.get("report_order") or "[]"))
        except json.JSONDecodeError as exc:
            raise BusinessExcelError("报告项目顺序必须是JSON数组") from exc
        if not isinstance(data["report_order"], list):
            raise BusinessExcelError("报告项目顺序必须是JSON数组")
        prep_headers = ["溶样ID", "溶样名称", "称样量(g)", "定容体积(mL)", "稀释ID", "稀释名称"]
        task_headers = ["任务ID", "溶样ID", "溶样名称", "项目ID", "分析项目", "仪器ID", "仪器", "方法ID", "方法", "报告选择"]
        preps = []
        seen_prep_ids = set()
        for row in _records(wb["溶样方案"], prep_headers):
            name = str(row["溶样名称"] or "").strip()
            if not name:
                raise BusinessExcelError("溶样名称不能为空")
            prep_id = _integer(row["溶样ID"], "溶样ID")
            if prep_id is not None:
                if prep_id in seen_prep_ids:
                    raise BusinessExcelError(f"溶样ID {prep_id} 重复")
                seen_prep_ids.add(prep_id)
            dilution_ids = _resolve_dilution_chain(db, row["稀释ID"], row["稀释名称"])
            preps.append({"id": prep_id, "name": name,
                          "mass_g": _number(row["称样量(g)"], "称样量"),
                          "volume_ml": _number(row["定容体积(mL)"], "定容体积"),
                          "dilution_id": dilution_ids[0] if dilution_ids else None,
                          "dilution_ids": dilution_ids})
        tasks = []
        seen_task_ids = set()
        special_method_ids = set()
        for row in _records(wb["检测方案"], task_headers):
            task_id = _integer(row["任务ID"], "任务ID")
            if task_id is not None:
                if task_id in seen_task_ids:
                    raise BusinessExcelError(f"任务ID {task_id} 重复")
                seen_task_ids.add(task_id)
            if data["workflow_type"] == "special":
                method_id = _resolve(db, "special_methods", row["方法ID"], row["方法"], "专项方法", "AND active=1")
                if method_id is not None:
                    if special_method_ids and method_id not in special_method_ids:
                        raise BusinessExcelError("专项样品只能填写一个专项方法")
                    special_method_ids.add(method_id)
                    data["special_method_id"] = method_id
                continue
            aid = _resolve(db, "analytes", row["项目ID"], row["分析项目"], "分析项目")
            iid = _resolve(db, "instruments", row["仪器ID"], row["仪器"], "仪器")
            mid = _resolve(db, "methods", row["方法ID"], row["方法"], "方法")
            instrument = db.execute("SELECT itype FROM instruments WHERE id=%s", (iid,)).fetchone() if iid else None
            if iid and not db.execute("SELECT 1 FROM instr_analytes WHERE instrument_id=%s AND analyte_id=%s", (iid, aid)).fetchone():
                raise BusinessExcelError(f"仪器“{row['仪器']}”不能检测项目“{row['分析项目']}”")
            if mid and (not instrument or instrument["itype"] not in {"function", "xrf"}):
                raise BusinessExcelError("只有公式仪器或XRF仪器可以配置方法")
            if mid and not db.execute("SELECT 1 FROM methods WHERE id=%s AND itype=%s", (mid, instrument["itype"])).fetchone():
                raise BusinessExcelError(f"方法“{row['方法']}”与仪器类型不匹配")
            tasks.append({"id": task_id, "preparation_id": _integer(row["溶样ID"], "溶样ID"),
                          "prep_name": str(row["溶样名称"] or "").strip(), "analyte_id": aid,
                          "instrument_id": iid, "method_id": mid, "selection": row["报告选择"]})
        if data["workflow_type"] == "special" and not data.get("special_method_id"):
            raise BusinessExcelError("专项样品必须填写专项方法")
        data["preps"], data["tasks"] = preps, tasks
        return data, meta
    finally:
        wb.close()


DATA_HEADERS = ["任务ID", "溶样", "分析项目", "仪器", "方法", "读数ID", "序号", "原始读数", "参与平均", "终值",
                "公式变量(JSON)", "辅助校正(JSON)", "报告选择"]


def build_data(db, sid):
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        raise BusinessExcelError("样品不存在")
    sample = dict(sample)
    wb = _new("sample-data", "样品数据工作簿", [
        "数据录入表仅覆盖工作簿中出现的任务；同一任务的现有读数会由该任务在工作簿中的全部行原子替换。空白读数行会清空该任务数据。",
        "公式变量和辅助校正使用JSON对象，例如 {\"V\":12.3}、{\"use\":true,\"expected\":10,\"measured\":9.8}。",
        "专项数据只可修改“原始值”，计算值由系统重新计算；工作簿中已有字段留空表示清空，未出现在工作簿中的字段会保留。XRF结果只读，上传永远不会覆盖仪器数据。",
        "不要使用Excel公式；导入发现公式会拒绝整个文件。",
    ], sample)
    info = _sheet(wb, "样品", "样品标识（只读）", ["样品ID", "LIMS编号", "样品名称", "状态", "更新标记"], editable=False)
    _append(info, [sid, sample["lims_no"], sample["name"], sample["status"], sample["updated_at"]])
    data_ws = _sheet(wb, "数据录入", "常规数据录入", DATA_HEADERS,
                     {"公式变量(JSON)": 28, "辅助校正(JSON)": 36})
    special_ws = _sheet(wb, "专项数据", "专项原始数据录入", ["字段键", "分组", "字段名称", "单位", "原始值", "系统计算值", "必填"])
    if sample["workflow_type"] == "regular":
        tasks = db.execute("""SELECT sa.*,p.name prep,a.name analyte,i.name instrument,m.name method,r.aux
            FROM sample_analytes sa LEFT JOIN preparations p ON p.id=sa.preparation_id JOIN analytes a ON a.id=sa.analyte_id
            LEFT JOIN instruments i ON i.id=sa.instrument_id LEFT JOIN methods m ON m.id=sa.method_id
            LEFT JOIN results r ON r.sample_analyte_id=sa.id
            WHERE sa.sample_id=%s AND COALESCE(i.itype,'')!='xrf' ORDER BY sa.id""", (sid,)).fetchall()
        for task in tasks:
            readings = db.execute("SELECT * FROM readings WHERE sample_analyte_id=%s ORDER BY id", (task["id"],)).fetchall()
            if not readings:
                _append(data_ws, [task["id"], task["prep"] or "原样", task["analyte"], task["instrument"], task["method"],
                                  "", 1, "", 1, 0, "{}", task["aux"] or "{}", task["selection"]])
            for sequence, reading in enumerate(readings, 1):
                _append(data_ws, [task["id"], task["prep"] or "原样", task["analyte"], task["instrument"], task["method"],
                                  reading["id"], sequence, reading["raw"], reading["use_avg"], reading["is_final"],
                                  reading["extra"] or "{}", task["aux"] or "{}", task["selection"]])
    else:
        result = db.execute("""SELECT sr.*,sm.schema_json FROM special_results sr JOIN special_methods sm ON sm.id=sr.method_id
                               WHERE sr.sample_id=%s""", (sid,)).fetchone()
        if result:
            schema = json.loads(result["schema_json"] or "{}")
            raw = json.loads(result["raw_data"] or "{}")
            calculated = json.loads(result["calculated_data"] or "{}")
            for group in schema.get("groups", []):
                for field in group.get("fields", []):
                    _append(special_ws, [field.get("key"), group.get("name"), field.get("label"), field.get("unit"),
                                         raw.get(field.get("key")), calculated.get(field.get("key")), "是" if field.get("required") else "否"])
            _append(special_ws, ["note", "备注", "备注", "", raw.get("note"), "", "否"])
    xrf = _sheet(wb, "XRF结果", "仪器来源XRF结果（只读）", ["分析ID", "外部编号", "分析时间", "方法", "项目", "结果(%)", "用于报告"], editable=False)
    for row in db.execute("""SELECT xa.id,xa.external_id,xa.analyzed_at,xa.method,xv.name,xv.value,xv.use_report
        FROM xrf_analyses xa JOIN xrf_values xv ON xv.analysis_id=xa.id WHERE xa.sample_id=%s ORDER BY xa.id,xv.id""", (sid,)):
        _append(xrf, list(row))
    _finish_table(data_ws, "RegularData")
    _finish_table(special_ws, "SpecialData")
    _finish_table(xrf, "ReadonlyXrfData")
    return _bytes(wb), sample


def parse_data(stream):
    wb, meta = _open(stream, "sample-data", ["样品", "数据录入", "专项数据", "XRF结果"])
    try:
        _reject_formulas(wb, ["数据录入", "专项数据"])
        identity = _records(wb["样品"], ["样品ID", "LIMS编号", "样品名称", "状态", "更新标记"])
        if len(identity) != 1:
            raise BusinessExcelError("“样品”工作表必须保留一行样品标识")
        item = identity[0]
        if _integer(item["样品ID"], "样品ID") != _integer(meta.get("样品ID"), "说明页样品ID") or \
                str(item["LIMS编号"] or "") != str(meta.get("样品编号") or "") or \
                str(item["更新标记"] or "") != str(meta.get("更新标记") or ""):
            raise BusinessExcelError("说明页与样品页的样品身份不一致")
        regular = _records(wb["数据录入"], DATA_HEADERS)
        rows = []
        for row in regular:
            rows.append({"task_id": _integer(row["任务ID"], "任务ID", optional=False),
                         "reading_id": _integer(row["读数ID"], "读数ID"), "raw": _number(row["原始读数"], "原始读数"),
                         "use_avg": int(str(row["参与平均"] or "0").lower() in {"1", "true", "是"}),
                         "is_final": int(str(row["终值"] or "0").lower() in {"1", "true", "是"}),
                         "extra": _loads(row["公式变量(JSON)"], "公式变量"),
                         "aux": _loads(row["辅助校正(JSON)"], "辅助校正"), "selection": row["报告选择"]})
        special = {}
        for row in _records(wb["专项数据"], ["字段键", "分组", "字段名称", "单位", "原始值", "系统计算值", "必填"]):
            key = str(row["字段键"] or "").strip()
            if key:
                special[key] = row["原始值"]
        return {"identity": identity[0], "rows": rows, "special": special}, meta
    finally:
        wb.close()


def build_report(payload):
    sample = payload["sample"]
    draft = sample.get("status") != "reviewed"
    wb = _new("report", "分析报告" + ("（草稿）" if draft else ""), [
        "本工作簿与系统分析报告接口使用完全相同的计算数据。",
        "“草稿”表示样品尚未审核或发布；请勿作为正式签发报告使用。" if draft else "样品已进入审核/发布状态。",
        "原始记录和计算明细用于结果追溯。",
    ], sample)
    report = wb.create_sheet("分析报告")
    report.sheet_view.showGridLines = False
    report.merge_cells("A1:F1")
    report["A1"] = "分析报告" + (" - 草稿" if draft else "")
    report["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    report["A1"].fill = PatternFill("solid", fgColor=BLUE)
    report["A1"].alignment = Alignment(horizontal="center")
    for column, width in zip("ABCDEF", (10, 25, 18, 12, 18, 12)):
        report.column_dimensions[column].width = width
    metadata = [("LIMS编号", sample.get("lims_no")), ("来样序号", sample.get("name")),
                ("样品名称", sample.get("category")), ("客户", sample.get("customer")),
                ("报告编号", sample.get("report_no")), ("分析日期", sample.get("analysis_date")),
                ("分析员", sample.get("analyst")), ("审核员", sample.get("reviewer")), ("状态", sample.get("status"))]
    for index, (key, value) in enumerate(metadata, 1):
        report.cell(index + 1, 1, key).font = Font(bold=True, color=BLUE)
        _set_value(report.cell(index + 1, 2), value)
    # Keep tabular report below metadata and restore a dedicated header.
    header_row = 12
    headers = ["序号", "分析项目", "最终结果", "单位", "取值方式", "依据数"]
    for col, header in enumerate(headers, 1):
        cell = report.cell(header_row, col, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=BLUE)
    report.freeze_panes = "A13"
    if sample.get("workflow_type") == "special":
        special = payload.get("special") or {}
        schema = special.get("schema") or {}
        raw, calculated = special.get("raw_data") or {}, special.get("calculated_data") or {}
        index = 0
        for group in schema.get("groups", []):
            for field in group.get("fields", []):
                key = field.get("key")
                value = calculated.get(key, raw.get(key))
                if value not in (None, ""):
                    index += 1
                    report.append([index, field.get("label"), value, field.get("unit"), "系统计算" if key in calculated else "原始值", 1])
    else:
        manual = payload.get("manual_report")
        if manual:
            index = 0
            for row in payload.get("report_rows", []):
                if row.get("include", True):
                    index += 1
                    result = row.get("result")
                    try:
                        result = float(result)
                    except (TypeError, ValueError):
                        pass
                    report.append([index, row.get("item"), result, row.get("unit"),
                                   row.get("note") or "手工报告", 1])
        else:
            for index, group in enumerate(payload.get("groups", []), 1):
                final = group.get("final") or {}
                report.append([index, group["analyte"], final.get("value"), final.get("unit"), final.get("mode", "未完成"), final.get("based_on", 0)])
    raw_ws = _sheet(wb, "原始分析记录", "原始分析记录", ["项目", "溶样", "仪器", "方法", "原始值/变量", "参与", "换算值", "单位"])
    calc_ws = _sheet(wb, "计算明细", "计算明细", ["项目", "任务ID", "任务结果", "单位", "辅助校正", "报告选择"])
    if sample.get("workflow_type") == "special":
        special = payload.get("special") or {}
        for key, value in (special.get("raw_data") or {}).items():
            _append(raw_ws, [key, "原样", special.get("instrument"), special.get("method_name"), value, "是", "", ""])
        for key, value in (special.get("calculated_data") or {}).items():
            _append(calc_ws, [key, "", value, "", "专项公式", "是"])
    else:
        for group in payload.get("groups", []):
            for item in group.get("rows", []):
                for reading in item.get("readings", []):
                    _append(raw_ws, [group["analyte"], item.get("prep"), item.get("instrument"), item.get("method"),
                                     _json(reading.get("extra")) if reading.get("extra") else reading.get("raw"),
                                     "是" if reading.get("used") else "否", reading.get("corrected_value"), reading.get("unit")])
                _append(calc_ws, [group["analyte"], item.get("sample_analyte_id"), item.get("value"), item.get("unit"),
                                  _json(item.get("aux")), "否" if item.get("selection") == "exclude" else "是"])
    _finish_table(raw_ws, "RawAnalysisRecords")
    _finish_table(calc_ws, "CalculationDetails")
    return _bytes(wb)
