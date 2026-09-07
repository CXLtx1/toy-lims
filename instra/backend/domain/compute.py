"""读数计算与显示单位换算：移植 toy-lims app.py 的同名逻辑（语义一致，只读用途）。

包含：公式方法求值（AST 白名单）、按仪器类型的读数换算（滴定/比色/ppm/ppb/公式…）、
回标系数、任务级终值聚合、显示单位换算链（% ↔ ppm ↔ ppb ↔ g/L ↔ mg/L ↔ ug/L，液体密度参与）。
"""

import ast
import json
import math
import operator

_SPECIAL_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                   ast.Div: operator.truediv, ast.Pow: operator.pow}
_SPECIAL_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

METHOD_FIXED_VARS = {"m", "v"}


def special_formula_value(expression, values):
    """只允许数字、字段名和基本四则运算的计算公式。"""

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in values:
            return float(values[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _SPECIAL_BINOPS:
            return _SPECIAL_BINOPS[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SPECIAL_UNARYOPS:
            return _SPECIAL_UNARYOPS[type(node.op)](evaluate(node.operand))
        raise ValueError("公式包含不允许的内容")

    return evaluate(ast.parse(expression, mode="eval"))


def formula_variables(expression):
    """校验公式并返回变量名（按出现顺序）。"""
    if not expression or len(expression) > 500:
        raise ValueError("公式不能为空且不能超过 500 个字符")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("公式语法不正确") from exc
    variables = []

    def validate(node):
        if isinstance(node, ast.Expression):
            validate(node.body)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
              and not isinstance(node.value, bool)):
            return
        elif isinstance(node, ast.Name) and node.id and len(node.id) <= 32:
            if node.id not in variables:
                variables.append(node.id)
        elif isinstance(node, ast.BinOp) and type(node.op) in _SPECIAL_BINOPS:
            validate(node.left)
            validate(node.right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _SPECIAL_UNARYOPS:
            validate(node.operand)
        else:
            raise ValueError("公式只允许变量、数字、括号和 + - * / ** 运算")

    validate(tree)
    if len(variables) > 30:
        raise ValueError("一个公式最多使用 30 个变量")
    return variables


def aux_coefficient(aux):
    """回标系数：优先旧格式 coefficient，否则 expected/measured。"""
    if not aux.get("use"):
        return 1.0
    if aux.get("coefficient"):
        return float(aux["coefficient"])
    if aux.get("expected") and aux.get("measured"):
        return float(aux["expected"]) / float(aux["measured"])
    return 1.0


def reading_value(sa, is_liquid, raw, extra):
    """单个读数换算。sa 需含 itype/prep_factor/formula/method_constants/prep_mass/prep_vol。
    返回 (数值, 单位) 或 (None, 说明)。"""
    it = sa["itype"]
    if not it:
        return (None, "未选仪器")
    if it == "ph":
        return (raw, "pH") if raw is not None else (None, "未录入")
    if it == "mol":
        return (raw, "mol/L") if raw is not None else (None, "未录入")
    if it == "xrf":
        return (raw, "%") if raw is not None else (None, "未录入")
    factor = sa["prep_factor"] or 1
    if it == "function":
        if not sa["formula"]:
            return (None, "未选方法")
        try:
            required = formula_variables(sa["formula"])
            constants = json.loads(sa["method_constants"] or "{}")
            env = {key: float(value) for key, value in (extra or {}).items() if key in required}
            env.update({key: float(value) for key, value in constants.items() if key in required})
            fixed_sources = {"m": sa["prep_mass"], "v": sa["prep_vol"]}
            for variable in METHOD_FIXED_VARS:
                if fixed_sources[variable] is not None:
                    env[variable] = float(fixed_sources[variable])
            missing = [variable for variable in required if variable not in env]
            if missing:
                return (None, "缺少" + "/".join(missing))
            val = special_formula_value(sa["formula"], env)
            if not math.isfinite(float(val)):
                raise ValueError("计算结果不是有限数值")
            output_unit = sa.get("method_output_unit") or "%"
            if is_liquid and output_unit == "ppm":
                output_unit = "mg/L"
            elif is_liquid and output_unit == "ppb":
                output_unit = "ug/L"
            return (float(val), output_unit)
        except Exception as exc:
            return (None, f"公式错误: {exc}")
    if raw is None:
        return (None, "未录入")
    if it == "percent":
        return (raw, "%")
    if it == "ppb":
        if is_liquid:
            return (raw * factor, "ug/L")
        if not sa["prep_mass"] or not sa["prep_vol"]:
            return (None, "缺称样量/定容体积")
        # w% = C(μg/L) * V(mL) * D / (m(g) * 10^7)
        return (raw * sa["prep_vol"] * factor / (sa["prep_mass"] * 10000000), "%")
    if it == "ppm" and is_liquid:
        return (raw * factor, "mg/L")
    if it != "ppm":
        return (None, "未知仪器类型")
    if not sa["prep_mass"] or not sa["prep_vol"]:
        return (None, "缺称样量/定容体积")
    # w% = C(mg/L) * V(mL) * D / (m(g) * 10^4)
    return (raw * sa["prep_vol"] * factor / (sa["prep_mass"] * 10000), "%")


def normalized_result_unit(unit):
    value = str(unit or "").strip()
    return "ug/L" if value in {"μg/L", "µg/L", "ug/L"} else value


def convert_result_unit(value, source_unit, target_unit, density=None):
    """仅换算显示单位，不改变存储的分析值。"""
    source = normalized_result_unit(source_unit)
    target = normalized_result_unit(target_unit)
    if value is None or source == target:
        return value
    mass_to_percent = {"%": 1.0, "ppm": 1e-4, "ppb": 1e-7}
    volume_to_g_l = {"g/L": 1.0, "mg/L": 1e-3, "ug/L": 1e-6}
    if source in mass_to_percent:
        percent = float(value) * mass_to_percent[source]
        if target in mass_to_percent:
            return percent / mass_to_percent[target]
        if target in volume_to_g_l and density:
            return percent * float(density) * 10 / volume_to_g_l[target]
    if source in volume_to_g_l:
        grams_litre = float(value) * volume_to_g_l[source]
        if target in volume_to_g_l:
            return grams_litre / volume_to_g_l[target]
        if target in mass_to_percent and density:
            percent = grams_litre / (float(density) * 10)
            return percent / mass_to_percent[target]
    raise ValueError("所选单位不能从当前结果口径换算")


def result_unit_options(source_unit, density=None):
    source = normalized_result_unit(source_unit)
    mass_units = ["%", "ppm", "ppb"]
    volume_units = ["g/L", "mg/L", "ug/L"]
    if source in mass_units:
        return mass_units + (volume_units if density else [])
    if source in volume_units:
        return volume_units + (mass_units if density else [])
    return [source] if source else []


def rounded_display_value(value, unit, xrf=False):
    if value is None:
        return None
    if xrf:
        return float(f"{float(value):.5g}")
    magnitude = abs(float(value))
    if magnitude >= 100000:
        return float(f"{float(value):.7g}")
    return round(float(value), 6 if unit in {"%", "g/L"} else 4)


def calc_result(sa, is_liquid):
    """任务级结果：只聚合勾选参与的读数，再乘回标系数。
    返回 (数值, 单位/说明, 读数明细列表)。"""
    aux = sa.get("aux") or {}
    if isinstance(aux, str):
        aux = json.loads(aux or "{}")
    coeff = aux_coefficient(aux)
    readings = sa.get("readings") or []
    if not readings:
        # 兼容未被迁移的旧单值
        if sa["raw"] is not None or sa.get("extra") not in (None, "", "{}"):
            extra = sa.get("extra")
            if isinstance(extra, str):
                extra = json.loads(extra or "{}")
            readings = [{"raw": sa["raw"], "extra": extra, "use_avg": 1, "is_final": 0}]
    if not readings:
        return (None, "未录入" if sa["itype"] else "未选仪器", [])
    details = []
    for rd in readings:
        extra = rd.get("extra")
        if isinstance(extra, str):
            extra = json.loads(extra or "{}")
        val, unit = reading_value(sa, is_liquid, rd.get("raw"), extra)
        details.append({
            "raw": rd.get("raw"), "extra": extra or {}, "value": val, "unit": unit,
            "used": bool(rd.get("use_avg")) or bool(rd.get("is_final")),
            "is_final": bool(rd.get("is_final")),
        })
    finals = [d for d in details if d["is_final"] and d["value"] is not None]
    included = [d for d in details if d["used"] and not d["is_final"] and d["value"] is not None]
    chosen = finals or included
    for d in details:
        d["used"] = d in chosen
        d["corrected_value"] = (round(d["value"] * coeff, 4)
                                if d["value"] is not None else None)
    if not chosen:
        # 没有有效读数时，取第一条的说明作为提示
        return (None, details[0]["unit"], details)
    avg = sum(d["value"] for d in chosen) / len(chosen)
    return (round(avg * coeff, 4), chosen[0]["unit"], details)
