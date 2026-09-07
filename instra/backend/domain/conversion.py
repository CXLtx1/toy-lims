"""元素↔氧化物口径换算：移植 toy-lims 语义（app.py _xrf_reference/_element_to_target_factor）。

系数一律取自 common_oxides 表，不写死。规则：
- 直取优先：名字本身就是目标口径时不动；
- 元素→氧化物 ×factor；氧化物→元素 ÷factor；
- 元素→氧化物不唯一（Fe→FeO/Fe2O3/Fe3O4）时取惯用氧化物（is_conventional）；
- 两者无关（未知通道名等）时不可换算，调用方决定保留或跳过。
"""


def normalize(token):
    return str(token or "").strip().casefold()


def load_reference(db):
    """返回 (elements, oxides)：
    elements: {symbol.casefold(): symbol}
    oxides:   {formula.casefold(): {"formula", "element", "factor", "conventional"}}
    """
    elements = {row["symbol"].casefold(): row["symbol"]
                for row in db.execute("SELECT symbol FROM chemical_elements")}
    oxides = {}
    for row in db.execute("""SELECT formula,element_symbol,element_to_oxide_factor,is_conventional
        FROM common_oxides"""):
        oxides[row["formula"].casefold()] = {
            "formula": row["formula"], "element": row["element_symbol"],
            "factor": float(row["element_to_oxide_factor"]),
            "conventional": bool(row["is_conventional"])}
    return elements, oxides


def name_kind(name, elements, oxides):
    """判断名字属于 element / oxide / unknown。"""
    key = normalize(name)
    if key in elements:
        return "element"
    if key in oxides:
        return "oxide"
    return "unknown"


def conversion_factor(source, target, oxides):
    """source 名字的值换算成 target 口径的系数；无关系返回 (None, '')。

    返回 (factor, note)，note 形如 "Fe × 1.43" 或 "Fe2O3 ÷ 1.43"。
    """
    skey, tkey = normalize(source), normalize(target)
    if skey == tkey:
        return 1.0, ""
    if tkey in oxides and oxides[tkey]["element"].casefold() == skey:
        factor = oxides[tkey]["factor"]
        return factor, f"{source} × {factor:.4g}"
    if skey in oxides and oxides[skey]["element"].casefold() == tkey:
        factor = 1.0 / oxides[skey]["factor"]
        return factor, f"{source} ÷ {oxides[skey]['factor']:.4g}"
    return None, ""


def convert_value(source, target, value, oxides):
    """换算数值；不可换算返回 (None, '')。"""
    factor, note = conversion_factor(source, target, oxides)
    if factor is None:
        return None, ""
    return value * factor, note


def conventional_oxide(element_symbol, oxides):
    """元素的惯用氧化物；没有返回 None。"""
    key = normalize(element_symbol)
    for oxide in oxides.values():
        if oxide["conventional"] and oxide["element"].casefold() == key:
            return oxide["formula"]
    return None


def to_basis(name, alt_name, value, basis, elements, oxides):
    """把一项结果转换为指定口径，返回 (显示名, 显示值, 换算说明)。

    优先级：name 本身符合 → alt_name 符合（必要时换算）→ 按参考表换算 name
    （氧化物→元素唯一；元素→惯用氧化物）→ 都不符合则原样保留并注明。
    """
    candidates = [n for n in (name, alt_name) if n]
    for candidate in candidates:
        if name_kind(candidate, elements, oxides) != basis:
            continue
        if candidate.casefold() == normalize(name):
            return candidate, value, ""
        converted, note = convert_value(name, candidate, value, oxides)
        if converted is not None:
            return candidate, converted, note
    # alt 缺失时按参考表换算 name 本身
    kind = name_kind(name, elements, oxides)
    target = None
    if basis == "element" and kind == "oxide":
        target = oxides[normalize(name)]["element"]
    elif basis == "oxide" and kind == "element":
        target = conventional_oxide(name, oxides)
    if target:
        converted, note = convert_value(name, target, value, oxides)
        if converted is not None:
            return target, converted, note
    return name, value, "未换算（无对应口径）" if kind != "unknown" else ""


def composition_pairs(composition, elements, oxides):
    """把最终组成整理为「左氧化物 / 右元素」成对展示。

    每项返回 {"oxide_name","oxide_value","element_name","element_value"}：
    - 氧化物名 → ÷factor 得元素；
    - 元素名 → ×惯用氧化物 factor 得氧化物；无惯用氧化物时左右重复元素名和值；
    - 未知口径原样放左侧，不换算。
    """
    pairs = []
    for v in composition:
        name, value = v["name"], v.get("value")
        pair = {"oxide_name": None, "oxide_value": None,
                "element_name": None, "element_value": None}
        kind = name_kind(name, elements, oxides)
        if kind == "oxide":
            ref = oxides[normalize(name)]
            pair["oxide_name"] = name
            pair["oxide_value"] = value
            pair["element_name"] = ref["element"]
            pair["element_value"] = (value / ref["factor"]
                                     if value is not None else None)
        elif kind == "element":
            pair["element_name"] = name
            pair["element_value"] = value
            conv = conventional_oxide(name, oxides)
            if conv:
                ref = oxides[normalize(conv)]
                pair["oxide_name"] = conv
                pair["oxide_value"] = (value * ref["factor"]
                                       if value is not None else None)
            else:
                pair["oxide_name"] = name
                pair["oxide_value"] = value
        else:
            pair["oxide_name"] = name
            pair["oxide_value"] = value
        pairs.append(pair)
    return pairs


def composition_pair_key(pair):
    """元素/氧化物对的稳定导出键；同一对在不同扫描和口径下保持一致。"""
    return f"{normalize(pair.get('oxide_name'))}|{normalize(pair.get('element_name'))}"


def composition_pair_label(pair):
    """导出界面的紧凑标签，例如 CaO / Ca；Cl / Cl 简化为 Cl。"""
    oxide, element = pair.get("oxide_name"), pair.get("element_name")
    if oxide and element and normalize(oxide) != normalize(element):
        return f"{oxide} / {element}"
    return oxide or element or "—"
