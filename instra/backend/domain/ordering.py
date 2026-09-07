"""元素/结果项排序：与 toy-lims 同语义，唯一权威实现。

规则（PLAN §7）：
1. 顺序模板（或样品级 report_order）中出现的名字按模板位次排；
2. 未出现的名字排在已知名字之后，按名称排序（大小写不敏感）——
   定量结果中的氧化物名、原始通道名（如 "Ag Ka 1,2net"）都走这条兜底。
"""

import json


def normalize(token):
    return str(token or "").strip().casefold()


def order_items(names, order_list):
    """按顺序模板排序；未知名字排尾部按名称排序。输入去重（保留首次出现的写法）。"""
    index = {}
    for position, item in enumerate(order_list or []):
        key = normalize(item)
        if key and key not in index:
            index[key] = position
    seen, unique = set(), []
    for name in names:
        key = normalize(name)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(str(name).strip())
    known = sorted((n for n in unique if normalize(n) in index),
                   key=lambda n: index[normalize(n)])
    unknown = sorted((n for n in unique if normalize(n) not in index),
                     key=lambda n: normalize(n))
    return known + unknown


def load_order_list(db, template_id=None):
    """读取顺序模板的项目列表；template_id 为空或无效时用系统默认模板。"""
    row = None
    if template_id:
        row = db.execute("SELECT items_json FROM result_order_templates WHERE id=?",
                         (template_id,)).fetchone()
    if row is None:
        row = db.execute("""SELECT items_json FROM result_order_templates
            WHERE is_default=1 ORDER BY id LIMIT 1""").fetchone()
    if row is None:
        row = db.execute("""SELECT items_json FROM result_order_templates
            ORDER BY id LIMIT 1""").fetchone()
    if row is None:
        return []
    try:
        items = json.loads(row["items_json"] or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def load_sample_report_order(db, sample_id):
    """样品级报告顺序覆盖；无覆盖返回 []。"""
    row = db.execute("SELECT report_order FROM samples WHERE id=?",
                     (sample_id,)).fetchone()
    if row is None:
        return []
    try:
        items = json.loads(row["report_order"] or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item).strip() for item in items if str(item).strip()]
