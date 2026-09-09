"""样品生命周期、正式编号和审计日志。"""

import json
from datetime import datetime

from flask import g, request


SAMPLE_STATUS_LABELS = {
    "received": "未制样",
    "queued": "未测量",
    "measuring": "测量中",
    "partially_done": "测量中",
    "completed": "待审核",
    "reviewed": "已审核",
    "cancelled": "已作废",
}

SAMPLE_TRANSITIONS = {
    "received": ("queued", "cancelled"),
    "queued": ("received", "measuring", "cancelled"),
    "measuring": ("queued", "completed", "cancelled"),
    "partially_done": ("measuring", "completed", "cancelled"),
    "completed": ("measuring", "reviewed", "cancelled"),
    "reviewed": (),
    "cancelled": (),
}

CAPABILITY_STATUS_TARGETS = {
    "sample_manage": {"received", "queued", "cancelled"},
    "result_edit": {"received", "queued", "measuring", "completed", "cancelled"},
    "review_release": {"completed", "reviewed"},
}


def jsonable(value):
    if value is None:
        return None
    if hasattr(value, "keys"):
        return {key: value[key] for key in value.keys()}
    return value


_AUDIT_MISSING = object()
_AUDIT_IGNORED_FIELDS = {"id", "created_at", "updated_at", "sample_status",
                         "status_operator", "status_action", "status_changed_at"}
_AUDIT_FIELD_LABELS = {
    "name": "来样序号", "sample_id": "LIMS 样品", "itype": "数据类型", "category": "样品名称", "is_liquid": "样品形态", "density_g_ml": "液体密度", "xrf": "XRF",
    "xrf_method_id": "XRF 方法", "xrf_report_items": "XRF 报告项目",
    "status": "状态", "tags": "样品标签", "report_order": "报告元素顺序", "report_excludes": "打印排除元素", "result_units": "结果显示单位", "customer": "来样单位",
    "report_no": "报告编号", "analysis_date": "分析日期", "analyst": "分析人",
    "reviewer": "审核人", "mass_g": "称样(g)", "volume_ml": "定容(mL)",
    "dilution_id": "稀释方式", "dilution_steps": "多级稀释", "dilution_factor": "稀释总倍数",
    "dilution_label": "稀释序列", "config_json": "组合配置",
    "instrument_id": "仪器", "method_id": "方法",
    "selection": "结果参与计算", "raw": "原始值", "extra": "滴定变量",
    "aux": "辅助数据", "expected": "标称", "measured": "回读", "use": "带标",
    "use_avg": "参与计算", "is_final": "终值标记", "active": "启用状态",
    "permissions": "能力", "display_name": "显示名称", "formula": "公式", "constants": "固定常数",
    "output_unit": "输出单位", "default_unit": "默认单位",
    "note": "备注", "factor": "倍数", "aliquot_ml": "移取体积(mL)",
    "final_volume_ml": "再次定容(mL)", "analyte_ids": "测定项目",
    "sort_order": "排序",
    "report_rows": "手工结果内容", "result": "结果", "unit": "单位",
    "source": "报告来源", "item": "报告项目",
    "report_profile_id": "报告版式", "company_name_cn": "公司中文名",
    "company_name_en": "公司英文名", "raw_code": "原始记录编号",
    "final_code": "分析报告票编号",
    "include": "参与报告", "items": "元素顺序",
    "preparations": "溶样", "tasks": "检测项目", "preparation": "溶样",
    "analyte": "元素", "instrument": "仪器", "method": "方法",
    # 专项检测原始表字段：审计界面只显示实验室业务名称，不暴露存储键。
    "time": "时间", "analysis_time": "分析时间", "pan_no": "盘号",
    "pan_weight": "盘重(g)", "sample_weight": "样重(g)",
    "dry_total": "干总重(g)", "moisture": "水分(%)",
    "ash_boat": "灰分舟重(g)", "ash_sample": "灰分样重(g)",
    "ash_total": "灰分烧后总重(g)", "ash": "灰分(%)",
    "water_dish": "分析水皿重(g)", "water_sample": "分析水样重(g)",
    "water_total": "分析水烘干后总重(g)", "analysis_water": "分析水(%)",
    "volatile_crucible": "挥发分坩埚重(g)", "volatile_sample": "挥发分样重(g)",
    "volatile_total": "挥发分烧后总重(g)", "volatile": "挥发分(%)",
    "sulfur": "硫 S(%)", "carbon": "碳 C(%)", "fixed_carbon": "固定碳(%)",
    "attached_pan": "附着水盘重(g)", "attached_sample": "附着水样重(g)",
    "attached_total": "45℃恒重总重(g)", "attached_constant": "附着水恒重样重(g)",
    "attached_water": "附着水(%)", "crystal_dish": "结晶水皿重(g)",
    "crystal_sample": "结晶水样重(g)", "crystal_total": "230℃恒重总重(g)",
    "crystal_constant": "结晶水恒重样重(g)", "crystal_water": "结晶水(%)",
    "dihydrate": "二水硫酸钙(%)", "cl_sample": "氯离子样重(g)",
    "cl_total_volume": "氯离子定容体积(mL)", "cl_aliquot": "氯离子移取体积(mL)",
    "agno3_c": "AgNO3浓度(mol/L)", "agno3_v": "消耗标准液(mL)",
    "chloride": "氯离子 Cl-(ppm)", "hhv": "高位热值 HHV(cal/g)",
    "lhv": "低位热值 LHV(cal/g)",
}


def _decode_audit_value(value):
    """把审计中的 JSON 字符串还原，避免只看到整段转义文本。"""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in {"{", "["}:
            try:
                return _decode_audit_value(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                return value
    if isinstance(value, dict):
        return {str(key): _decode_audit_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_audit_value(item) for item in value]
    return value


def _audit_payload(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return _decode_audit_value(jsonable(value))


def _audit_label(path):
    parts = [part for part in path.split(".") if part and not part.isdigit()]
    labels = []
    for part in parts:
        if part in {"sample", "task", "result", "special_result", "raw_data", "calculated_data"}:
            continue
        label = _AUDIT_FIELD_LABELS.get(part, part)
        if not labels or labels[-1] != label:
            labels.append(label)
    return " / ".join(labels) if labels else "内容"


def _audit_display(value, field):
    if value is _AUDIT_MISSING or value is None or value == "":
        return "—"
    if field.endswith("use_avg"):
        return "参与" if bool(value) else "不参与"
    if field.endswith("selection"):
        return "不参与" if value == "exclude" else "参与"
    if field.endswith("source"):
        return {"system": "系统计算", "manual": "手工报告"}.get(str(value), str(value))
    if field.endswith("status"):
        return SAMPLE_STATUS_LABELS.get(str(value), str(value))
    if field.endswith(("is_liquid", "xrf", "active", "use", "is_final", "include")):
        return "是" if bool(value) else "否"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return str(value)


def audit_changes(before, after, limit=30):
    """递归比较审计快照，只返回真正发生变化的字段。"""
    before_value = _audit_payload(before)
    after_value = _audit_payload(after)
    changes = []

    def item_hint(left, right):
        value = right if isinstance(right, dict) else left if isinstance(left, dict) else None
        if not value:
            return ""
        if value.get("name"):
            return str(value["name"])
        parts = [value.get("preparation"), value.get("analyte")]
        return " · ".join(str(part) for part in parts if part)

    def compare(left, right, path="", hint=""):
        if len(changes) >= limit:
            return
        blank_left = left is _AUDIT_MISSING or left is None or left == "" or left == {} or left == []
        blank_right = right is _AUDIT_MISSING or right is None or right == "" or right == {} or right == []
        if blank_left and blank_right:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key in _AUDIT_IGNORED_FIELDS:
                    continue
                compare(left.get(key, _AUDIT_MISSING), right.get(key, _AUDIT_MISSING),
                        f"{path}.{key}" if path else key, hint)
            return
        if left is _AUDIT_MISSING and isinstance(right, dict):
            hint = hint or item_hint(left, right)
            for key in sorted(right):
                if key not in _AUDIT_IGNORED_FIELDS:
                    compare(_AUDIT_MISSING, right[key], f"{path}.{key}" if path else key, hint)
            return
        if right is _AUDIT_MISSING and isinstance(left, dict):
            hint = hint or item_hint(left, right)
            for key in sorted(left):
                if key not in _AUDIT_IGNORED_FIELDS:
                    compare(left[key], _AUDIT_MISSING, f"{path}.{key}" if path else key, hint)
            return
        if isinstance(left, list) and isinstance(right, list):
            keyed = all(isinstance(item, dict) and "id" in item for item in left + right)
            if keyed:
                left_items = {str(item["id"]): item for item in left}
                right_items = {str(item["id"]): item for item in right}
                keys = sorted(set(left_items) | set(right_items), key=lambda key: int(key))
            else:
                left_items = {str(index): item for index, item in enumerate(left)}
                right_items = {str(index): item for index, item in enumerate(right)}
                keys = [str(index) for index in range(max(len(left), len(right)))]
            for key in keys:
                left_item = left_items.get(key, _AUDIT_MISSING)
                right_item = right_items.get(key, _AUDIT_MISSING)
                compare(left_item, right_item, f"{path}.{key}" if path else key,
                        item_hint(left_item, right_item) or hint)
            return
        if left is _AUDIT_MISSING and isinstance(right, list):
            for index, value in enumerate(right):
                compare(_AUDIT_MISSING, value, f"{path}.{index}" if path else str(index),
                        item_hint(_AUDIT_MISSING, value) or hint)
            return
        if right is _AUDIT_MISSING and isinstance(left, list):
            for index, value in enumerate(left):
                compare(value, _AUDIT_MISSING, f"{path}.{index}" if path else str(index),
                        item_hint(value, _AUDIT_MISSING) or hint)
            return
        if left == right:
            return
        label = _audit_label(path)
        if hint:
            label = f"{label}（{hint}）"
        changes.append({
            "field": path or "内容",
            "label": label,
            "before": _audit_display(left, path),
            "after": _audit_display(right, path),
        })

    compare(before_value if before_value is not None else _AUDIT_MISSING,
            after_value if after_value is not None else _AUDIT_MISSING)
    return changes


def audit_event(db, action, entity_type, entity_id=None, before=None, after=None,
                reason="", user=None):
    """在同一业务事务中写审计；调用方负责 commit。"""
    before_value = jsonable(before)
    after_value = jsonable(after)
    if before is not None and after is not None and not audit_changes(before_value, after_value, limit=1):
        return False
    actor = user if user is not None else getattr(g, "user", None)
    try:
        user_id = actor["id"] if actor else None
        username = actor["username"] if actor else "system"
    except (KeyError, TypeError, IndexError):
        user_id, username = None, "system"
    terminal = getattr(g, "terminal", None)
    try:
        terminal_id = terminal["id"] if terminal else None
        terminal_name = terminal["name"] if terminal else None
    except (KeyError, TypeError, IndexError):
        terminal_id, terminal_name = None, None
    db.execute("""INSERT INTO audit_logs(
        user_id,username,terminal_id,terminal_name,action,entity_type,entity_id,
        before_json,after_json,reason,ip_address) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
        user_id, username or "system", terminal_id, terminal_name, action, entity_type,
        str(entity_id) if entity_id is not None else None,
        json.dumps(before_value, ensure_ascii=False, default=str) if before is not None else None,
        json.dumps(after_value, ensure_ascii=False, default=str) if after is not None else None,
        reason.strip(), request.remote_addr if request else "",
    ))
    return True


def next_lims_no(db, business_date=None):
    day = (business_date or datetime.now()).strftime("%Y%m%d")
    number = db.execute("""INSERT INTO number_sequences(day,last_number) VALUES(%s,1)
        ON CONFLICT(day) DO UPDATE SET last_number=number_sequences.last_number+1
        RETURNING last_number""", (day,)).fetchone()[0]
    return f"{day}-{number:03d}"


def can_transition(permissions, current, target):
    allowed_targets = set().union(*(
        CAPABILITY_STATUS_TARGETS.get(permission, set()) for permission in permissions))
    return (target in SAMPLE_TRANSITIONS.get(current, ()) and
            target in allowed_targets)


def recompute_sample_progress(db, sample_id):
    """根据任务完成度更新检测阶段，不覆盖审核、报告、作废状态。"""
    sample = db.execute("SELECT status,xrf FROM samples WHERE id=%s", (sample_id,)).fetchone()
    if not sample or sample[0] not in {
            "received", "queued", "measuring", "partially_done", "completed"}:
        return
    counts = db.execute("""SELECT COUNT(*),
        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
        SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END)
        FROM sample_analytes sa LEFT JOIN instruments i ON i.id=sa.instrument_id
        WHERE sa.sample_id=%s AND sa.status!='cancelled' AND COALESCE(i.itype,'')!='xrf'""",
        (sample_id,)).fetchone()
    total, completed, in_progress = counts[0] or 0, counts[1] or 0, counts[2] or 0
    if sample[1]:
        total += 1
        if db.execute("SELECT 1 FROM xrf_analyses WHERE sample_id=%s LIMIT 1",
                      (sample_id,)).fetchone():
            completed += 1
    if sample[0] in {"received", "queued"}:
        status = sample[0]
    elif total and completed == total:
        status = "completed"
    elif completed:
        status = "partially_done"
    elif in_progress:
        status = "measuring"
    else:
        status = sample[0] if sample[0] == "received" else "queued"
    db.execute("UPDATE samples SET status=%s,updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s",
               (status, sample_id))


def recompute_task_progress(db, task_id):
    task = db.execute("SELECT sample_id,instrument_id FROM sample_analytes WHERE id=%s",
                      (task_id,)).fetchone()
    if not task:
        return
    has_value = db.execute("""SELECT 1 FROM readings WHERE sample_analyte_id=%s
            AND (raw IS NOT NULL OR (extra IS NOT NULL AND extra NOT IN ('', '{}', 'null')))
        UNION ALL SELECT 1 FROM results WHERE sample_analyte_id=%s
            AND (raw IS NOT NULL OR (extra IS NOT NULL AND extra NOT IN ('', '{}', 'null'))) LIMIT 1""",
        (task_id, task_id)).fetchone()
    status = "completed" if has_value else ("in_progress" if task["instrument_id"] else "pending")
    db.execute("UPDATE sample_analytes SET status=%s WHERE id=%s", (status, task_id))
    recompute_sample_progress(db, task["sample_id"])
