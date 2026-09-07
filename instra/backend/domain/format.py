"""XRF 数值格式、单位换算与有效数字规则。"""

import math


UNIT_MULTIPLIERS = {"%": 1.0, "ppm": 10_000.0, "ppb": 10_000_000.0}


def fmt_number(value, precision=5):
    """toPrecision(5) 语义：有效数字截断并去尾零；空值返回 '—'。"""
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.{precision}g}"


def default_xrf_unit(percent_value):
    """按百分比原值推荐单位：≥0.1% 用 %，≥1 ppm 用 ppm，其余用 ppb。"""
    value = abs(float(percent_value or 0))
    if value >= 0.1:
        return "%"
    if value * UNIT_MULTIPLIERS["ppm"] >= 1:
        return "ppm"
    return "ppb"


def convert_percent(value, unit):
    """把数据库中的百分比值换算为指定单位。"""
    if unit not in UNIT_MULTIPLIERS:
        raise ValueError(f"不支持的 XRF 单位：{unit}")
    return float(value) * UNIT_MULTIPLIERS[unit]


def round_significant(value, digits=5):
    """返回数值型的有效数字舍入结果；0 保持为 0。"""
    number = float(value)
    if not math.isfinite(number) or number == 0:
        return number
    places = digits - math.floor(math.log10(abs(number))) - 1
    return round(number, places)


def fmt_export_number(value, digits=5):
    """有效数字格式化且不用科学计数法，适合 PDF/报表阅读。"""
    number = round_significant(value, digits)
    if not math.isfinite(number):
        return str(number)
    if number == 0:
        return "0"
    places = max(0, digits - math.floor(math.log10(abs(number))) - 1)
    text = f"{number:.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
