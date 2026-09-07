"""UniQuant 单页 PDF：氧化物 / 元素逐行对应，右侧显示精简关键参数。"""

import math
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from domain import conversion, format as value_format, ordering

TEMPLATES = Path(__file__).resolve().parent / "templates"
_jinja = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                     autoescape=select_autoescape(["html"]))

# 单页右栏只保留中文参数；Shape/Case/Kappa/Sector/Rest/DoS 等不输出。
OPTION_LABELS = (
    ("chemistry", "化学表示"),
    ("atmosphere", "气氛"),
    ("report_level", "报告限(ppm)"),
    ("area", "面积"),
    ("diameter", "直径"),
    ("gross_diameter", "总直径"),
    ("mass", "质量"),
    ("gross_mass", "总质量"),
    ("height", "高度"),
    ("rho", "密度"),
    ("shadow_loss", "阴影损耗"),
    ("known_conc", "已知浓度"),
    ("film", "膜片"),
    ("processed", "已再处理"),
)


def _option_items(options, item):
    """关键选项 [(名, 值)]：严格白名单，不泄露内部或英文参数。"""
    merged = dict(options or {})
    for key in ("film", "processed"):
        if item.get(key) not in (None, "") and key not in merged:
            merged[key] = item[key]
    shown = []
    for key, label in OPTION_LABELS:
        if key in merged and merged[key] not in (None, ""):
            value = merged[key]
            if key == "chemistry":
                value = {1: "氧化物", "1": "氧化物", "oxide": "氧化物"}.get(value, "元素")
            elif key == "atmosphere" and value in (0, "0"):
                value = "真空"
            elif key == "processed":
                value = "是" if value in (1, True, "1", "true") else "否"
            elif isinstance(value, float):
                value = f"{value:.6g}"
            shown.append((label, value))
    return shown


def _report_pairs(composition, elements, oxides, order_list, units=None,
                  significant_digits=5, order_mode="content"):
    """生成同序双栏数据和各口径合计。"""
    pairs = conversion.composition_pairs(composition, elements, oxides)
    rank = {conversion.normalize(name): i for i, name in enumerate(order_list)}

    def pair_rank(indexed):
        index, pair = indexed
        candidates = [conversion.normalize(name) for name in
                      (pair["oxide_name"], pair["element_name"]) if name]
        matched = [rank[name] for name in candidates if name in rank]
        return (min(matched) if matched else len(rank), index)

    if order_mode == "content":
        pairs = sorted(pairs, key=lambda pair: -abs(float(
            pair["element_value"] if pair["element_value"] is not None
            else pair["oxide_value"])))
    else:
        pairs = [pair for _, pair in sorted(enumerate(pairs), key=pair_rank)]
    oxide_total = math.fsum(float(pair["oxide_value"])
                            for pair in pairs if pair["oxide_value"] is not None)
    element_total = math.fsum(float(pair["element_value"])
                              for pair in pairs if pair["element_value"] is not None)
    units = units or {}
    for pair in pairs:
        key = conversion.composition_pair_key(pair)
        maximum = max(abs(float(value)) for value in
                      (pair["oxide_value"], pair["element_value"]) if value is not None)
        unit = units.get(key) or value_format.default_xrf_unit(maximum)
        pair["unit"] = unit
        pair["oxide_display"] = (value_format.fmt_export_number(
            value_format.convert_percent(pair["oxide_value"], unit), significant_digits)
            if pair["oxide_value"] is not None else "—")
        pair["element_display"] = (value_format.fmt_export_number(
            value_format.convert_percent(pair["element_value"], unit), significant_digits)
            if pair["element_value"] is not None else "—")
    return pairs, oxide_total, element_total


def build_uq_pdf(db, item, order_template_id=None, units=None, significant_digits=5,
                 order_mode="content"):
    """item 为 api.xrf.load_uq_detail 的返回；返回 PDF 字节。"""
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError("服务端未安装 WeasyPrint（及其 Pango 依赖），无法生成 PDF") from exc

    elements, oxides = conversion.load_reference(db)
    order_list = ordering.load_order_list(db, order_template_id)

    pairs, oxide_total, element_total = _report_pairs(
        item["composition"], elements, oxides, order_list, units,
        significant_digits, order_mode)

    html = _jinja.get_template("uq_report.html").render(
        item=item,
        options=_option_items(item.get("options"), item),
        pairs=pairs,
        oxide_total=value_format.fmt_export_number(oxide_total, significant_digits),
        element_total=value_format.fmt_export_number(element_total, significant_digits),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return HTML(string=html, base_url=str(TEMPLATES)).write_pdf()


def uq_pdf_filename(item):
    name = (item.get("lims_name") or item.get("sample_name") or "uq").strip()
    safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in name)
    return f"UQ-{safe}-{item.get('external_id') or item.get('id')}.pdf"
