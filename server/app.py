# -*- coding: utf-8 -*-
"""LabFlow: Flask, PostgreSQL, and the built Vue frontend."""
import gzip
import json
import ast
import hashlib
import logging
import math
import os
import operator
import re
import secrets
import threading
import time
from functools import wraps
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from uuid import UUID
from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from business_excel import (BusinessExcelError, MIME as EXCEL_MIME, build_data,
                            build_overview, build_plan, build_report,
                            parse_data, parse_plan)
from db_backend import DATABASE_ERRORS, INTEGRITY_ERRORS, connect_database
from db_schema import initialize_database
from lims_auth import (CAPABILITIES, bp as auth_bp,
                       authenticate_capable_user, capability_required, consume_forced_authorization,
                       extend_write_authorization, load_user,
                       login_required_before_request, user_permissions)
from lims_workflow import (CAPABILITY_STATUS_TARGETS, SAMPLE_STATUS_LABELS, SAMPLE_TRANSITIONS, audit_changes, audit_event,
                           can_transition, next_lims_no,
                           recompute_sample_progress, recompute_task_progress)
from result_report_excel import build_result_report
from mutation_guard import (locked_row, lock_reading, lock_reading_task,
                             next_updated_at, reading_version, stable_hash)
from security import init_security

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
BASE_DIR = Path(__file__).resolve().parent
# Vite build output (frontend/dist, base=/frontend/).
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

# 反向代理部署时设 LIMS_TRUST_PROXY=1：request.remote_addr 改读 X-Forwarded-For，
# 审计、请求日志和仪器页才能显示真实来源 IP；直连部署不要开启（头可被伪造）。
if os.environ.get("LIMS_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# 请求日志开关：设为 False 后不创建日志目录，也不写请求日志。
REQUEST_LOG_ENABLED = False

app.secret_key = os.environ.get("LIMS_SECRET_KEY")
if not app.secret_key:
    secret_file = BASE_DIR / "instance" / "secret_key"
    secret_file.parent.mkdir(exist_ok=True)
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32), encoding="ascii")
    app.secret_key = secret_file.read_text(encoding="ascii").strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")

# No implicit database or embedded credentials.
DB = os.environ.get("LIMS_DATABASE_URL")
# Instrument tokens must also be configured for loopback clients.
XRF_CLIENT_TOKEN = os.environ.get("LIMS_XRF_CLIENT_TOKEN", "").strip() or ""
STANDARD_CLIENT_TOKEN = os.environ.get("LIMS_STANDARD_CLIENT_TOKEN", "").strip() or ""
LOG_DIR = Path(os.environ.get("LIMS_LOG_DIR", str(BASE_DIR / "logs")))
REQUEST_LOGGER = logging.getLogger("toy_lims.requests")
if REQUEST_LOG_ENABLED and not REQUEST_LOGGER.handlers:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    request_log_handler = TimedRotatingFileHandler(
        LOG_DIR / "requests.log", when="midnight", interval=1,
        backupCount=0,
        encoding="utf-8", delay=True,
    )
    request_log_handler.suffix = "%Y-%m-%d"
    request_log_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    REQUEST_LOGGER.addHandler(request_log_handler)
    REQUEST_LOGGER.setLevel(logging.INFO)
    REQUEST_LOGGER.propagate = False
METHOD_FIXED_VARS = {"m", "v"}
METHOD_OUTPUT_UNITS = {"%", "ppm", "ppb", "mol/L", "g/L"}
INSTRUMENT_TYPES = {"xrf", "ppm", "ppb", "mol", "percent", "function", "ph"}
RESULT_DISPLAY_UNITS = ("%", "ppm", "ppb", "g/L", "mg/L", "ug/L")

# Database schema and initialization live in db_schema.py.

def database_target():
    target = app.config.get("LIMS_DATABASE_URL") or app.config.get("DATABASE_URL") or DB
    if not target:
        raise RuntimeError("Configure LIMS_DATABASE_URL before starting the server")
    return target


def get_db():
    if "db" not in g:
        g.db = connect_database(database_target())
    return g.db


def xrf_client_required(view):
    """Require a device token regardless of network origin."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = app.config.get("XRF_CLIENT_TOKEN", XRF_CLIENT_TOKEN)
        supplied = request.headers.get("X-Instrument-Token", "").strip()
        if not expected:
            return jsonify(ok=False, error="服务端尚未配置 LIMS_XRF_CLIENT_TOKEN"), 503
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            return jsonify(ok=False, error="仪器客户端令牌无效"), 401
        return view(*args, **kwargs)
    return wrapped


def standard_client_required(view):
    """Require a separate standard-instrument token, including during tests."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = app.config.get("STANDARD_CLIENT_TOKEN", STANDARD_CLIENT_TOKEN)
        supplied = request.headers.get("X-Instrument-Token", "").strip()
        if not expected:
            return jsonify(ok=False, error="服务端尚未配置 LIMS_STANDARD_CLIENT_TOKEN"), 503
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            return jsonify(ok=False, error="标准仪器客户端令牌无效"), 401
        return view(*args, **kwargs)
    return wrapped


@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


app.extensions["lims_get_db"] = get_db
init_security(app)
app.register_blueprint(auth_bp)


@app.before_request
def start_request_timer():
    g.request_started_at = time.perf_counter()


app.before_request(load_user)
app.before_request(login_required_before_request)
app.after_request(extend_write_authorization)


@app.after_request
def disable_api_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.after_request
def invalidate_report_payload_cache(response):
    # XRF 客户端的每 5 秒心跳/同步也走 POST，但不会改已关联样品的报告数据；
    # 导入端点在真正重写关联样品数据时会自行调用 _report_cache_note_write。
    if request.method not in {"GET", "HEAD", "OPTIONS"} \
            and not request.path.startswith("/api/instrument/xrf/"):
        _report_cache_note_write()
    return response


COMPRESSIBLE_TYPES = {"application/json", "text/html", "text/css",
                      "application/javascript", "text/javascript",
                      "application/manifest+json", "image/svg+xml",
                      "text/csv", "text/plain"}
COMPRESS_MIN_BYTES = 1024


@app.after_request
def compress_response(response):
    ctype = (response.content_type or "").split(";")[0].strip().lower()
    if ctype == "text/event-stream" or response.headers.get("Content-Encoding"):
        return response
    if response.status_code != 200 or ctype not in COMPRESSIBLE_TYPES:
        return response
    if "gzip" not in (request.headers.get("Accept-Encoding", "") or "").lower():
        return response
    if response.direct_passthrough:
        try:
            response.direct_passthrough = False
        except Exception:
            return response
    data = response.get_data()
    if len(data) < COMPRESS_MIN_BYTES:
        return response
    response.set_data(gzip.compress(data, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    response.headers.add("Vary", "Accept-Encoding")
    return response


@app.after_request
def static_cache_headers(response):
    if response.status_code == 200 and request.path.startswith("/static/"):
        if request.args.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.after_request
def log_request(response):
    if not REQUEST_LOG_ENABLED:
        return response
    elapsed_ms = (time.perf_counter() - getattr(g, "request_started_at", time.perf_counter())) * 1000
    user = getattr(g, "user", None)
    terminal = getattr(g, "terminal", None)
    user_name = (user["display_name"] or user["username"]) if user else "-"
    terminal_name = terminal["name"] if terminal else "-"
    safe_path = request.path.replace("\r", "").replace("\n", "")
    REQUEST_LOGGER.info(
        "ip=%s method=%s path=%s status=%d duration_ms=%.1f user=%s terminal=%s",
        request.remote_addr or "-", request.method, safe_path, response.status_code,
        elapsed_ms, user_name, terminal_name,
    )
    return response


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_):
    return jsonify(ok=False, error="上传文件超过 20 MB 限制"), 413


@app.errorhandler(404)
def route_not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="请求的接口不存在", code="api_not_found"), 404
    return error


def init_db():
    initialize_database(database_target())


# ---------------------------------------------------------------- 工具

def rows(q, args=()):
    return [dict(r) for r in get_db().execute(q, args)]


def optional_density(data):
    value = data.get("density_g_ml")
    if value in (None, ""):
        return None
    try:
        density = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("液体密度必须是数字") from exc
    if not math.isfinite(density) or density <= 0:
        raise ValueError("液体密度必须大于 0")
    return density


def clean_sample_tags(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("每个样品最多添加 20 个标签")
    tags = []
    seen = set()
    for raw in value:
        tag = str(raw or "").strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > 30 or any(ord(char) < 32 for char in tag):
            raise ValueError("标签不能为空且不能超过 30 个字符")
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


def replace_sample_tags(db, sample_id, value):
    tags = clean_sample_tags(value)
    db.execute("DELETE FROM sample_tags WHERE sample_id=%s", (sample_id,))
    db.executemany("INSERT INTO sample_tags(sample_id,tag) VALUES(%s,%s)",
                   [(sample_id, tag) for tag in tags])
    return tags


def attach_sample_tags(db, samples):
    if not samples:
        return samples
    ids = [sample["id"] for sample in samples]
    grouped = {sample_id: [] for sample_id in ids}
    for row in db.execute(f"""SELECT sample_id,tag FROM sample_tags
            WHERE sample_id IN ({','.join('%s' for _ in ids)}) ORDER BY tag""", ids):
        grouped[row["sample_id"]].append(row["tag"])
    for sample in samples:
        sample["tags"] = grouped.get(sample["id"], [])
    return samples


def actor_name(actor=None):
    actor = actor if actor is not None else getattr(g, "user", None)
    try:
        name = actor.get("display_name") or actor.get("username")
    except AttributeError:
        name = actor["display_name"] or actor["username"] if actor else None
    return str(name or "系统")


def mark_sample_status_actor(db, sample_id, action, actor=None):
    db.execute("""UPDATE samples SET status_operator=%s,status_action=%s,
        status_changed_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS') WHERE id=%s""",
        (actor_name(actor), action, sample_id))


def current_actor_name():
    return actor_name()


_SPECIAL_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                   ast.Div: operator.truediv, ast.Pow: operator.pow}
_SPECIAL_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def special_formula_value(expression, values):
    """只允许数字、字段名和基本四则运算的专项计算公式。"""
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
    """Validate a numeric formula and return identifiers in source order."""
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
        elif isinstance(node, ast.Name) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", node.id):
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


def calculate_special(schema, raw):
    values = {key: value for key, value in raw.items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)}
    calculated = {}
    for group in schema.get("groups", []):
        pending = [field for field in group.get("fields", []) if field.get("formula")]
        for _ in range(len(pending) + 1):
            changed = False
            for field in list(pending):
                try:
                    value = special_formula_value(field["formula"], {**values, **calculated})
                    if value != value or abs(value) == float("inf"):
                        continue
                    calculated[field["key"]] = round(value, int(field.get("decimals", 4)))
                    pending.remove(field)
                    changed = True
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    continue
            if not changed:
                break
    required = [field["key"] for group in schema.get("groups", [])
                for field in group.get("fields", []) if field.get("required")]
    complete = bool(required) and all(raw.get(key) not in (None, "") for key in required)
    return calculated, complete


def aux_coefficient(aux):
    """Return the correction coefficient from the reference measurement."""
    if not aux.get("use"):
        return 1.0
    if aux.get("expected") and aux.get("measured"):
        return float(aux["expected"]) / float(aux["measured"])
    return 1.0


def reading_value(sa, is_liquid, raw, extra):
    """单个读数换算。返回 (数值, 单位) 或 (None, 说明)。"""
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
        except Exception as e:
            return (None, f"公式错误: {e}")
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
    """Convert display units without changing the stored analytical value."""
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
    """任务级结果: 只聚合勾选参与的读数，再乘回标系数。
    返回 (数值, 单位/说明, 读数明细列表)。"""
    aux = json.loads(sa.get("aux") or "{}")
    coeff = aux_coefficient(aux)
    readings = sa.get("readings") or []
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
        # 没有有效读数时, 取第一条的说明作为提示
        return (None, details[0]["unit"], details)
    avg = sum(d["value"] for d in chosen) / len(chosen)
    return (round(avg * coeff, 4), chosen[0]["unit"], details)


def task_defaults(db, instrument_map, analyte_id):
    """返回模板为某项目配置的有效 (instrument_id, method_id)。"""
    config = (instrument_map or {}).get(str(analyte_id))
    if not config:
        return None, None
    instrument_id = config.get("instrument_id")
    if not instrument_id:
        return None, None
    instrument = db.execute(
        """SELECT i.id,i.itype FROM instruments i
           JOIN instr_analytes ia ON ia.instrument_id=i.id
           WHERE i.id=%s AND ia.analyte_id=%s""", (instrument_id, analyte_id)).fetchone()
    if not instrument:
        return None, None
    method_id = config.get("method_id") if instrument["itype"] in {"function", "xrf"} else None
    if method_id and not db.execute(
            "SELECT 1 FROM methods WHERE id=%s AND itype=%s AND active=1",
            (method_id, instrument["itype"])).fetchone():
        method_id = None
    return instrument_id, method_id


def preparation_dilution_values(db, prep):
    """Validate a dilution chain and return its compatible storage values."""
    dilution_ids = prep.get("dilution_ids")
    if dilution_ids is None:
        dilution_ids = prep.get("dilution_steps")
        if isinstance(dilution_ids, str):
            try:
                dilution_ids = json.loads(dilution_ids or "[]")
            except json.JSONDecodeError:
                dilution_ids = None
    if dilution_ids is None:
        dilution_ids = [prep.get("dilution_id")] if prep.get("dilution_id") is not None else []
    if not isinstance(dilution_ids, list) or len(dilution_ids) > 8:
        raise ValueError("每路溶样最多支持 8 级稀释")
    try:
        dilution_ids = [int(value) for value in dilution_ids if value not in (None, "")]
    except (TypeError, ValueError):
        raise ValueError("稀释序列格式无效") from None
    labels, factor = [], 1.0
    for dilution_id in dilution_ids:
        dilution = db.execute("SELECT label,factor FROM dilutions WHERE id=%s", (dilution_id,)).fetchone()
        if not dilution:
            raise ValueError("稀释序列中包含不存在的稀释方式")
        labels.append(dilution["label"])
        factor *= float(dilution["factor"])
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("稀释总倍数无效")
    return (dilution_ids[0] if dilution_ids else None, json.dumps(dilution_ids),
            factor, " × ".join(labels))


def preparation_values(db, prep):
    return (prep["name"], prep.get("mass_g"), prep.get("volume_ml"),
            *preparation_dilution_values(db, prep))


def sample_audit_snapshot(db, sample_id):
    """审计用完整样品快照：主表、溶样及检测任务均纳入前后比较。"""
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sample_id,)).fetchone()
    if not sample:
        return None
    preparations = db.execute("""SELECT id,name,mass_g,volume_ml,dilution_id,
            dilution_steps,dilution_factor,dilution_label
        FROM preparations WHERE sample_id=%s ORDER BY id""", (sample_id,)).fetchall()
    tasks = db.execute("""SELECT sa.id,p.name AS preparation,a.name AS analyte,
            i.name AS instrument,m.name AS method,sa.status,sa.selection
        FROM sample_analytes sa
        LEFT JOIN preparations p ON p.id=sa.preparation_id
        JOIN analytes a ON a.id=sa.analyte_id
        LEFT JOIN instruments i ON i.id=sa.instrument_id
        LEFT JOIN methods m ON m.id=sa.method_id
        WHERE sa.sample_id=%s ORDER BY sa.id""", (sample_id,)).fetchall()
    special = db.execute("""SELECT sr.method_id,sm.name AS method,sr.raw_data,
        sr.calculated_data,sr.status FROM special_results sr
        JOIN special_methods sm ON sm.id=sr.method_id WHERE sr.sample_id=%s""",
        (sample_id,)).fetchone()
    return {
        "sample": dict(sample),
        "tags": [row["tag"] for row in db.execute(
            "SELECT tag FROM sample_tags WHERE sample_id=%s ORDER BY tag", (sample_id,))],
        "preparations": {str(row["id"]): {key: row[key] for key in row.keys() if key != "id"}
                         for row in preparations},
        "tasks": {str(row["id"]): {key: row[key] for key in row.keys() if key != "id"}
                         for row in tasks},
        "special_result": dict(special) if special else None,
    }


def attach_sample_status_history(db, samples):
    """Attach every manually recorded lifecycle action and its operator."""
    if not samples:
        return samples
    sample_ids = [int(sample["id"]) for sample in samples]
    placeholders = ",".join("%s" for _ in sample_ids)
    records = db.execute(f"""SELECT al.entity_id,al.action,al.before_json,al.after_json,al.reason,al.created_at,
            COALESCE(NULLIF(u.display_name,''),NULLIF(al.terminal_name,''),al.username,'系统') AS operator
        FROM audit_logs al LEFT JOIN users u ON u.id=al.user_id
        WHERE al.entity_type='sample' AND CAST(al.entity_id AS INTEGER) IN ({placeholders})
          AND al.action IN ('create','excel_plan_create','status_change','cancel')
        ORDER BY al.id""", sample_ids).fetchall()
    histories = {sample_id: [] for sample_id in sample_ids}
    status_order = {status: index for index, status in enumerate(
        ("received", "queued", "measuring", "partially_done", "completed", "reviewed"))}
    for record in records:
        try:
            payload = json.loads(record["after_json"] or "{}")
            before_payload = json.loads(record["before_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        status = (payload.get("sample") or payload).get("status")
        before_status = (before_payload.get("sample") or before_payload).get("status")
        if status not in SAMPLE_STATUS_LABELS:
            continue
        entity_history = histories.setdefault(int(record["entity_id"]), [])
        entity_history.append({
            "action": status,
            "operator": record["operator"],
            "at": record["created_at"],
            "reason": record["reason"] or "",
            "rollback": (record["action"] == "status_change" and
                         status_order.get(status, -1) < status_order.get(before_status, -1)),
        })
    for sample in samples:
        history = histories.get(int(sample["id"]), [])
        if (history and sample.get("status_action") == history[-1]["action"] and
                sample.get("status_operator")):
            history[-1]["operator"] = sample["status_operator"]
            history[-1]["at"] = sample.get("status_changed_at") or history[-1]["at"]
        elif not history and sample.get("status_operator"):
            history.append({"action": sample.get("status_action") or sample.get("status"),
                            "operator": sample["status_operator"],
                            "at": sample.get("status_changed_at"), "reason": ""})
        sample["status_history"] = history
    return samples


# ---------------------------------------------------------------- 页面

@app.route("/")
def index():
    built = FRONTEND_DIST / "index.html"
    response = app.make_response(send_file(built))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/frontend/<path:filename>")
def frontend_assets(filename):
    response = send_from_directory(FRONTEND_DIST, filename)
    # 资产文件名带内容哈希，可以长缓存；manifest 与 index.html 除外。
    if filename.startswith("assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.route("/health")
def health():
    try:
        get_db().execute("SELECT 1").fetchone()
        return jsonify(ok=True, database="ok")
    except DATABASE_ERRORS:
        return jsonify(ok=False, database="error"), 503


@app.route("/api/site-status")
def site_status():
    """供服务器时钟及右键对象历史读取；未指定对象时不返回审计记录。"""
    db = get_db()
    entity_type = request.args.get("entity_type", "").strip()
    entity_id = request.args.get("entity_id", "").strip()
    allowed_types = {"sample", "sample_analyte", "reading", "xrf_value",
                      "analyte", "instrument", "dilution", "method", "template",
                      "user", "terminal", "report_profile", "volume_preset",
                      "preparation_combination", "result_order_template"}
    candidates = []
    columns = """SELECT al.id,al.username,al.terminal_id,al.terminal_name,
            COALESCE(NULLIF(u.display_name,''),al.username) AS display_name,
            al.action,al.entity_type,al.entity_id,al.before_json,al.after_json,
            al.reason,al.created_at
        FROM audit_logs al LEFT JOIN users u ON u.id=al.user_id"""
    if entity_type == "sample" and entity_id.isdigit():
        candidates = db.execute(columns + """
            WHERE (al.entity_type='sample' AND al.entity_id=%s)
               OR (al.entity_type='sample_analyte' AND CASE WHEN al.entity_id ~ '^[0-9]+$' THEN al.entity_id::INTEGER END IN
                   (SELECT id FROM sample_analytes WHERE sample_id=%s))
               OR (al.entity_type='reading' AND CASE WHEN al.entity_id ~ '^[0-9]+$' THEN al.entity_id::INTEGER END IN
                   (SELECT r.id FROM readings r JOIN sample_analytes sa
                    ON sa.id=r.sample_analyte_id WHERE sa.sample_id=%s))
               OR (al.entity_type='xrf_value' AND CASE WHEN al.entity_id ~ '^[0-9]+$' THEN al.entity_id::INTEGER END IN
                   (SELECT xv.id FROM xrf_values xv JOIN xrf_analyses xa
                    ON xa.id=xv.analysis_id WHERE xa.sample_id=%s))
            ORDER BY al.id DESC LIMIT 200""", (entity_id, entity_id, entity_id, entity_id)).fetchall()
    elif entity_type in allowed_types and entity_id:
        candidates = db.execute(columns + """
            WHERE al.entity_type=%s AND al.entity_id=%s
            ORDER BY al.id DESC LIMIT 200""", (entity_type, entity_id)).fetchall()
    latest_change = None
    for candidate in candidates:
        changes = audit_changes(candidate["before_json"], candidate["after_json"])
        if not changes:
            continue
        latest_change = dict(candidate)
        latest_change["changes"] = changes
        break
    revision = db.execute("SELECT COALESCE(MAX(id),0) FROM audit_logs").fetchone()[0]
    return jsonify({
        "ok": True,
        "server_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "revision": revision,
        "latest_change": latest_change,
    })


SSE_POLL_SECONDS = 1.0
SSE_HEARTBEAT_TICKS = 15


@app.route("/api/events")
def sse_events():
    """SSE 推送：audit_logs 最大 id 变化（即服务器 revision 变化）时通知浏览器刷新。"""
    def generate():
        connection = connect_database(database_target())
        # 只读单语句轮询，必须 autocommit：否则连接终身 idle in transaction，
        # 长期持有旧快照，阻止 VACUUM 回收 audit_logs 死元组。
        connection.autocommit = True
        last_revision = None
        idle_ticks = 0
        try:
            while True:
                try:
                    row = connection.execute(
                        "SELECT COALESCE(MAX(id),0) FROM audit_logs").fetchone()
                    revision = int(row[0] if row else 0)
                except DATABASE_ERRORS:
                    break
                if last_revision is None or revision != last_revision:
                    payload = json.dumps({
                        "revision": revision,
                        "server_time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    })
                    yield f"data: {payload}\n\n"
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    if idle_ticks % SSE_HEARTBEAT_TICKS == 0:
                        yield ": ping\n\n"
                last_revision = revision
                time.sleep(SSE_POLL_SECONDS)
        finally:
            connection.close()
    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response


# ---------------------------------------------------------------- 元数据

@app.route("/api/meta")
def meta():
    instrs = rows("SELECT * FROM instruments ORDER BY sort_order,id")
    caps = rows("SELECT * FROM instr_analytes")
    for ins in instrs:
        ins["analytes"] = [c["analyte_id"] for c in caps if c["instrument_id"] == ins["id"]]
    special_methods = rows("SELECT * FROM special_methods WHERE active=1 ORDER BY sort_order,id")
    for method in special_methods:
        method["schema"] = json.loads(method.pop("schema_json") or "{}")
    terminal = dict(g.terminal) if getattr(g, "terminal", None) else None
    actual_user = dict(g.user) if g.user else None
    if actual_user:
        actual_user["permissions"] = sorted(user_permissions(g.user))
    if actual_user and terminal and terminal["kind"] == "standard":
        actual_user["is_authorized"] = True
    current_user = actual_user or ({
        "id": None, "username": f"terminal:{terminal['name']}",
        "display_name": terminal["name"], "permissions": sorted(CAPABILITIES), "virtual": True,
    } if terminal else None)
    combinations = rows("SELECT * FROM preparation_combinations ORDER BY name,id")
    for combination in combinations:
        combination["rows"] = json.loads(combination.pop("config_json") or "[]")
    result_order_templates = rows(
        "SELECT * FROM result_order_templates ORDER BY is_default DESC,name,id")
    for template in result_order_templates:
        template["items"] = json.loads(template.pop("items_json") or "[]")
    return jsonify({
        "analytes": rows("SELECT * FROM analytes ORDER BY sort_order,id"),
        "instruments": instrs,
        "dilutions": rows("SELECT * FROM dilutions ORDER BY active DESC,factor,id"),
        "volume_presets": rows("SELECT * FROM volume_presets ORDER BY active DESC,volume_ml,id"),
        "default_volume_ml": 250,
        "methods": rows("SELECT * FROM methods ORDER BY sort_order,id"),
        "special_methods": special_methods,
        "templates": rows("SELECT * FROM templates ORDER BY id"),
        "preparation_combinations": combinations,
        "report_profiles": rows("SELECT * FROM report_profiles ORDER BY id"),
        "result_order_templates": result_order_templates,
        "default_order_template_id": next((item["id"] for item in result_order_templates
                                             if item.get("is_default")), None),
        "categories": [r["category"] for r in rows(
            "SELECT DISTINCT category FROM samples WHERE category != '' ORDER BY category")],
        "sample_tags": rows("""SELECT tag AS name,COUNT(*) AS count FROM sample_tags
            GROUP BY tag ORDER BY tag"""),
        "current_user": current_user,
        "terminal": terminal,
        "authorized_user": actual_user if terminal and terminal["kind"] == "standard" else None,
        "authorization_required": bool(terminal and terminal["kind"] == "standard" and not actual_user),
        "authorization_expires_in": 120,
        "capabilities": CAPABILITIES,
        "sample_statuses": SAMPLE_STATUS_LABELS,
        "sample_transitions": SAMPLE_TRANSITIONS,
        "allowed_status_targets": sorted(set().union(*(
            CAPABILITY_STATUS_TARGETS.get(permission, set())
            for permission in current_user.get("permissions", [])
        )) if current_user else set()),
    })


def clean_report_profile(data):
    fields = {
        "name": (80, True), "company_name_cn": (160, True),
        "company_name_en": (240, False), "raw_code": (80, False),
        "final_code": (80, False),
    }
    result = {}
    for field, (limit, required) in fields.items():
        value = str(data.get(field, "")).strip()
        if required and not value:
            raise ValueError("版式名称和公司中文名不能为空")
        if len(value) > limit:
            raise ValueError("报告版式内容过长")
        result[field] = value
    return result


def clean_result_order_template(data):
    name = str(data.get("name", "")).strip()
    items = data.get("items", [])
    if not name:
        raise ValueError("模板名称不能为空")
    if len(name) > 80 or not isinstance(items, list) or len(items) > 200:
        raise ValueError("元素顺序模板格式无效")
    clean, seen = [], set()
    for item in items:
        value = str(item).strip()
        key = value.casefold()
        if not value or len(value) > 120 or key in seen:
            continue
        seen.add(key)
        clean.append(value)
    if not clean:
        raise ValueError("请至少填写一个元素或结果项目")
    return {"name": name, "items": clean}


def _default_order_template_id(db):
    row = db.execute(
        "SELECT id FROM result_order_templates WHERE is_default=1 ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def _validated_order_template_id(db, value, use_default=True):
    if value in (None, ""):
        return _default_order_template_id(db) if use_default else None
    try:
        template_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("通用顺序模板无效") from exc
    if not db.execute("SELECT 1 FROM result_order_templates WHERE id=%s", (template_id,)).fetchone():
        raise ValueError("通用顺序模板不存在")
    return template_id


def _universal_order_key(db, template_id=None):
    """Return a stable name sorter: selected template, system default, then chemistry."""
    template_id = _validated_order_template_id(db, template_id)
    default_id = _default_order_template_id(db)
    ordered_names = []
    for current_id in dict.fromkeys(item for item in (template_id, default_id) if item):
        row = db.execute(
            "SELECT items_json FROM result_order_templates WHERE id=%s", (current_id,)).fetchone()
        try:
            items = json.loads(row["items_json"] or "[]") if row else []
        except (TypeError, json.JSONDecodeError):
            items = []
        ordered_names.extend(str(item).strip() for item in items if str(item).strip())
    positions = {}
    for name in ordered_names:
        positions.setdefault(name.casefold(), len(positions))
    element_numbers = {str(row["symbol"]).casefold(): row["atomic_number"] for row in db.execute(
        "SELECT atomic_number,symbol FROM chemical_elements")}
    oxide_numbers = {str(row["formula"]).casefold(): element_numbers.get(
        str(row["element_symbol"]).casefold(), 999999) for row in db.execute(
            "SELECT formula,element_symbol FROM common_oxides")}
    analyte_orders = {str(row["name"]).casefold(): row["sort_order"] for row in db.execute(
        "SELECT name,sort_order FROM analytes")}

    def key(name):
        text = str(name or "").strip()
        folded = text.casefold()
        if folded in positions:
            return (0, positions[folded], 0, "")
        if folded in element_numbers:
            return (1, element_numbers[folded], 0, folded)
        if folded in oxide_numbers:
            return (1, oxide_numbers[folded], 1, folded)
        return (2, analyte_orders.get(folded, 999999), 0, folded)

    return key


def _sample_analyte_order_key(db, sample):
    universal_key = _universal_order_key(db, sample.get("order_template_id"))
    try:
        manual = [int(item) for item in json.loads(sample.get("report_order") or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        manual = []
    manual_positions = {item: index for index, item in enumerate(manual)}

    def key(item):
        analyte_id = item.get("analyte_id")
        if analyte_id in manual_positions:
            return (0, manual_positions[analyte_id], (0, 0, 0, ""))
        return (1, 0, universal_key(item.get("analyte") or item.get("name")))

    return key


@app.post("/api/result-order-templates")
@capability_required("settings_manage")
def add_result_order_template():
    try:
        template = clean_result_order_template(request.json or {})
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    db = get_db()
    try:
        template_id = db.execute("""INSERT INTO result_order_templates(name,items_json,is_default)
            VALUES(%s,%s,0) RETURNING id""",
            (template["name"], json.dumps(template["items"], ensure_ascii=False))).fetchone()["id"]
    except INTEGRITY_ERRORS:
        return jsonify(ok=False, error="模板名称已存在"), 409
    audit_event(db, "create", "result_order_template", template_id, after=template)
    db.commit()
    return jsonify(ok=True, id=template_id)


@app.put("/api/result-order-templates/<int:template_id>")
@capability_required("settings_manage")
def update_result_order_template(template_id):
    try:
        template = clean_result_order_template(request.json or {})
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    db = get_db()
    before = db.execute("SELECT * FROM result_order_templates WHERE id=%s", (template_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="模板不存在"), 404
    try:
        db.execute("UPDATE result_order_templates SET name=%s,items_json=%s WHERE id=%s",
                   (template["name"], json.dumps(template["items"], ensure_ascii=False), template_id))
    except INTEGRITY_ERRORS:
        return jsonify(ok=False, error="模板名称已存在"), 409
    if (request.json or {}).get("is_default"):
        db.execute("UPDATE result_order_templates SET is_default=0 WHERE id!=%s", (template_id,))
        db.execute("UPDATE result_order_templates SET is_default=1 WHERE id=%s", (template_id,))
        template["is_default"] = True
    audit_event(db, "update", "result_order_template", template_id, before=before, after=template)
    db.commit()
    return jsonify(ok=True, id=template_id)


@app.delete("/api/result-order-templates/<int:template_id>")
@capability_required("settings_manage")
def delete_result_order_template(template_id):
    db = get_db()
    before = db.execute("SELECT * FROM result_order_templates WHERE id=%s", (template_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="模板不存在"), 404
    if before["is_default"]:
        return jsonify(ok=False, error="系统默认顺序模板不能删除，请先将其他模板设为默认"), 409
    db.execute("UPDATE samples SET order_template_id=NULL WHERE order_template_id=%s", (template_id,))
    db.execute("UPDATE templates SET order_template_id=NULL WHERE order_template_id=%s", (template_id,))
    db.execute("DELETE FROM result_order_templates WHERE id=%s", (template_id,))
    audit_event(db, "delete", "result_order_template", template_id, before=before)
    db.commit()
    return jsonify(ok=True)


@app.post("/api/report-profiles")
@capability_required("settings_manage")
def add_report_profile():
    try:
        profile = clean_report_profile(request.json or {})
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    db = get_db()
    try:
        profile_id = db.execute("""INSERT INTO report_profiles(
            name,company_name_cn,company_name_en,raw_code,final_code)
            VALUES(%s,%s,%s,%s,%s) RETURNING id""",
            tuple(profile[field] for field in ("name", "company_name_cn", "company_name_en", "raw_code", "final_code"))).fetchone()["id"]
    except INTEGRITY_ERRORS:
        return jsonify(ok=False, error="报告版式名称已存在"), 409
    audit_event(db, "create", "report_profile", profile_id, after=profile)
    db.commit()
    return jsonify(ok=True, id=profile_id)


@app.put("/api/report-profiles/<int:profile_id>")
@capability_required("settings_manage")
def update_report_profile(profile_id):
    db = get_db()
    before = db.execute("SELECT * FROM report_profiles WHERE id=%s", (profile_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="报告版式不存在"), 404
    merged = {key: (request.json or {}).get(key, before[key]) for key in before.keys()}
    try:
        profile = clean_report_profile(merged)
        db.execute("""UPDATE report_profiles SET name=%s,company_name_cn=%s,company_name_en=%s,
            raw_code=%s,final_code=%s WHERE id=%s""", tuple(profile[field] for field in (
                "name", "company_name_cn", "company_name_en", "raw_code", "final_code")) + (profile_id,))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except INTEGRITY_ERRORS:
        return jsonify(ok=False, error="报告版式名称已存在"), 409
    after = db.execute("SELECT * FROM report_profiles WHERE id=%s", (profile_id,)).fetchone()
    audit_event(db, "update", "report_profile", profile_id, before=before, after=after)
    db.commit()
    return jsonify(ok=True)


@app.delete("/api/report-profiles/<int:profile_id>")
@capability_required("settings_manage")
def delete_report_profile(profile_id):
    db = get_db()
    before = db.execute("SELECT * FROM report_profiles WHERE id=%s", (profile_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="报告版式不存在"), 404
    if db.execute("SELECT COUNT(*) FROM report_profiles").fetchone()[0] <= 1:
        return jsonify(ok=False, error="至少保留一套报告版式"), 409
    db.execute("UPDATE samples SET report_profile_id=NULL WHERE report_profile_id=%s", (profile_id,))
    db.execute("DELETE FROM report_profiles WHERE id=%s", (profile_id,))
    audit_event(db, "delete", "report_profile", profile_id, before=before)
    db.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- 业务 Excel

def uploaded_xlsx():
    file = request.files.get("file")
    if not file or not file.filename:
        raise BusinessExcelError("请选择要上传的 .xlsx 文件")
    if not file.filename.lower().endswith(".xlsx"):
        raise BusinessExcelError("只支持 .xlsx 格式的业务工作簿")
    return file


def excel_error(exc, status=400):
    return jsonify(ok=False, error=str(exc)), status


@app.route("/api/excel/samples-overview")
def excel_samples_overview():
    try:
        output, _ = build_overview(get_db(), request.args.get("date_from"), request.args.get("date_to"),
                                   request.args.get("type", ""), request.args.get("q", "").strip(),
                                   request.args.get("include_cancelled") == "1")
        name = f"样品总览-{request.args.get('date_from')}-{request.args.get('date_to')}.xlsx"
        return send_file(output, as_attachment=True, download_name=name, mimetype=EXCEL_MIME)
    except BusinessExcelError as exc:
        return excel_error(exc)


@app.route("/api/excel/samples/<int:sid>/detail")
def excel_sample_plan(sid):
    try:
        output, sample = build_plan(get_db(), sid)
        return send_file(output, as_attachment=True,
                         download_name=f"样品方案-{sample['lims_no'] or sid}.xlsx", mimetype=EXCEL_MIME)
    except BusinessExcelError as exc:
        return excel_error(exc, 404 if str(exc) == "样品不存在" else 400)


def _validate_xrf_method(db, data):
    method_id = data.get("xrf_method_id") if data.get("xrf") else None
    if method_id in (None, ""):
        if data.get("xrf"):
            raise BusinessExcelError("启用XRF时必须填写有效的XRF方法ID")
        return None
    try:
        method_id = int(method_id)
    except (TypeError, ValueError) as exc:
        raise BusinessExcelError("XRF方法ID必须是整数") from exc
    if not db.execute("SELECT 1 FROM methods WHERE id=%s AND itype='xrf'", (method_id,)).fetchone():
        raise BusinessExcelError("XRF方法ID不存在或不是XRF方法")
    return method_id


def apply_excel_plan(db, data, sid=None):
    """Apply a parsed plan. Existing stable preparation/task IDs retain their results."""
    creating = sid is None
    existing = None if creating else db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not creating:
        if not existing:
            raise BusinessExcelError("样品不存在")
        if existing["status"] in {"reviewed", "cancelled"}:
            raise BusinessExcelError("已审核、已出报告或已作废的样品不能覆盖方案")
        if data.get("id") != sid or str(data.get("lims_no") or "") != str(existing["lims_no"] or ""):
            raise BusinessExcelError("工作簿样品身份与当前样品不一致")
        if str(data.get("updated_at") or "") != str(existing["updated_at"] or ""):
            raise BusinessExcelError("样品已被他人更新，请重新导出后再上传")
        if existing["workflow_type"] != data["workflow_type"]:
            raise BusinessExcelError("常规样和专项样不能相互转换，请新建样品")
    workflow = data["workflow_type"]
    if creating:
        lims_no = next_lims_no(db)
        is_water_quality = int(bool(data.get("is_water_quality", 0))) if workflow == "regular" else 0
        is_liquid = int(bool(data["is_liquid"]) or is_water_quality) if workflow == "regular" else 0
        sid = db.execute("""INSERT INTO samples(name,category,is_liquid,is_water_quality,workflow_type,special_method_id,xrf,
            xrf_method_id,xrf_report_items,customer,report_no,analysis_date,analyst,reviewer,report_order,lims_no,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'received') RETURNING id""",
            (data["name"], str(data.get("category") or "").strip(), is_liquid, is_water_quality, workflow,
             data.get("special_method_id") if workflow == "special" else None, int(data.get("xrf", 0)) if workflow == "regular" else 0,
             _validate_xrf_method(db, data) if workflow == "regular" else None, str(data.get("xrf_report_items") or "").strip(),
             str(data.get("customer") or "").strip(), str(data.get("report_no") or "").strip(),
             str(data.get("analysis_date") or "").strip(), str(data.get("analyst") or "").strip(),
             str(data.get("reviewer") or "").strip(), json.dumps(data.get("report_order") or []), lims_no)).fetchone()["id"]
        mark_sample_status_actor(db, sid, "received")
    else:
        lims_no = existing["lims_no"]
        before = sample_audit_snapshot(db, sid)
        is_water_quality = int(bool(data.get("is_water_quality", 0))) if workflow == "regular" else 0
        is_liquid = int(bool(data["is_liquid"]) or is_water_quality) if workflow == "regular" else 0
        db.execute("""UPDATE samples SET name=%s,category=%s,is_liquid=%s,is_water_quality=%s,special_method_id=%s,xrf=%s,xrf_method_id=%s,
            xrf_report_items=%s,customer=%s,report_no=%s,analysis_date=%s,analyst=%s,reviewer=%s,report_order=%s,
            updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
            (data["name"], str(data.get("category") or "").strip(), is_liquid, is_water_quality,
             data.get("special_method_id") if workflow == "special" else None,
             int(data.get("xrf", 0)) if workflow == "regular" else 0,
             _validate_xrf_method(db, data) if workflow == "regular" else None,
             str(data.get("xrf_report_items") or "").strip(), str(data.get("customer") or "").strip(),
             str(data.get("report_no") or "").strip(), str(data.get("analysis_date") or "").strip(),
             str(data.get("analyst") or "").strip(), str(data.get("reviewer") or "").strip(),
             json.dumps(data.get("report_order") or []), sid))
    if workflow == "special":
        method_id = data["special_method_id"]
        current = db.execute("SELECT * FROM special_results WHERE sample_id=%s", (sid,)).fetchone()
        if current and current["method_id"] != method_id and json.loads(current["raw_data"] or "{}"):
            raise BusinessExcelError("已有专项数据，不能更换专项方法")
        db.execute("""INSERT INTO special_results(sample_id,method_id) VALUES(%s,%s)
            ON CONFLICT(sample_id) DO UPDATE SET method_id=excluded.method_id""", (sid, method_id))
    else:
        existing_preps = {row["id"]: row for row in db.execute("SELECT * FROM preparations WHERE sample_id=%s", (sid,))}
        prep_map, kept_preps = {}, set()
        for prep in data["preps"]:
            try:
                values = preparation_values(db, prep)
            except ValueError as exc:
                raise BusinessExcelError(str(exc)) from exc
            exported_id = prep.get("id")
            if not creating and exported_id in existing_preps:
                pid = exported_id
                db.execute("""UPDATE preparations SET name=%s,mass_g=%s,volume_ml=%s,dilution_id=%s,
                    dilution_steps=%s,dilution_factor=%s,dilution_label=%s WHERE id=%s""", values + (pid,))
            else:
                pid = db.execute("""INSERT INTO preparations(sample_id,name,mass_g,volume_ml,dilution_id,
                    dilution_steps,dilution_factor,dilution_label)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (sid,) + values).fetchone()["id"]
            prep_map[exported_id] = pid
            prep_map[("name", prep["name"])] = pid
            kept_preps.add(pid)
        existing_tasks = {row["id"]: row for row in db.execute("""SELECT sa.*,i.itype FROM sample_analytes sa
            LEFT JOIN instruments i ON i.id=sa.instrument_id WHERE sa.sample_id=%s""", (sid,))}
        kept_tasks = set()
        wanted_tasks = set()
        for task in data["tasks"]:
            prep_name = str(task["prep_name"] or "").strip()
            direct_prep = task["preparation_id"] is None and prep_name in {"", "原样"}
            if task["preparation_id"] is not None:
                pid = prep_map.get(task["preparation_id"])
            elif direct_prep:
                pid = None
            else:
                pid = prep_map.get(("name", prep_name))
            if pid is None and not direct_prep:
                raise BusinessExcelError(f"检测任务引用了不存在的溶样：{task['prep_name'] or task['preparation_id']}")
            task_key = (pid, task["analyte_id"])
            if task_key in wanted_tasks:
                raise BusinessExcelError(f"同一溶样中分析项目重复：{task['prep_name']} / {task['analyte_id']}")
            wanted_tasks.add(task_key)
            old = existing_tasks.get(task.get("id")) if not creating else None
            new_instrument = (db.execute("SELECT itype FROM instruments WHERE id=%s", (task["instrument_id"],)).fetchone()
                              if task["instrument_id"] else None)
            new_itype = new_instrument["itype"] if new_instrument else None
            if (old and old["itype"] == "xrf") or new_itype == "xrf":
                changed = (not old or old["itype"] != "xrf" or new_itype != "xrf" or
                           old["preparation_id"] != pid or old["analyte_id"] != task["analyte_id"] or
                           (old["instrument_id"], old["method_id"], old["selection"]) !=
                           (task["instrument_id"], task["method_id"], task["selection"]))
                if changed:
                    raise BusinessExcelError("XRF仪器任务由仪器链路管理，不能通过Excel新增、删除或修改")
                task_id = old["id"]
            elif old and old["preparation_id"] == pid and old["analyte_id"] == task["analyte_id"]:
                task_id = old["id"]
                changed = (old["instrument_id"], old["method_id"]) != (task["instrument_id"], task["method_id"])
                db.execute("UPDATE sample_analytes SET instrument_id=%s,method_id=%s,selection=%s WHERE id=%s",
                           (task["instrument_id"], task["method_id"], task["selection"], task_id))
                if changed:
                    db.execute("DELETE FROM readings WHERE sample_analyte_id=%s", (task_id,))
                    db.execute("DELETE FROM results WHERE sample_analyte_id=%s", (task_id,))
                    db.execute("UPDATE sample_analytes SET status='pending' WHERE id=%s", (task_id,))
            else:
                task_id = db.execute("""INSERT INTO sample_analytes(
                    sample_id,preparation_id,analyte_id,instrument_id,method_id,selection)
                    VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (sid, pid, task["analyte_id"], task["instrument_id"], task["method_id"], task["selection"])).fetchone()["id"]
            kept_tasks.add(task_id)
        if not creating:
            removed = set(existing_tasks) - kept_tasks
            if any(existing_tasks[task_id]["itype"] == "xrf" for task_id in removed):
                raise BusinessExcelError("XRF仪器任务由仪器链路管理，不能通过Excel新增、删除或修改")
            for task_id in removed:
                db.execute("DELETE FROM sample_analytes WHERE id=%s", (task_id,))
            for pid in set(existing_preps) - kept_preps:
                db.execute("DELETE FROM preparations WHERE id=%s", (pid,))
        recompute_sample_progress(db, sid)
    action = "excel_plan_create" if creating else "excel_plan_overwrite"
    audit_event(db, action, "sample", sid, before=None if creating else before,
                after=sample_audit_snapshot(db, sid), reason="业务Excel方案上传")
    return sid, lims_no


def _import_plan(sid=None):
    db = get_db()
    try:
        data, _ = parse_plan(uploaded_xlsx().stream, db)
        db.execute("SAVEPOINT business_excel_plan")
        try:
            result_id, lims_no = apply_excel_plan(db, data, sid)
            db.execute("RELEASE business_excel_plan")
            db.commit()
        except Exception:
            db.execute("ROLLBACK TO business_excel_plan")
            db.execute("RELEASE business_excel_plan")
            raise
        return jsonify(ok=True, id=result_id, lims_no=lims_no,
                       message="样品已从Excel创建" if sid is None else "样品方案已从Excel覆盖")
    except BusinessExcelError as exc:
        db.rollback()
        conflict = any(word in str(exc) for word in ("已审核", "已出报告", "已作废", "已被他人", "身份", "不能相互转换", "已有专项数据"))
        return excel_error(exc, 409 if conflict else 400)
    except DATABASE_ERRORS:
        db.rollback()
        return excel_error(BusinessExcelError("导入失败，数据未改变"), 400)
    except Exception:
        db.rollback()
        raise


@app.route("/api/excel/samples/create", methods=["POST"])
@capability_required("sample_manage")
def excel_sample_create():
    return _import_plan()


@app.route("/api/excel/samples/<int:sid>/detail", methods=["POST"])
@capability_required("sample_manage")
def excel_sample_plan_overwrite(sid):
    return _import_plan(sid)


@app.route("/api/excel/samples/<int:sid>/data")
def excel_sample_data(sid):
    try:
        output, sample = build_data(get_db(), sid)
        return send_file(output, as_attachment=True,
                         download_name=f"样品数据-{sample['lims_no'] or sid}.xlsx", mimetype=EXCEL_MIME)
    except BusinessExcelError as exc:
        return excel_error(exc, 404 if str(exc) == "样品不存在" else 400)


@app.route("/api/excel/samples/<int:sid>/data", methods=["POST"])
@capability_required("result_edit")
def excel_sample_data_overwrite(sid):
    db = get_db()
    try:
        data, _ = parse_data(uploaded_xlsx().stream)
        sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
        if not sample:
            raise BusinessExcelError("样品不存在")
        identity = data["identity"]
        try:
            identity_id = int(identity["样品ID"])
        except (TypeError, ValueError):
            raise BusinessExcelError("工作簿样品ID无效")
        if identity_id != sid or str(identity["LIMS编号"] or "") != str(sample["lims_no"] or ""):
            raise BusinessExcelError("工作簿样品身份与当前样品不一致")
        if str(identity["更新标记"] or "") != str(sample["updated_at"] or ""):
            raise BusinessExcelError("样品已被他人更新，请重新导出后再上传")
        if sample["status"] in {"received", "queued", "reviewed", "cancelled"}:
            raise BusinessExcelError("当前样品状态不能覆盖检测数据")
        db.execute("SAVEPOINT business_excel_data")
        before = sample_audit_snapshot(db, sid)
        if sample["workflow_type"] == "special":
            result = db.execute("""SELECT sr.*,sm.schema_json FROM special_results sr JOIN special_methods sm ON sm.id=sr.method_id
                                   WHERE sr.sample_id=%s""", (sid,)).fetchone()
            if not result:
                raise BusinessExcelError("专项方法尚未建立")
            schema = json.loads(result["schema_json"] or "{}")
            allowed = {field["key"] for group in schema.get("groups", []) for field in group.get("fields", []) if not field.get("formula")}
            allowed.add("note")
            unknown = {key for key, value in data["special"].items()
                       if key not in allowed and value not in (None, "")}
            if unknown:
                raise BusinessExcelError("专项数据包含未知或只读计算字段：" + "、".join(sorted(unknown)))
            existing_raw = json.loads(result["raw_data"] or "{}")
            clean = dict(existing_raw)
            for key, value in data["special"].items():
                if key not in allowed:
                    continue
                if value in (None, ""):
                    clean.pop(key, None)
                    continue
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        clean.pop(key, None)
                        continue
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                clean[key] = value
            calculated, complete = calculate_special(schema, clean)
            status = "completed" if complete else ("in_progress" if clean else "pending")
            db.execute("""UPDATE special_results SET raw_data=%s,calculated_data=%s,status=%s,updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),updated_by=%s
                          WHERE sample_id=%s""", (json.dumps(clean, ensure_ascii=False), json.dumps(calculated, ensure_ascii=False),
                                                   status, g.user["id"], sid))
        else:
            grouped = {}
            for row in data["rows"]:
                task = db.execute("""SELECT sa.*,i.itype FROM sample_analytes sa
                    LEFT JOIN instruments i ON i.id=sa.instrument_id WHERE sa.id=%s AND sa.sample_id=%s""",
                    (row["task_id"], sid)).fetchone()
                if not task:
                    raise BusinessExcelError(f"任务ID {row['task_id']} 不属于当前样品")
                if task["itype"] == "xrf":
                    raise BusinessExcelError(f"任务ID {row['task_id']} 是仪器来源的XRF任务，不能通过Excel覆盖")
                grouped.setdefault(row["task_id"], []).append(row)
            for task_id, imported in grouped.items():
                for row in imported:
                    if row["reading_id"] and not db.execute("SELECT 1 FROM readings WHERE id=%s AND sample_analyte_id=%s",
                                                             (row["reading_id"], task_id)).fetchone():
                        raise BusinessExcelError(f"读数ID {row['reading_id']} 不属于任务 {task_id}")
                db.execute("DELETE FROM readings WHERE sample_analyte_id=%s", (task_id,))
                aux = imported[0]["aux"]
                selection = imported[0]["selection"]
                if any(row["aux"] != aux or row["selection"] != selection for row in imported):
                    raise BusinessExcelError(f"任务 {task_id} 各行的辅助校正或报告选择不一致")
                has_value = any(row["raw"] not in (None, "") or row["extra"] for row in imported)
                if has_value or aux:
                    db.execute("""INSERT INTO results(sample_analyte_id,aux) VALUES(%s,%s)
                        ON CONFLICT(sample_analyte_id) DO UPDATE SET aux=excluded.aux""",
                               (task_id, json.dumps(aux, ensure_ascii=False)))
                else:
                    db.execute("DELETE FROM results WHERE sample_analyte_id=%s", (task_id,))
                db.execute("UPDATE sample_analytes SET selection=%s WHERE id=%s", (selection, task_id))
                for row in imported:
                    if row["raw"] in (None, "") and not row["extra"]:
                        continue
                    db.execute("INSERT INTO readings(sample_analyte_id,raw,extra,use_avg,is_final) VALUES(%s,%s,%s,%s,%s)",
                               (task_id, row["raw"] if row["raw"] != "" else None,
                                json.dumps(row["extra"], ensure_ascii=False), row["use_avg"], row["is_final"]))
                recompute_task_progress(db, task_id)
        db.execute("UPDATE samples SET updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s", (sid,))
        recompute_sample_progress(db, sid)
        audit_event(db, "excel_data_overwrite", "sample", sid, before=before,
                    after=sample_audit_snapshot(db, sid), reason="业务Excel数据上传")
        db.execute("RELEASE business_excel_data")
        db.commit()
        return jsonify(ok=True, id=sid, lims_no=sample["lims_no"], message="检测数据已从Excel覆盖")
    except BusinessExcelError as exc:
        db.rollback()
        conflict = any(word in str(exc) for word in ("状态", "身份", "已被他人"))
        status = 404 if str(exc) == "样品不存在" else (409 if conflict else 400)
        return excel_error(exc, status)
    except DATABASE_ERRORS:
        db.rollback()
        return excel_error(BusinessExcelError("导入失败，数据未改变"), 400)
    except Exception:
        db.rollback()
        raise


@app.route("/api/analytes", methods=["POST"])
@capability_required("settings_manage")
def add_analyte():
    data = request.json or {}
    name = data["name"].strip()
    default_unit = normalized_result_unit(data.get("default_unit"))
    if default_unit and default_unit not in RESULT_DISPLAY_UNITS:
        return jsonify(ok=False, error="默认单位无效"), 400
    db = get_db()
    created = db.execute("""INSERT INTO analytes(name,sort_order,default_unit)
        VALUES(%s,COALESCE((SELECT MAX(sort_order)+1 FROM analytes),1),%s)
        ON CONFLICT(name) DO NOTHING RETURNING id""", (name, default_unit)).fetchone()
    if created:
        audit_event(db, "create", "analyte", created["id"],
                    after={"name": name, "default_unit": default_unit})
    db.commit()
    return jsonify(ok=True)


@app.route("/api/analytes/<int:aid>", methods=["PUT", "DELETE"])
@capability_required("settings_manage")
def del_analyte(aid):
    db = get_db()
    before = db.execute("SELECT * FROM analytes WHERE id=%s", (aid,)).fetchone()
    if request.method == "PUT":
        if not before:
            return jsonify(ok=False, error="分析项目不存在"), 404
        default_unit = normalized_result_unit((request.json or {}).get("default_unit"))
        if default_unit and default_unit not in RESULT_DISPLAY_UNITS:
            return jsonify(ok=False, error="默认单位无效"), 400
        db.execute("UPDATE analytes SET default_unit=%s WHERE id=%s", (default_unit, aid))
        after = db.execute("SELECT * FROM analytes WHERE id=%s", (aid,)).fetchone()
        audit_event(db, "update", "analyte", aid, before=before, after=after)
        db.commit()
        return jsonify(ok=True, default_unit=default_unit)
    db.execute("DELETE FROM analytes WHERE id=%s", (aid,))
    if before:
        audit_event(db, "delete", "analyte", aid, before=before)
    db.commit()
    return jsonify(ok=True)


@app.route("/api/instruments", methods=["POST"])
@capability_required("settings_manage")
def add_instrument():
    d = request.json or {}
    itype = str(d.get("itype", "")).strip().lower()
    if itype not in INSTRUMENT_TYPES:
        return jsonify(ok=False, error="仪器类型无效"), 400
    name = str(d.get("name", "")).strip()
    if not name:
        return jsonify(ok=False, error="仪器名称不能为空"), 400
    db = get_db()
    instrument_id = db.execute("""INSERT INTO instruments(name,itype,sort_order)
        VALUES(%s,%s,COALESCE((SELECT MAX(sort_order)+1 FROM instruments),1))
        RETURNING id""", (name, itype)).fetchone()["id"]
    audit_event(db, "create", "instrument", instrument_id,
                after={"name": name, "itype": itype})
    db.commit()
    return jsonify(ok=True)


@app.route("/api/instruments/<int:iid>", methods=["DELETE"])
@capability_required("settings_manage")
def del_instrument(iid):
    db = get_db()
    before = db.execute("SELECT * FROM instruments WHERE id=%s", (iid,)).fetchone()
    db.execute("DELETE FROM instruments WHERE id=%s", (iid,))
    if before:
        audit_event(db, "delete", "instrument", iid, before=before)
    db.commit()
    return jsonify(ok=True)


@app.route("/api/instruments/<int:iid>/capabilities", methods=["PUT"])
@capability_required("settings_manage")
def set_capabilities(iid):
    db = get_db()
    before_ids = [row[0] for row in db.execute(
        "SELECT analyte_id FROM instr_analytes WHERE instrument_id=%s ORDER BY analyte_id",
        (iid,))]
    existing_ids = {row[0] for row in db.execute("SELECT id FROM analytes")}
    ids = []
    for value in (request.json or {}).get("analyte_ids", []):
        try:
            analyte_id = int(value)
        except (TypeError, ValueError):
            continue
        if analyte_id in existing_ids and analyte_id not in ids:
            ids.append(analyte_id)
    db.execute("DELETE FROM instr_analytes WHERE instrument_id=%s", (iid,))
    db.executemany("INSERT INTO instr_analytes VALUES(%s,%s)", [(iid, a) for a in ids])
    after_ids = sorted(ids)
    audit_event(db, "capabilities", "instrument", iid,
                before={"analyte_ids": before_ids},
                after={"analyte_ids": after_ids})
    db.commit()
    return jsonify(ok=True)


def update_order(table, ids):
    db = get_db()
    before_rows = db.execute(
        f"SELECT id,sort_order FROM {table} ORDER BY sort_order,id").fetchall()
    existing = {row[0] for row in before_rows}
    before_order = {row[0]: row[1] for row in before_rows}
    ordered = []
    for item in ids:
        try:
            item_id = int(item)
        except (TypeError, ValueError):
            continue
        if item_id in existing and item_id not in ordered:
            ordered.append(item_id)
    ordered.extend(sorted(existing - set(ordered)))
    entity_type = {"instruments": "instrument", "analytes": "analyte",
                   "methods": "method"}[table]
    for position, item_id in enumerate(ordered, 1):
        db.execute(f"UPDATE {table} SET sort_order=%s WHERE id=%s", (position, item_id))
        audit_event(db, "reorder", entity_type, item_id,
                    before={"sort_order": before_order.get(item_id)},
                    after={"sort_order": position})
    db.commit()
    return ordered


@app.route("/api/instruments/order", methods=["PUT"])
@capability_required("settings_manage")
def reorder_instruments():
    return jsonify(ok=True, ids=update_order(
        "instruments", (request.json or {}).get("ids", [])))


@app.route("/api/analytes/order", methods=["PUT"])
@capability_required("settings_manage")
def reorder_analytes():
    return jsonify(ok=True, ids=update_order(
        "analytes", (request.json or {}).get("ids", [])))


@app.route("/api/methods/order", methods=["PUT"])
@capability_required("settings_manage")
def reorder_methods():
    return jsonify(ok=True, ids=update_order(
        "methods", (request.json or {}).get("ids", [])))


@app.route("/api/dilutions", methods=["POST"])
@capability_required("settings_manage")
def add_dilution():
    d = request.json or {}
    aliquot = d.get("aliquot_ml")
    final_volume = d.get("final_volume_ml")
    if aliquot is not None or final_volume is not None:
        try:
            aliquot = float(aliquot)
            final_volume = float(final_volume)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="移取体积和再次定容体积必须是数字"), 400
        if aliquot <= 0 or final_volume <= 0 or final_volume < aliquot:
            return jsonify(ok=False, error="体积必须大于 0，且再次定容体积不能小于移取体积"), 400
        def compact(value):
            return f"{value:g}"
        label = f"{compact(aliquot)}/{compact(final_volume)}"
        factor = final_volume / aliquot
    else:
        label = d.get("label", "").strip()
        try:
            factor = float(d.get("factor"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="稀释倍数必须是数字"), 400
        if not label or factor <= 0:
            return jsonify(ok=False, error="稀释标签和倍数不能为空"), 400
    db = get_db()
    existing = db.execute("SELECT id,active FROM dilutions WHERE label=%s", (label,)).fetchone()
    if existing:
        if existing["active"]:
            return jsonify(ok=False, error=f"稀释方式 {label} 已存在"), 409
        db.execute("UPDATE dilutions SET factor=%s,active=1 WHERE id=%s",
                   (factor, existing["id"]))
        audit_event(db, "restore", "dilution", existing["id"],
                    after={"label": label, "factor": factor, "active": 1})
        db.commit()
        return jsonify(ok=True, id=existing["id"], label=label, factor=factor, restored=True)
    dilution_id = db.execute("INSERT INTO dilutions(label,factor) VALUES(%s,%s) RETURNING id",
                             (label, factor)).fetchone()["id"]
    audit_event(db, "create", "dilution", dilution_id,
                after={"label": label, "factor": factor, "active": 1})
    db.commit()
    return jsonify(ok=True, label=label, factor=factor)


@app.route("/api/dilutions/<int:did>", methods=["DELETE"])
@capability_required("settings_manage")
def del_dilution(did):
    db = get_db()
    dilution = db.execute("SELECT * FROM dilutions WHERE id=%s", (did,)).fetchone()
    if not dilution:
        return jsonify(ok=False, error="稀释方式不存在"), 404
    prep_count = 0
    for prep in db.execute("SELECT dilution_id,dilution_steps FROM preparations").fetchall():
        try:
            steps = json.loads(prep["dilution_steps"] or "[]")
        except json.JSONDecodeError:
            steps = []
        if did in steps or (not steps and prep["dilution_id"] == did):
            prep_count += 1
    if not dilution["active"]:
        return jsonify(ok=True, hidden=True, historical_preparations=prep_count)
    if db.execute("SELECT COUNT(*) FROM dilutions WHERE active=1").fetchone()[0] <= 1:
        return jsonify(ok=False, error="至少需要保留一种可选稀释方式"), 400
    db.execute("UPDATE dilutions SET active=0 WHERE id=%s", (did,))
    audit_event(db, "disable", "dilution", did, before=dilution,
                after={"active": 0}, reason=f"保留 {prep_count} 条历史溶样引用")
    db.commit()
    return jsonify(ok=True, hidden=True, historical_preparations=prep_count)


def clean_preparation_combination(db, data):
    name = str(data.get("name", "")).strip()
    config = data.get("rows", [])
    if not name:
        raise ValueError("组合名称不能为空")
    if not isinstance(config, list) or not config:
        raise ValueError("组合至少需要一条溶样配置")
    if len(config) > 20:
        raise ValueError("一个组合最多包含 20 条溶样配置")
    cleaned = []
    for row in config:
        if not isinstance(row, dict):
            raise ValueError("溶样组合格式无效")
        try:
            mass = None if row.get("mass_g") in (None, "") else float(row["mass_g"])
            volume = None if row.get("volume_ml") in (None, "") else float(row["volume_ml"])
        except (TypeError, ValueError):
            raise ValueError("称样量和定容体积必须是数字") from None
        if mass is not None and (not math.isfinite(mass) or mass <= 0):
            raise ValueError("称样量必须大于 0")
        if volume is not None and (not math.isfinite(volume) or volume <= 0):
            raise ValueError("定容体积必须大于 0")
        dilution_id, dilution_steps, _, _ = preparation_dilution_values(db, row)
        cleaned.append({
            "name": str(row.get("name", "")).strip(),
            "mass_g": mass,
            "volume_ml": volume,
            "dilution_id": dilution_id,
            "dilution_ids": json.loads(dilution_steps),
        })
    return name, cleaned


@app.post("/api/preparation-combinations")
@capability_required("settings_manage")
def add_preparation_combination():
    db = get_db()
    try:
        name, config = clean_preparation_combination(db, request.json or {})
        combination_id = db.execute("""INSERT INTO preparation_combinations(name,config_json)
            VALUES(%s,%s) RETURNING id""", (name, json.dumps(config))).fetchone()["id"]
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except INTEGRITY_ERRORS:
        return jsonify(ok=False, error="溶样组合名称已存在"), 409
    audit_event(db, "create", "preparation_combination", combination_id,
                after=db.execute("SELECT * FROM preparation_combinations WHERE id=%s",
                                 (combination_id,)).fetchone())
    db.commit()
    return jsonify(ok=True, id=combination_id)


@app.put("/api/preparation-combinations/<int:combination_id>")
@capability_required("settings_manage")
def update_preparation_combination(combination_id):
    db = get_db()
    before = db.execute("SELECT * FROM preparation_combinations WHERE id=%s",
                        (combination_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="溶样组合不存在"), 404
    try:
        name, config = clean_preparation_combination(db, request.json or {})
        db.execute("UPDATE preparation_combinations SET name=%s,config_json=%s WHERE id=%s",
                   (name, json.dumps(config), combination_id))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except INTEGRITY_ERRORS:
        return jsonify(ok=False, error="溶样组合名称已存在"), 409
    audit_event(db, "update", "preparation_combination", combination_id, before=before,
                after=db.execute("SELECT * FROM preparation_combinations WHERE id=%s",
                                 (combination_id,)).fetchone())
    db.commit()
    return jsonify(ok=True, id=combination_id)


@app.delete("/api/preparation-combinations/<int:combination_id>")
@capability_required("settings_manage")
def delete_preparation_combination(combination_id):
    db = get_db()
    before = db.execute("SELECT * FROM preparation_combinations WHERE id=%s",
                        (combination_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="溶样组合不存在"), 404
    db.execute("DELETE FROM preparation_combinations WHERE id=%s", (combination_id,))
    audit_event(db, "delete", "preparation_combination", combination_id, before=before)
    db.commit()
    return jsonify(ok=True)


@app.post("/api/volume-presets")
@capability_required("settings_manage")
def add_volume_preset():
    try:
        volume_ml = float((request.json or {}).get("volume_ml"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="定容容量必须是数字"), 400
    if not math.isfinite(volume_ml) or volume_ml <= 0:
        return jsonify(ok=False, error="定容容量必须大于 0"), 400
    db = get_db()
    existing = db.execute("SELECT id,active FROM volume_presets WHERE volume_ml=%s",
                          (volume_ml,)).fetchone()
    if existing:
        if existing["active"]:
            return jsonify(ok=False, error=f"定容容量 {volume_ml:g} mL 已存在"), 409
        db.execute("UPDATE volume_presets SET active=1 WHERE id=%s", (existing["id"],))
        audit_event(db, "restore", "volume_preset", existing["id"],
                    after={"volume_ml": volume_ml, "active": 1})
        db.commit()
        return jsonify(ok=True, id=existing["id"], volume_ml=volume_ml, restored=True)
    preset_id = db.execute("INSERT INTO volume_presets(volume_ml) VALUES(%s) RETURNING id",
                           (volume_ml,)).fetchone()["id"]
    audit_event(db, "create", "volume_preset", preset_id,
                after={"volume_ml": volume_ml, "active": 1})
    db.commit()
    return jsonify(ok=True, id=preset_id, volume_ml=volume_ml)


@app.delete("/api/volume-presets/<int:preset_id>")
@capability_required("settings_manage")
def delete_volume_preset(preset_id):
    db = get_db()
    preset = db.execute("SELECT * FROM volume_presets WHERE id=%s", (preset_id,)).fetchone()
    if not preset:
        return jsonify(ok=False, error="定容容量选项不存在"), 404
    historical = db.execute("SELECT COUNT(*) FROM preparations WHERE volume_ml=%s",
                            (preset["volume_ml"],)).fetchone()[0]
    if not preset["active"]:
        return jsonify(ok=True, hidden=True, historical_preparations=historical)
    if float(preset["volume_ml"]) == 250:
        return jsonify(ok=False, error="250 mL 是新建溶样的默认容量，不能移除"), 400
    if db.execute("SELECT COUNT(*) FROM volume_presets WHERE active=1").fetchone()[0] <= 1:
        return jsonify(ok=False, error="至少需要保留一种可选定容容量"), 400
    db.execute("UPDATE volume_presets SET active=0 WHERE id=%s", (preset_id,))
    audit_event(db, "disable", "volume_preset", preset_id, before=preset,
                after={"active": 0}, reason=f"保留 {historical} 条历史溶样容量")
    db.commit()
    return jsonify(ok=True, hidden=True, historical_preparations=historical)


@app.route("/api/methods", methods=["POST"])
@capability_required("settings_manage")
def add_method():
    d = request.json or {}
    itype = str(d.get("itype", "function")).strip()
    if itype not in {"function", "xrf"}:
        return jsonify(ok=False, error="方法类型只支持公式或 XRF"), 400
    f = d.get("formula", "").strip()
    try:
        variables = formula_variables(f) if itype == "function" else []
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    constants = d.get("constants", {})
    if not isinstance(constants, dict):
        return jsonify(ok=False, error="方法常数格式不正确"), 400
    try:
        constants = {str(key): float(value) for key, value in constants.items()}
    except (TypeError, ValueError):
        return jsonify(ok=False, error="方法常数必须是数字"), 400
    invalid_keys = set(constants) - set(variables)
    if invalid_keys:
        return jsonify(ok=False, error="公式中未使用这些常数: " + ", ".join(sorted(invalid_keys))), 400
    fixed_keys = set(constants) & METHOD_FIXED_VARS
    if fixed_keys:
        return jsonify(ok=False, error="m 和 v 固定取样品称样量与定容体积，无需设置常数"), 400
    note = str(d.get("note", "")).strip()
    if len(note) > 2000:
        return jsonify(ok=False, error="方法说明不能超过 2000 个字符"), 400
    target = str(d.get("target", "")).strip()
    if len(target) > 40:
        return jsonify(ok=False, error="检测对象不能超过 40 个字符"), 400
    output_unit = str(d.get("output_unit") or "%").strip()
    if output_unit not in METHOD_OUTPUT_UNITS:
        return jsonify(ok=False, error="公式输出单位无效"), 400
    db = get_db()
    if itype == "xrf":
        f, constants, output_unit = "", {}, "%"
    method_id = db.execute("""INSERT INTO methods(name,itype,formula,constants,note,output_unit,target,sort_order)
        VALUES(%s,%s,%s,%s,%s,%s,%s,COALESCE((SELECT MAX(sort_order)+1 FROM methods),1))
        RETURNING id""",
        (d["name"].strip(), itype, f, json.dumps(constants), note, output_unit, target)).fetchone()["id"]
    audit_event(db, "create", "method", method_id,
                after={"name": d["name"].strip(), "itype": itype,
                        "formula": f, "constants": constants, "output_unit": output_unit,
                        "target": target})
    db.commit()
    return jsonify(ok=True)


@app.put("/api/methods/<int:mid>/note")
@capability_required("settings_manage")
def update_method_note(mid):
    db = get_db()
    before = db.execute("SELECT * FROM methods WHERE id=%s", (mid,)).fetchone()
    if not before:
        return jsonify(ok=False, error="分析方法不存在"), 404
    data = request.json or {}
    note = str(data.get("note", "")).strip()
    if len(note) > 2000:
        return jsonify(ok=False, error="方法说明不能超过 2000 个字符"), 400
    output_unit = str(data.get("output_unit") or before["output_unit"] or "%").strip()
    if output_unit not in METHOD_OUTPUT_UNITS:
        return jsonify(ok=False, error="公式输出单位无效"), 400
    if before["itype"] == "xrf":
        output_unit = "%"
        target = str(before["target"] or "")
    else:
        target = str(data.get("target", before["target"]) or "").strip()
        if len(target) > 40:
            return jsonify(ok=False, error="检测对象不能超过 40 个字符"), 400
    try:
        active = 1 if int(data.get("active", before["active"])) else 0
    except (TypeError, ValueError):
        return jsonify(ok=False, error="启用状态无效"), 400
    db.execute("UPDATE methods SET note=%s,output_unit=%s,active=%s,target=%s WHERE id=%s",
               (note, output_unit, active, target, mid))
    audit_event(db, "update", "method", mid, before=before,
                after=db.execute("SELECT * FROM methods WHERE id=%s", (mid,)).fetchone())
    db.commit()
    return jsonify(ok=True)


@app.route("/api/methods/<int:mid>", methods=["DELETE"])
@capability_required("settings_manage")
def del_method(mid):
    db = get_db()
    before = db.execute("SELECT * FROM methods WHERE id=%s", (mid,)).fetchone()
    if db.execute("SELECT 1 FROM sample_analytes WHERE method_id=%s LIMIT 1", (mid,)).fetchone():
        return jsonify(ok=False, error="方法已被样品使用，请改为停用以保留历史结果"), 409
    db.execute("DELETE FROM methods WHERE id=%s", (mid,))
    if before:
        audit_event(db, "delete", "method", mid, before=before)
    db.commit()
    return jsonify(ok=True)


@app.route("/api/templates", methods=["POST"])
@capability_required("settings_manage")
def add_template():
    d = request.json
    db = get_db()
    is_water_quality = int(bool(d.get("is_water_quality", 0)))
    is_liquid = int(bool(d.get("is_liquid", 0)) or is_water_quality)
    try:
        order_template_id = _validated_order_template_id(db, d.get("order_template_id"))
        template_tags = clean_sample_tags(d.get("tags", []))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    template_id = db.execute("""INSERT INTO templates(
        name,category,tags_json,is_liquid,is_water_quality,dilution_id,xrf,analyte_ids,prep_config,instrument_config,
        order_template_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
               (d["name"].strip(), str(d.get("category", "")).strip(),
                  json.dumps(template_tags, ensure_ascii=False), is_liquid, is_water_quality, d.get("dilution_id"),
                  int(d.get("xrf", 0)), json.dumps(d.get("analyte_ids", [])),
                  json.dumps(d.get("preps", [])), json.dumps(d.get("instrument_map", {})),
                   order_template_id)).fetchone()["id"]
    audit_event(db, "create", "template", template_id, after={"name": d["name"].strip()})
    db.commit()
    return jsonify(ok=True, id=template_id)


@app.route("/api/templates/<int:tid>", methods=["PUT"])
@capability_required("settings_manage")
def update_template(tid):
    d = request.json
    db = get_db()
    is_water_quality = int(bool(d.get("is_water_quality", 0)))
    is_liquid = int(bool(d.get("is_liquid", 0)) or is_water_quality)
    try:
        order_template_id = _validated_order_template_id(db, d.get("order_template_id"))
        template_tags = clean_sample_tags(d.get("tags", []))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    before = db.execute("SELECT * FROM templates WHERE id=%s", (tid,)).fetchone()
    cur = db.execute("""UPDATE templates SET name=%s,category=%s,tags_json=%s,is_liquid=%s,is_water_quality=%s,dilution_id=%s,xrf=%s,
        analyte_ids=%s,prep_config=%s,instrument_config=%s,order_template_id=%s WHERE id=%s""",
        (d["name"].strip(), str(d.get("category", "")).strip(),
         json.dumps(template_tags, ensure_ascii=False), is_liquid, is_water_quality, d.get("dilution_id"),
         int(d.get("xrf", 0)), json.dumps(d.get("analyte_ids", [])),
         json.dumps(d.get("preps", [])), json.dumps(d.get("instrument_map", {})),
         order_template_id, tid))
    if not cur.rowcount:
        return jsonify(ok=False, error="模板不存在"), 404
    audit_event(db, "update", "template", tid, before=before,
                after=db.execute("SELECT * FROM templates WHERE id=%s", (tid,)).fetchone())
    db.commit()
    return jsonify(ok=True, id=tid)


@app.route("/api/templates/<int:tid>", methods=["DELETE"])
@capability_required("settings_manage")
def del_template(tid):
    db = get_db()
    before = db.execute("SELECT * FROM templates WHERE id=%s", (tid,)).fetchone()
    db.execute("DELETE FROM templates WHERE id=%s", (tid,))
    if before:
        audit_event(db, "delete", "template", tid, before=before)
    db.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- 样品与结果

@app.route("/api/samples", methods=["GET"])
def list_samples():
    query = request.args.get("q", "").strip()
    sample_type = request.args.get("type", "all")
    requested_statuses = [item.strip() for item in request.args.get("status", "").split(",")
                          if item.strip()]
    if any(status not in SAMPLE_STATUS_LABELS for status in requested_statuses):
        return jsonify(ok=False, error="样品状态筛选无效"), 400
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        limit, offset = 100, 0
    conditions, args = [], []
    try:
        requested_tags = clean_sample_tags(request.args.getlist("tag"))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    for tag in requested_tags:
        conditions.append("EXISTS(SELECT 1 FROM sample_tags st WHERE st.sample_id=s.id AND st.tag=%s)")
        args.append(tag)
    if query:
        conditions.append("""(s.name LIKE %s OR s.lims_no LIKE %s OR CAST(s.id AS TEXT)=%s OR EXISTS(
            SELECT 1 FROM sample_analytes sx JOIN analytes ax ON ax.id=sx.analyte_id
            WHERE sx.sample_id=s.id AND ax.name LIKE %s) OR EXISTS(
            SELECT 1 FROM special_methods smx WHERE smx.id=s.special_method_id
            AND (smx.name LIKE %s OR smx.instrument LIKE %s)))""")
        args.extend((f"%{query}%", f"%{query}%", query.lstrip("#"), f"%{query}%",
                     f"%{query}%", f"%{query}%"))
    if request.args.get("include_cancelled") != "1":
        conditions.append("COALESCE(s.status,'received')!='cancelled'")
    if requested_statuses:
        conditions.append(f"s.status IN ({','.join('%s' for _ in requested_statuses)})")
        args.extend(requested_statuses)
    if request.args.get("xrf") == "1":
        conditions.append("s.xrf=1 AND COALESCE(s.workflow_type,'regular')='regular'")
    if request.args.get("xrf_available") == "1":
        conditions.append("NOT EXISTS(SELECT 1 FROM xrf_analyses xa WHERE xa.sample_id=s.id)")
    if sample_type == "solid":
        conditions.append("s.is_liquid=0 AND COALESCE(s.workflow_type,'regular')='regular'")
    elif sample_type == "liquid":
        conditions.append("s.is_liquid=1 AND COALESCE(s.is_water_quality,0)=0 AND COALESCE(s.workflow_type,'regular')='regular'")
    elif sample_type == "water_quality":
        conditions.append("COALESCE(s.is_water_quality,0)=1 AND COALESCE(s.workflow_type,'regular')='regular'")
    elif sample_type == "special":
        conditions.append("s.workflow_type='special'")
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    total = get_db().execute(f"SELECT COUNT(*) FROM samples s {where}", args).fetchone()[0]
    page_args = args + [limit, offset]
    data = rows(f"""SELECT s.*, sm.name AS special_method_name, sm.instrument AS special_instrument,
                           (SELECT string_agg(name, ' ' ORDER BY id) FROM preparations
                            WHERE sample_id=s.id) AS prep_names,
                           (SELECT COUNT(*) FROM preparations
                            WHERE sample_id=s.id) AS prep_count,
                           (SELECT string_agg(name, ', ' ORDER BY analyte_sort_id) FROM (
                               SELECT DISTINCT a.name, a.id AS analyte_sort_id
                               FROM sample_analytes sa JOIN analytes a ON a.id=sa.analyte_id
                               WHERE sa.sample_id=s.id ORDER BY analyte_sort_id
                             ) AS sample_analytes) AS analyte_names
                           FROM samples s LEFT JOIN special_methods sm ON sm.id=s.special_method_id
                            {where} ORDER BY s.id DESC LIMIT %s OFFSET %s""", page_args)
    order_keys = {}
    for sample in data:
        names = [name.strip() for name in str(sample.get("analyte_names") or "").split(",")
                 if name.strip()]
        if not names:
            continue
        template_id = sample.get("order_template_id")
        if template_id not in order_keys:
            order_keys[template_id] = _universal_order_key(get_db(), template_id)
        sample["analyte_names"] = ", ".join(sorted(names, key=order_keys[template_id]))
    attach_sample_tags(get_db(), data)
    attach_sample_status_history(get_db(), data)
    if request.args.get("paged") == "1":
        return jsonify({"rows": data, "total": total, "limit": limit, "offset": offset})
    return jsonify(data)


@app.route("/api/samples", methods=["POST"])
@capability_required("sample_manage")
def add_sample():
    d = request.json or {}
    name = str(d.get("name", "")).strip()
    if not name:
        return jsonify(ok=False, error="来样序号不能为空"), 400
    db = get_db()
    workflow_type = "special" if d.get("workflow_type") == "special" else "regular"
    if workflow_type == "special" and d.get("is_water_quality"):
        return jsonify(ok=False, error="水质样不能使用其他样流程"), 400
    if workflow_type == "special":
        special_method_id = d.get("special_method_id")
        if not db.execute("SELECT 1 FROM special_methods WHERE id=%s AND active=1",
                          (special_method_id,)).fetchone():
            return jsonify(ok=False, error="请选择有效的专项检测方法"), 400
        lims_no = next_lims_no(db)
        sid = db.execute("""INSERT INTO samples(name,category,is_liquid,workflow_type,
            special_method_id,xrf,lims_no,status,report_order)
            VALUES(%s,%s,0,'special',%s,0,%s,'received','[]') RETURNING id""",
            (name, str(d.get("category", "")).strip(), special_method_id, lims_no)).fetchone()["id"]
        try:
            replace_sample_tags(db, sid, d.get("tags", []))
        except ValueError as exc:
            db.rollback()
            return jsonify(ok=False, error=str(exc)), 400
        mark_sample_status_actor(db, sid, "received")
        db.execute("INSERT INTO special_results(sample_id,method_id) VALUES(%s,%s)",
                   (sid, special_method_id))
        audit_event(db, "create", "sample", sid, after=sample_audit_snapshot(db, sid))
        db.commit()
        return jsonify(ok=True, id=sid, lims_no=lims_no, status="received")
    instrument_map = d.get("instrument_map", {})
    try:
        order_template_id = _validated_order_template_id(db, d.get("order_template_id"))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    is_water_quality = int(bool(d.get("is_water_quality", 0)))
    is_liquid = int(bool(d.get("is_liquid", 0)) or is_water_quality)
    try:
        density_g_ml = optional_density(d) if is_liquid else None
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    xrf_enabled = int(bool(d.get("xrf", 0)))
    xrf_method_id = d.get("xrf_method_id") if xrf_enabled else None
    if xrf_enabled and not db.execute(
            "SELECT 1 FROM methods WHERE id=%s AND itype='xrf'", (xrf_method_id,)).fetchone():
        return jsonify(ok=False, error="请选择有效的 XRF 方法"), 400
    try:
        prepared_rows = [(p, preparation_values(db, p)) for p in d.get("preps", [])]
    except (KeyError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc) or "溶样名称不能为空"), 400
    lims_no = next_lims_no(db)
    sid = db.execute("""INSERT INTO samples(
        name,category,is_liquid,density_g_ml,is_water_quality,xrf,xrf_method_id,xrf_report_items,
        lims_no,status,report_order,order_template_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'received',%s,%s) RETURNING id""",
        (name, d.get("category", "").strip(), is_liquid, density_g_ml, is_water_quality,
         xrf_enabled, xrf_method_id, str(d.get("xrf_report_items", "")).strip(),
         lims_no, json.dumps(d.get("report_order", [])), order_template_id)).fetchone()["id"]
    try:
        replace_sample_tags(db, sid, d.get("tags", []))
    except ValueError as exc:
        db.rollback()
        return jsonify(ok=False, error=str(exc)), 400
    mark_sample_status_actor(db, sid, "received")
    if xrf_enabled:
        _sync_sample_xrf_targets(db, sid, str(d.get("xrf_report_items", "")))
    for p, values in prepared_rows:
        prep_instrument_map = p.get("instrument_map", instrument_map)
        pid = db.execute("""INSERT INTO preparations(sample_id,name,mass_g,volume_ml,dilution_id,
                dilution_steps,dilution_factor,dilution_label)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (sid,) + values).fetchone()["id"]
        for a in p.get("analyte_ids", []):
            instrument_id, method_id = task_defaults(db, prep_instrument_map, a)
            db.execute(
                """INSERT INTO sample_analytes(
                    sample_id,preparation_id,analyte_id,instrument_id,method_id)
                   VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (sid, pid, a, instrument_id, method_id))
    audit_event(db, "create", "sample", sid, after=sample_audit_snapshot(db, sid))
    db.commit()
    return jsonify(ok=True, id=sid, lims_no=lims_no, status="received")


@app.route("/api/samples/<int:sid>", methods=["DELETE"])
@capability_required("sample_manage")
def del_sample(sid):
    """Cancel a sample while preserving its auditable business record."""
    db = get_db()
    before = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not before:
        return jsonify(ok=False, error="样品不存在"), 404
    if before["status"] == "cancelled":
        return jsonify(ok=True, cancelled=True)
    if before["status"] == "reviewed":
        return jsonify(ok=False, error="已审核样品不能作废；如需修改请先执行特权审核退回"), 409
    reason = str((request.json or {}).get("reason", "用户作废样品")).strip()
    db.execute("""UPDATE samples SET status='cancelled',cancelled_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
        cancelled_by=%s,cancel_reason=%s,updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
        (g.user["id"], reason, sid))
    mark_sample_status_actor(db, sid, "cancelled")
    db.execute("UPDATE sample_analytes SET status='cancelled' WHERE sample_id=%s", (sid,))
    db.execute("UPDATE special_results SET status='cancelled' WHERE sample_id=%s", (sid,))
    after = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    audit_event(db, "cancel", "sample", sid, before=before, after=after, reason=reason)
    db.commit()
    return jsonify(ok=True, cancelled=True)


@app.route("/api/samples/<int:sid>/status", methods=["PUT"])
def update_sample_status(sid):
    data = request.json or {}
    target = data.get("status")
    reason = str(data.get("reason", "")).strip()
    db = get_db()
    before = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not before:
        return jsonify(ok=False, error="样品不存在"), 404
    permissions = user_permissions(g.user)
    privileged_rollback = before["status"] == "reviewed" and target == "completed"
    privileged_actor = None
    if privileged_rollback:
        if "result_override" not in permissions:
            return jsonify(ok=False, code="permission_denied", capability="result_override",
                           error="当前用户没有审核退回与手工结果补录权限"), 403
        if not reason:
            return jsonify(ok=False, error="审核退回必须填写原因"), 400
        privileged_actor = consume_forced_authorization("result_override")
        if not privileged_actor:
            return jsonify(ok=False, code="forced_authorization_required",
                           capability="result_override",
                           error="审核退回必须重新输入具备特权操作权限的用户密码"), 428
    elif not can_transition(permissions, before["status"], target):
        return jsonify(ok=False, error="当前状态或用户能力不允许执行此转换"), 400
    if target in {"completed", "reviewed"}:
        if before["workflow_type"] == "special":
            result = db.execute("SELECT status FROM special_results WHERE sample_id=%s", (sid,)).fetchone()
            incomplete = 0 if result and result["status"] == "completed" else 1
        else:
            incomplete = db.execute("""SELECT COUNT(*) FROM sample_analytes sa
                LEFT JOIN instruments i ON i.id=sa.instrument_id
                WHERE sa.sample_id=%s AND sa.status!='completed' AND COALESCE(i.itype,'')!='xrf'""",
                (sid,)).fetchone()[0]
            if before["xrf"] and not db.execute(
                    "SELECT 1 FROM xrf_analyses WHERE sample_id=%s LIMIT 1", (sid,)).fetchone():
                incomplete += 1
        if incomplete:
            return jsonify(ok=False, error=f"还有 {incomplete} 个分析任务未完成，不能完成或审核"), 409
    if target == "cancelled" and not reason:
        return jsonify(ok=False, error="作废样品必须填写原因"), 400
    if target == "cancelled":
        db.execute("""UPDATE samples SET status=%s,cancelled_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
            cancelled_by=%s,cancel_reason=%s,updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
            (target, g.user["id"], reason, sid))
        db.execute("UPDATE sample_analytes SET status='cancelled' WHERE sample_id=%s", (sid,))
        db.execute("UPDATE special_results SET status='cancelled' WHERE sample_id=%s", (sid,))
    else:
        db.execute("UPDATE samples SET status=%s,updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s",
                   (target, sid))
    if target == "measuring" and not before["analyst"]:
        db.execute("UPDATE samples SET analyst=%s WHERE id=%s", (current_actor_name(), sid))
    if target == "reviewed":
        db.execute("UPDATE samples SET reviewer=%s WHERE id=%s", (current_actor_name(), sid))
    elif target == "completed" and privileged_rollback:
        db.execute("UPDATE samples SET reviewer='' WHERE id=%s", (sid,))
    mark_sample_status_actor(db, sid, target, privileged_actor)
    after = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    audit_event(db, "status_change", "sample", sid, before=before, after=after,
                reason=reason, user=privileged_actor)
    db.commit()
    return jsonify(ok=True, status=target)


@app.route("/api/samples/<int:sid>")
def sample_detail(sid):
    db = get_db()
    sample_row = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample_row:
        return jsonify(ok=False, error="样品不存在"), 404
    sample = dict(sample_row)
    attach_sample_tags(db, [sample])
    attach_sample_status_history(db, [sample])
    if sample["workflow_type"] == "special":
        special = db.execute("""SELECT sr.*,sm.code,sm.name AS method_name,
            sm.instrument,sm.schema_json FROM special_results sr
            JOIN special_methods sm ON sm.id=sr.method_id WHERE sr.sample_id=%s""", (sid,)).fetchone()
        special_data = dict(special) if special else None
        if special_data:
            special_data["schema"] = json.loads(special_data.pop("schema_json") or "{}")
            special_data["raw_data"] = json.loads(special_data["raw_data"] or "{}")
            special_data["calculated_data"] = json.loads(special_data["calculated_data"] or "{}")
        return jsonify({"sample": sample, "preps": [], "items": [], "special": special_data})
    preps = rows("""SELECT p.*,p.dilution_factor AS factor
                    FROM preparations p WHERE p.sample_id=%s ORDER BY p.id""", (sid,))
    for prep in preps:
        prep["dilution_ids"] = json.loads(prep.get("dilution_steps") or "[]")
    items = rows("""SELECT sa.*, a.name AS analyte,
                           a.sort_order AS analyte_sort_order,
                           i.name AS instrument, i.itype,
                           i.sort_order AS instrument_sort_order,
                           m.name AS method_name, m.formula, m.note AS method_note,
                            m.constants AS method_constants, m.output_unit AS method_output_unit,
                            r.aux,
                           p.name AS prep_name, p.mass_g AS prep_mass,
                           p.volume_ml AS prep_vol, p.dilution_factor AS prep_factor,
                           p.dilution_label AS prep_dilution
                    FROM sample_analytes sa
                    JOIN analytes a ON a.id=sa.analyte_id
                    LEFT JOIN instruments i ON i.id=sa.instrument_id
                    LEFT JOIN methods m ON m.id=sa.method_id
                    LEFT JOIN results r ON r.sample_analyte_id=sa.id
                    LEFT JOIN preparations p ON p.id=sa.preparation_id
                    WHERE sa.sample_id=%s ORDER BY sa.id""", (sid,))
    reads = rows("""SELECT rd.* FROM readings rd
                    JOIN sample_analytes sa ON sa.id=rd.sample_analyte_id
                    WHERE sa.sample_id=%s ORDER BY rd.id""", (sid,))
    by_task = {}
    for rd in reads:
        rd["version"] = reading_version(rd)
        by_task.setdefault(rd["sample_analyte_id"], []).append(rd)
    for it in items:
        it["readings"] = by_task.get(it["id"], [])
    sample_order_key = _sample_analyte_order_key(db, sample)
    items.sort(key=lambda item: (sample_order_key(item),
                                 item.get("instrument_sort_order") or 0,
                                 item.get("preparation_id") or 0, item["id"]))
    return jsonify({"sample": sample, "preps": preps, "items": items, "special": None})


@app.route("/api/samples/<int:sid>/report-order", methods=["PUT"])
@capability_required("report_edit")
def set_sample_report_order(sid):
    db = get_db()
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="样品不存在"), 404
    if sample["status"] == "cancelled":
        return jsonify(ok=False, error="已作废的样品不能调整元素顺序"), 409
    requested = (request.json or {}).get("analyte_ids", [])
    has_template = "order_template_id" in (request.json or {})
    try:
        order_template_id = (_validated_order_template_id(
            db, (request.json or {}).get("order_template_id")) if has_template
            else sample["order_template_id"])
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    available = {row[0] for row in db.execute(
        "SELECT DISTINCT analyte_id FROM sample_analytes WHERE sample_id=%s", (sid,))}
    ordered = []
    for item in requested:
        try:
            aid = int(item)
        except (TypeError, ValueError):
            continue
        if aid in available and aid not in ordered:
            ordered.append(aid)
    before = {"report_order": sample["report_order"],
              "order_template_id": sample["order_template_id"]}
    db.execute("""UPDATE samples SET report_order=%s,order_template_id=%s,
        updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
               (json.dumps(ordered), order_template_id, sid))
    audit_event(db, "report_order", "sample", sid,
                before=before, after={"report_order": ordered,
                                      "order_template_id": order_template_id})
    db.commit()
    return jsonify(ok=True, analyte_ids=ordered, order_template_id=order_template_id)


def _report_print_excludes(sample):
    try:
        value = json.loads(sample["report_excludes"] or "[]")
    except (TypeError, json.JSONDecodeError, KeyError, IndexError):
        value = []
    return {str(item) for item in value} if isinstance(value, list) else set()


@app.route("/api/samples/<int:sid>/report-print", methods=["PUT"])
@capability_required("report_edit")
def set_report_print(sid):
    """报告编排：只控制某元素是否打印，不改变任何检测结果。"""
    db = get_db()
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="样品不存在"), 404
    if sample["status"] == "cancelled":
        return jsonify(ok=False, error="已作废的样品不能调整打印内容"), 409
    requested = (request.json or {}).get("excludes", [])
    if not isinstance(requested, list) or len(requested) > 500:
        return jsonify(ok=False, error="打印排除列表格式无效"), 400
    excludes = []
    for item in requested:
        text = str(item).strip()
        if (re.fullmatch(r"a:\d+", text) or
                (text.startswith(("x:", "m:")) and 0 < len(text) <= 122)):
            if text not in excludes:
                excludes.append(text)
    before = sample["report_excludes"]
    db.execute("UPDATE samples SET report_excludes=%s,updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s",
               (json.dumps(excludes, ensure_ascii=False), sid))
    audit_event(db, "report_print", "sample", sid,
                before={"report_excludes": before}, after={"report_excludes": excludes})
    db.commit()
    return jsonify(ok=True, excludes=excludes)


@app.route("/api/samples/<int:sid>/result-unit", methods=["PUT"])
@capability_required("report_edit")
def set_result_unit(sid):
    db = get_db()
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="样品不存在"), 404
    if sample["status"] == "cancelled":
        return jsonify(ok=False, error="已出报告或已作废的样品不能修改结果单位"), 409
    data = request.json or {}
    key = str(data.get("key", "")).strip()
    unit = normalized_result_unit(data.get("unit"))
    if not (re.fullmatch(r"a:\d+", key) or key.startswith("x:")) or len(key) > 122:
        return jsonify(ok=False, error="结果项目无效"), 400
    try:
        payload = cached_report_payload(db, sid)
    except BusinessExcelError as exc:
        return jsonify(ok=False, error=str(exc)), 404
    group = next((item for item in payload.get("groups", []) if item.get("key") == key), None)
    if not group or unit not in group.get("available_units", []):
        return jsonify(ok=False, error="该结果不能使用所选单位"), 400
    try:
        current = json.loads(sample["result_units"] or "{}")
    except (TypeError, json.JSONDecodeError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    before = dict(current)
    current[key] = unit
    db.execute("""UPDATE samples SET result_units=%s,
        updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
               (json.dumps(current, ensure_ascii=False), sid))
    audit_event(db, "result_unit", "sample", sid,
                before={"result_units": before}, after={"result_units": current})
    db.commit()
    return jsonify(ok=True, key=key, unit=unit)


@app.route("/api/samples/<int:sid>", methods=["PUT"])
@capability_required("sample_manage")
def update_sample(sid):
    """同步样品及其分析任务；未改变的任务行会保留已有结果。"""
    d = request.json or {}
    name = d.get("name", "").strip()
    if not name:
        return jsonify(ok=False, error="来样序号不能为空"), 400
    db = get_db()
    before_row = locked_row(db, "SELECT * FROM samples WHERE id=%s", (sid,))
    if not before_row:
        return jsonify(ok=False, error="样品不存在"), 404
    if "expected_updated_at" in d and d["expected_updated_at"] != before_row["updated_at"]:
        db.rollback()
        return jsonify(ok=False, code="version_conflict", error="Sample changed; reload before saving"), 409
    if before_row["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="已审核、已出报告或已作废的样品不能直接修改"), 409
    before = sample_audit_snapshot(db, sid)
    requested_workflow = "special" if d.get("workflow_type") == "special" else "regular"
    if requested_workflow == "special" and d.get("is_water_quality"):
        return jsonify(ok=False, error="水质样不能使用其他样流程"), 400
    if before_row["workflow_type"] == "special" or requested_workflow == "special":
        if before_row["workflow_type"] != requested_workflow:
            return jsonify(ok=False, error="常规样和专项样不能相互转换，请新建样品"), 409
        special_method_id = d.get("special_method_id")
        method = db.execute("SELECT * FROM special_methods WHERE id=%s AND active=1",
                            (special_method_id,)).fetchone()
        if not method:
            return jsonify(ok=False, error="请选择有效的专项检测方法"), 400
        result = db.execute("SELECT * FROM special_results WHERE sample_id=%s", (sid,)).fetchone()
        if result and result["method_id"] != special_method_id and json.loads(result["raw_data"] or "{}"):
            return jsonify(ok=False, error="已有专项数据，不能直接更换方法；请新建样品"), 409
        if "tags" in d:
            try:
                replace_sample_tags(db, sid, d.get("tags"))
            except ValueError as exc:
                return jsonify(ok=False, error=str(exc)), 400
        db.execute("""UPDATE samples SET name=%s,category=%s,special_method_id=%s,
            updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
            (name, str(d.get("category", "")).strip(), special_method_id, sid))
        db.execute("""INSERT INTO special_results(sample_id,method_id) VALUES(%s,%s)
            ON CONFLICT(sample_id) DO UPDATE SET method_id=excluded.method_id""",
            (sid, special_method_id))
        updated_at = next_updated_at(before_row["updated_at"])
        db.execute("UPDATE samples SET updated_at=%s WHERE id=%s", (updated_at, sid))
        audit_event(db, "update", "sample", sid, before=before,
                    after=sample_audit_snapshot(db, sid))
        db.commit()
        return jsonify(ok=True, id=sid, lims_no=before_row["lims_no"], status=before_row["status"],
                       updated_at=updated_at)
    instrument_map = d.get("instrument_map", {})
    try:
        requested_tags = clean_sample_tags(d.get("tags")) if "tags" in d else None
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    is_water_quality = int(bool(d.get("is_water_quality", 0)))
    is_liquid = int(bool(d.get("is_liquid", 0)) or is_water_quality)
    try:
        density_g_ml = optional_density(d) if is_liquid else None
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    xrf_enabled = int(bool(d.get("xrf", 0)))
    xrf_method_id = d.get("xrf_method_id") if xrf_enabled else None
    if xrf_enabled and not db.execute(
            "SELECT 1 FROM methods WHERE id=%s AND itype='xrf'", (xrf_method_id,)).fetchone():
        return jsonify(ok=False, error="请选择有效的 XRF 方法"), 400

    report_order = d.get("report_order")
    if report_order is not None and not isinstance(report_order, list):
        return jsonify(ok=False, error="报告元素顺序格式无效"), 400
    try:
        order_template_id = _validated_order_template_id(
            db, d.get("order_template_id", before_row["order_template_id"]))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    try:
        prepared_rows = [(p, preparation_values(db, p)) for p in d.get("preps", [])]
    except (KeyError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc) or "溶样名称不能为空"), 400
    report_order_json = None if report_order is None else json.dumps(report_order)
    db.execute("""UPDATE samples SET name=%s,category=%s,is_liquid=%s,density_g_ml=%s,is_water_quality=%s,xrf=%s,
                   xrf_method_id=%s,xrf_report_items=%s,
                   report_order=COALESCE(%s,report_order),order_template_id=%s,
             updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
               (name, d.get("category", "").strip(), is_liquid, density_g_ml, is_water_quality,
                  xrf_enabled, xrf_method_id, str(d.get("xrf_report_items", "")).strip(),
                  report_order_json, order_template_id, sid))
    if requested_tags is not None:
        replace_sample_tags(db, sid, requested_tags)
    _sync_sample_xrf_targets(db, sid, str(d.get("xrf_report_items", "")))
    existing_pids = {r[0] for r in db.execute(
        "SELECT id FROM preparations WHERE sample_id=%s", (sid,))}
    kept_pids = set()

    for p, values in prepared_rows:
        prep_instrument_map = p.get("instrument_map", instrument_map)
        has_prep_instrument_map = "instrument_map" in p
        pid = p.get("id")
        if pid in existing_pids:
            db.execute("""UPDATE preparations SET name=%s,mass_g=%s,volume_ml=%s,dilution_id=%s,
                       dilution_steps=%s,dilution_factor=%s,dilution_label=%s
                       WHERE id=%s AND sample_id=%s""", values + (pid, sid))
        else:
            pid = db.execute("""INSERT INTO preparations(sample_id,name,mass_g,volume_ml,dilution_id,
                    dilution_steps,dilution_factor,dilution_label)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (sid,) + values).fetchone()["id"]
        kept_pids.add(pid)
        wanted = {int(a) for a in p.get("analyte_ids", [])}
        current = {r["analyte_id"]: r for r in db.execute(
            """SELECT analyte_id,id,instrument_id,method_id FROM sample_analytes
               WHERE sample_id=%s AND preparation_id=%s""", (sid, pid))}
        for aid, task in current.items():
            if aid not in wanted:
                db.execute("DELETE FROM sample_analytes WHERE id=%s", (task["id"],))
            elif has_prep_instrument_map or str(aid) in instrument_map:
                instrument_id, method_id = task_defaults(db, prep_instrument_map, aid)
                if (task["instrument_id"], task["method_id"]) != (instrument_id, method_id):
                    db.execute("""UPDATE sample_analytes SET instrument_id=%s,method_id=%s,
                        status='pending' WHERE id=%s""", (instrument_id, method_id, task["id"]))
                    db.execute("DELETE FROM results WHERE sample_analyte_id=%s", (task["id"],))
                    db.execute("DELETE FROM readings WHERE sample_analyte_id=%s", (task["id"],))
        for aid in wanted - set(current):
            instrument_id, method_id = task_defaults(db, prep_instrument_map, aid)
            db.execute("""INSERT INTO sample_analytes(
                sample_id,preparation_id,analyte_id,instrument_id,method_id)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (sid, pid, aid, instrument_id, method_id))

    for pid in existing_pids - kept_pids:
        db.execute("DELETE FROM preparations WHERE id=%s", (pid,))

    recompute_sample_progress(db, sid)
    db.execute("UPDATE samples SET updated_at=%s WHERE id=%s", (next_updated_at(before_row["updated_at"]), sid))
    after = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    audit_event(db, "update", "sample", sid, before=before,
                after=sample_audit_snapshot(db, sid))
    db.commit()
    return jsonify(ok=True, id=sid, lims_no=after["lims_no"], status=after["status"],
                   updated_at=after["updated_at"])


@app.route("/api/samples/<int:sid>/report-meta", methods=["PUT"])
@capability_required("report_edit")
def update_report_meta(sid):
    """保存可编辑票面信息；审核人只能由审核动作写入。"""
    d = request.json or {}
    db = get_db()
    before = locked_row(db, "SELECT * FROM samples WHERE id=%s", (sid,))
    if not before:
        return jsonify(ok=False, error="样品不存在"), 404
    if "expected_updated_at" in d and d["expected_updated_at"] != before["updated_at"]:
        db.rollback()
        return jsonify(ok=False, code="version_conflict", error="Sample changed; reload before saving"), 409
    if before["status"] == "cancelled":
        return jsonify(ok=False, error="已作废的样品不能修改票面信息"), 409
    profile_id = d.get("report_profile_id")
    try:
        profile_id = int(profile_id) if profile_id not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify(ok=False, error="报告版式无效"), 400
    if profile_id and not db.execute("SELECT 1 FROM report_profiles WHERE id=%s", (profile_id,)).fetchone():
        return jsonify(ok=False, error="报告版式不存在"), 400
    fields = ("customer", "report_no", "analysis_date", "analyst")
    values = [str(d.get(field, "")).strip() for field in fields]
    db.execute("""UPDATE samples SET customer=%s,report_no=%s,analysis_date=%s,
                  analyst=%s,report_profile_id=%s,updated_at=%s WHERE id=%s""",
               values + [profile_id, next_updated_at(before["updated_at"]), sid])
    after = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    audit_event(db, "report_meta", "sample", sid, before=before, after=after)
    db.commit()
    return jsonify(ok=True, updated_at=after["updated_at"])


@app.route("/api/results", methods=["POST"])
@capability_required("result_edit")
def save_result():
    d = request.json or {}
    db = get_db()
    said = d.get("sample_analyte_id")
    lock_reading_task(db, said)
    task = db.execute("""SELECT sa.*,s.status AS sample_status,s.updated_at AS sample_updated_at,i.itype FROM sample_analytes sa
        JOIN samples s ON s.id=sa.sample_id
        LEFT JOIN instruments i ON i.id=sa.instrument_id WHERE sa.id=%s""", (said,)).fetchone()
    if not task:
        return jsonify(ok=False, error="分析任务不存在"), 404
    if "expected_updated_at" in d and d["expected_updated_at"] != task["sample_updated_at"]:
        db.rollback()
        return jsonify(ok=False, code="version_conflict", error="Sample changed; reload before saving"), 409
    if task["sample_status"] in {"received", "queued"} and task["itype"] != "xrf":
        return jsonify(ok=False, error="请先完成制样并开始测量"), 409
    if task["sample_status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="该样品已锁定，不能修改结果"), 409
    before_task = db.execute("SELECT * FROM sample_analytes WHERE id=%s", (said,)).fetchone()
    before = {"task": dict(before_task), "result": dict(db.execute(
        "SELECT * FROM results WHERE sample_analyte_id=%s", (said,)).fetchone() or {})}
    if "selection" in d:
        db.execute("UPDATE sample_analytes SET selection=%s WHERE id=%s",
                   (d["selection"], said))
    if "instrument_id" in d:            # 换仪器：原数据作废
        db.execute("UPDATE sample_analytes SET instrument_id=%s,method_id=NULL,selection=NULL WHERE id=%s",
                   (d["instrument_id"], said))
        db.execute("DELETE FROM results WHERE sample_analyte_id=%s", (said,))
    if "method_id" in d:
        db.execute("UPDATE sample_analytes SET method_id=%s WHERE id=%s",
                   (d["method_id"], said))
        db.execute("DELETE FROM results WHERE sample_analyte_id=%s", (said,))
    if "raw" in d or "extra" in d:
        return jsonify(ok=False, error="原始值必须通过读数接口保存"), 400
    if "aux" in d:
        existing = db.execute(
            "SELECT aux FROM results WHERE sample_analyte_id=%s", (said,)
        ).fetchone()
        aux = d.get("aux")
        if aux is None and existing:
            aux = json.loads(existing["aux"] or "{}")
        db.execute(
            """INSERT INTO results(sample_analyte_id,aux) VALUES(%s,%s)
               ON CONFLICT(sample_analyte_id) DO UPDATE
               SET aux=excluded.aux""",
            (said, json.dumps(aux or {})))
    recompute_task_progress(db, said)
    updated_at = next_updated_at(task["sample_updated_at"])
    db.execute("UPDATE samples SET updated_at=%s WHERE id=%s", (updated_at, task["sample_id"]))
    after = {"task": dict(db.execute("SELECT * FROM sample_analytes WHERE id=%s", (said,)).fetchone()),
             "result": dict(db.execute("SELECT * FROM results WHERE sample_analyte_id=%s",
                                       (said,)).fetchone() or {})}
    audit_event(db, "result_update", "sample_analyte", said, before=before, after=after)
    db.commit()
    return jsonify(ok=True, updated_at=updated_at)


@app.route("/api/sample-analytes/<int:said>/report-use", methods=["PUT"])
@capability_required("report_edit")
def set_report_use(said):
    """选择同一元素的某条仪器/溶样结果是否参与最终报告汇总。"""
    db = get_db()
    task = db.execute("""SELECT sa.*,s.status AS sample_status FROM sample_analytes sa
        JOIN samples s ON s.id=sa.sample_id WHERE sa.id=%s""", (said,)).fetchone()
    if not task:
        return jsonify(ok=False, error="分析任务不存在"), 404
    if task["sample_status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="已审核或已作废，不能改变结果参与计算状态"), 409
    use = bool((request.json or {}).get("use", True))
    before = dict(task)
    db.execute("UPDATE sample_analytes SET selection=%s WHERE id=%s",
               (None if use else "exclude", said))
    after = db.execute("SELECT * FROM sample_analytes WHERE id=%s", (said,)).fetchone()
    audit_event(db, "report_use", "sample_analyte", said, before=before, after=after)
    db.commit()
    return jsonify(ok=True, use=use)


# ---------------------------------------------------------------- 平行读数

@app.route("/api/readings", methods=["POST"])
@capability_required("result_edit")
def add_reading():
    d = request.json or {}
    try:
        said = int(d["sample_analyte_id"])
        if isinstance(d["sample_analyte_id"], bool) or said <= 0 or str(said) != str(d["sample_analyte_id"]):
            raise ValueError("sample_analyte_id must be a positive integer")
        client_key = d.get("client_reading_id")
        if "client_reading_id" in d:
            if not isinstance(client_key, str) or str(UUID(client_key)) != client_key.lower():
                raise ValueError("client_reading_id must be a UUID string")
            client_key = str(UUID(client_key))
        raw = d.get("raw")
        if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw)):
            raise ValueError("raw must be a finite number or null")
        extra = d.get("extra", {})
        if not isinstance(extra, dict):
            raise ValueError("extra must be an object")
        json.dumps(extra, allow_nan=False)
        payload = {"sample_analyte_id": said, "raw": float(raw) if raw is not None else None,
                   "extra": extra, "use_avg": int(bool(d.get("use_avg", True))),
                   "is_final": int(bool(d.get("is_final", False)))}
        payload_hash = stable_hash(payload)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
    db = get_db()
    if client_key:
        # The unique key reservation and the reading/audit commit together. Keep
        # this record without a cascading FK so deleted readings cannot reappear.
        inserted = db.execute("""INSERT INTO reading_create_requests(client_reading_id,payload_hash)
            VALUES(%s,%s) ON CONFLICT(client_reading_id) DO NOTHING""", (client_key, payload_hash)).rowcount
        saved = locked_row(db, "SELECT * FROM reading_create_requests WHERE client_reading_id=%s", (client_key,))
        if not inserted:
            if saved["payload_hash"] != payload_hash:
                db.rollback()
                return jsonify(ok=False, code="idempotency_conflict", error="Client reading ID already used with different values"), 409
            existing = lock_reading(db, saved["reading_id"])
            if not existing:
                db.rollback()
                return jsonify(ok=False, code="version_conflict", error="The original reading was deleted"), 409
            db.commit()
            # Return the creation version, not a fresh token that could let an
            # old queued draft overwrite edits made after the original create.
            return jsonify(ok=True, id=saved["reading_id"], version=saved["version"], replayed=True)
    lock_reading_task(db, said)
    task = db.execute("""SELECT sa.sample_id,s.status,s.updated_at,i.itype FROM sample_analytes sa
        JOIN samples s ON s.id=sa.sample_id
        LEFT JOIN instruments i ON i.id=sa.instrument_id WHERE sa.id=%s""", (said,)).fetchone()
    if not task:
        return jsonify(ok=False, error="分析任务不存在"), 404
    if task["status"] in {"received", "queued"} and task["itype"] != "xrf":
        return jsonify(ok=False, error="请先完成制样并开始测量"), 409
    if task["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="该样品已锁定，不能增加读数"), 409
    if payload["is_final"]:
        db.execute("UPDATE readings SET is_final=0 WHERE sample_analyte_id=%s", (said,))
    created = db.execute("""INSERT INTO readings(sample_analyte_id,raw,extra,use_avg,is_final)
        VALUES(%s,%s,%s,%s,%s) RETURNING *""",
        (said, payload["raw"], json.dumps(extra, sort_keys=True),
         payload["use_avg"], payload["is_final"])).fetchone()
    reading_id = created["id"]
    version = reading_version(created)
    if client_key:
        db.execute("UPDATE reading_create_requests SET reading_id=%s,version=%s WHERE client_reading_id=%s",
                   (reading_id, version, client_key))
    recompute_task_progress(db, said)
    db.execute("UPDATE samples SET updated_at=%s WHERE id=%s",
               (next_updated_at(task["updated_at"]), task["sample_id"]))
    audit_event(db, "create", "reading", reading_id,
                after=created)
    db.commit()
    return jsonify(ok=True, id=reading_id, version=version, replayed=False)


@app.route("/api/readings/<int:rid>", methods=["PUT"])
@capability_required("result_edit")
def update_reading(rid):
    d = request.json or {}
    db = get_db()
    row = lock_reading(db, rid)
    if "expected_version" in d and (not row or d["expected_version"] != reading_version(row)):
        db.rollback()
        return jsonify(ok=False, code="version_conflict", error="Reading changed or deleted; reload before saving"), 409
    if not row:
        return jsonify(ok=False, error="读数不存在"), 404
    sample = db.execute("""SELECT s.id,s.status,s.updated_at,i.itype FROM samples s JOIN sample_analytes sa
        ON sa.sample_id=s.id LEFT JOIN instruments i ON i.id=sa.instrument_id
        WHERE sa.id=%s""", (row["sample_analyte_id"],)).fetchone()
    if sample["status"] in {"received", "queued"} and sample["itype"] != "xrf":
        return jsonify(ok=False, error="请先完成制样并开始测量"), 409
    if sample["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="该样品已锁定，不能修改读数"), 409
    if d.get("is_final"):     # 同一任务只允许一个终值读数
        db.execute("UPDATE readings SET is_final=0 WHERE sample_analyte_id=%s",
                   (row["sample_analyte_id"],))
    if "raw" in d:
        db.execute("UPDATE readings SET raw=%s WHERE id=%s", (d["raw"], rid))
    if "extra" in d:
        db.execute("UPDATE readings SET extra=%s WHERE id=%s",
                   (json.dumps(d["extra"]), rid))
    if "use_avg" in d:
        db.execute("UPDATE readings SET use_avg=%s WHERE id=%s",
                   (int(bool(d["use_avg"])), rid))
    if "is_final" in d:
        db.execute("UPDATE readings SET is_final=%s WHERE id=%s",
                   (int(bool(d["is_final"])), rid))
    recompute_task_progress(db, row["sample_analyte_id"])
    db.execute("UPDATE samples SET updated_at=%s WHERE id=%s",
               (next_updated_at(sample["updated_at"]), sample["id"]))
    after = db.execute("SELECT * FROM readings WHERE id=%s", (rid,)).fetchone()
    version = reading_version(after)
    audit_event(db, "update", "reading", rid, before=row, after=after)
    db.commit()
    return jsonify(ok=True, id=rid, version=version)


@app.route("/api/readings/<int:rid>", methods=["DELETE"])
@capability_required("result_edit")
def del_reading(rid):
    d = (request.get_json() if request.is_json else {}) or {}
    db = get_db()
    before = lock_reading(db, rid)
    if "expected_version" in d and (not before or d["expected_version"] != reading_version(before)):
        db.rollback()
        return jsonify(ok=False, code="version_conflict", error="Reading changed or deleted; reload before deleting"), 409
    if not before:
        return jsonify(ok=False, error="读数不存在"), 404
    sample = db.execute("""SELECT s.id,s.status,s.updated_at,i.itype FROM samples s JOIN sample_analytes sa
        ON sa.sample_id=s.id LEFT JOIN instruments i ON i.id=sa.instrument_id
        WHERE sa.id=%s""", (before["sample_analyte_id"],)).fetchone()
    if sample["status"] in {"received", "queued"} and sample["itype"] != "xrf":
        return jsonify(ok=False, error="请先完成制样并开始测量"), 409
    if sample["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="该样品已锁定，不能删除读数"), 409
    db.execute("DELETE FROM readings WHERE id=%s", (rid,))
    recompute_task_progress(db, before["sample_analyte_id"])
    db.execute("UPDATE samples SET updated_at=%s WHERE id=%s",
               (next_updated_at(sample["updated_at"]), sample["id"]))
    audit_event(db, "delete", "reading", rid, before=before)
    db.commit()
    return jsonify(ok=True)

# ---------------------------------------------------------------- 标准数值仪器客户端

_STANDARD_INPUT_UNITS = {
    "ppm": "mg/L", "ppb": "μg/L", "mol": "mol/L", "percent": "%", "ph": "pH",
}
_STANDARD_SESSION_SECONDS = 10 * 60


def _standard_session_user(db, capability="result_edit"):
    if app.config.get("AUTH_DISABLED"):
        return g.user
    token = request.headers.get("X-User-Authorization", "").strip()
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = db.execute("""SELECT scs.token_hash,scs.last_activity,
            u.id,u.username,u.display_name,u.permissions,u.active
        FROM standard_client_sessions scs JOIN users u ON u.id=scs.user_id
        WHERE scs.token_hash=%s AND u.active=1""", (token_hash,)).fetchone()
    now = datetime.now().timestamp()
    if not row or now - float(row["last_activity"]) > _STANDARD_SESSION_SECONDS:
        if row:
            db.execute("DELETE FROM standard_client_sessions WHERE token_hash=%s", (token_hash,))
            db.commit()
        return None
    return row if capability in user_permissions(row) else None


def _standard_authorization_error():
    return jsonify(ok=False, code="user_authorization_required",
                   error="用户登录已失效，请重新输入具备数据录入权限的用户密码"), 401


def _touch_standard_session(db):
    if app.config.get("AUTH_DISABLED"):
        return
    token = request.headers.get("X-User-Authorization", "").strip()
    if token:
        db.execute("UPDATE standard_client_sessions SET last_activity=%s WHERE token_hash=%s",
                   (datetime.now().timestamp(), hashlib.sha256(token.encode("utf-8")).hexdigest()))


@app.post("/api/instrument/standard/authorize")
@standard_client_required
def standard_client_authorize():
    data = request.json or {}
    password = str(data.get("password") or "")
    client_id = str(data.get("client_id") or "标准仪器终端").strip()[:120]
    db = get_db()
    user, error = authenticate_capable_user(db, password, "result_edit")
    if not user:
        return jsonify(ok=False, error=error), 401 if "密码" in str(error) else 403
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    db.execute("DELETE FROM standard_client_sessions WHERE client_id=%s AND user_id=%s",
               (client_id, user["id"]))
    db.execute("""INSERT INTO standard_client_sessions(token_hash,user_id,client_id,last_activity)
        VALUES(%s,%s,%s,%s)""", (token_hash, user["id"], client_id, datetime.now().timestamp()))
    audit_event(db, "instrument_login", "session", client_id,
                after={"client_id": client_id}, user=user)
    db.commit()
    return jsonify(ok=True, token=token, expires_in=_STANDARD_SESSION_SECONDS,
                   user={"id": user["id"], "username": user["username"],
                         "display_name": user["display_name"]})


@app.post("/api/instrument/standard/session/touch")
@standard_client_required
def standard_client_session_touch():
    db = get_db()
    user = _standard_session_user(db)
    if not user:
        return _standard_authorization_error()
    _touch_standard_session(db)
    db.commit()
    return jsonify(ok=True, expires_in=_STANDARD_SESSION_SECONDS)


@app.post("/api/instrument/standard/logout")
@standard_client_required
def standard_client_logout():
    db = get_db()
    token = request.headers.get("X-User-Authorization", "").strip()
    if token:
        db.execute("DELETE FROM standard_client_sessions WHERE token_hash=%s",
                   (hashlib.sha256(token.encode("utf-8")).hexdigest(),))
        db.commit()
    return jsonify(ok=True)


@app.get("/api/instrument/standard/instruments")
@standard_client_required
def standard_client_instruments():
    instruments = rows("""SELECT id,name,itype,sort_order FROM instruments
        WHERE itype IN ('ppm','ppb','mol','percent','ph') ORDER BY sort_order,id""")
    for instrument in instruments:
        instrument["input_unit"] = _STANDARD_INPUT_UNITS[instrument["itype"]]
    return jsonify(ok=True, instruments=instruments,
                   server_time=datetime.now().isoformat(timespec="seconds"))


@app.post("/api/instrument/standard/status")
@standard_client_required
def standard_client_status():
    data = request.json or {}
    client_id = str(data.get("client_id") or data.get("machine_name") or "").strip()[:120]
    machine_name = str(data.get("machine_name") or client_id).strip()[:120]
    try:
        instrument_id = int(data.get("instrument_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="缺少仪器编号"), 400
    if not client_id:
        return jsonify(ok=False, error="缺少终端标识"), 400
    db = get_db()
    if not db.execute("""SELECT 1 FROM instruments WHERE id=%s
            AND itype IN ('ppm','ppb','mol','percent','ph')""", (instrument_id,)).fetchone():
        return jsonify(ok=False, error="仪器不存在或不支持标准单值录入"), 404
    user = _standard_session_user(db)
    db.execute("""INSERT INTO standard_client_status(
        client_id,machine_name,client_version,instrument_id,network_position,user_id,seen_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'))
        ON CONFLICT(client_id) DO UPDATE SET
          machine_name=excluded.machine_name,client_version=excluded.client_version,
          instrument_id=excluded.instrument_id,network_position=excluded.network_position,
          user_id=excluded.user_id,seen_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
          updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')""", (
        client_id, machine_name, str(data.get("version") or "").strip()[:40], instrument_id,
        request.remote_addr or "", user["id"] if user else None))
    db.commit()
    return jsonify(ok=True, server_time=datetime.now().isoformat(timespec="seconds"))


@app.get("/api/instrument/standard/tasks")
@standard_client_required
def standard_client_tasks():
    try:
        instrument_id = int(request.args.get("instrument_id", ""))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="请选择标准数值仪器"), 400
    db = get_db()
    if not _standard_session_user(db):
        return _standard_authorization_error()
    instrument = db.execute("""SELECT id,name,itype FROM instruments WHERE id=%s
        AND itype IN ('ppm','ppb','mol','percent','ph')""", (instrument_id,)).fetchone()
    if not instrument:
        return jsonify(ok=False, error="仪器不存在或不支持单值录入"), 404
    task_rows = db.execute("""SELECT sa.id AS task_id,sa.status AS task_status,
            s.id AS sample_id,s.lims_no,s.name AS sample_name,s.category,
            s.status AS sample_status,s.is_liquid,a.name AS analyte,
            p.name AS prep_name,p.mass_g,p.volume_ml,p.dilution_label
        FROM sample_analytes sa JOIN samples s ON s.id=sa.sample_id
        JOIN analytes a ON a.id=sa.analyte_id
        LEFT JOIN preparations p ON p.id=sa.preparation_id
        WHERE sa.instrument_id=%s AND sa.status!='cancelled'
          AND s.status IN ('queued','measuring','partially_done','completed')
        ORDER BY s.id,a.sort_order,a.id,p.id,sa.id""", (instrument_id,)).fetchall()
    task_ids = [row["task_id"] for row in task_rows]
    reading_map = {}
    if task_ids:
        placeholders = ",".join("%s" for _ in task_ids)
        for reading in db.execute(f"""SELECT id,sample_analyte_id,raw,use_avg,is_final
            FROM readings WHERE sample_analyte_id IN ({placeholders}) ORDER BY id""", task_ids):
            item = dict(reading)
            item["use_avg"] = bool(item["use_avg"])
            item["is_final"] = bool(item["is_final"])
            reading_map.setdefault(reading["sample_analyte_id"], []).append(item)
    samples = []
    by_sample = {}
    for task_row in task_rows:
        sid = task_row["sample_id"]
        sample = by_sample.get(sid)
        if not sample:
            sample = {
                "sample_id": sid, "lims_no": task_row["lims_no"],
                "sample_name": task_row["sample_name"], "category": task_row["category"],
                "sample_status": task_row["sample_status"], "tasks": [],
            }
            by_sample[sid] = sample
            samples.append(sample)
        sample["tasks"].append({
            "task_id": task_row["task_id"], "task_status": task_row["task_status"],
            "analyte": task_row["analyte"], "prep_name": task_row["prep_name"] or "原样",
            "mass_g": task_row["mass_g"], "volume_ml": task_row["volume_ml"],
            "dilution_label": task_row["dilution_label"] or "原样",
            "input_unit": _STANDARD_INPUT_UNITS[instrument["itype"]],
            "readings": reading_map.get(task_row["task_id"], []),
        })
    return jsonify(ok=True, instrument=dict(instrument), samples=samples,
                   server_time=datetime.now().isoformat(timespec="seconds"))


@app.post("/api/instrument/standard/samples/<int:sid>/start")
@standard_client_required
def standard_client_start_sample(sid):
    data = request.json or {}
    try:
        instrument_id = int(data.get("instrument_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="缺少仪器编号"), 400
    db = get_db()
    user = _standard_session_user(db)
    if not user:
        return _standard_authorization_error()
    before = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not before:
        return jsonify(ok=False, error="样品不存在"), 404
    if before["status"] != "queued":
        return jsonify(ok=False, error="只有未测量样品可以开始测量"), 409
    if not db.execute("""SELECT 1 FROM sample_analytes WHERE sample_id=%s
            AND instrument_id=%s AND status!='cancelled' LIMIT 1""", (sid, instrument_id)).fetchone():
        return jsonify(ok=False, error="该样品没有分配给当前仪器的任务"), 409
    actor = user["display_name"] or user["username"]
    db.execute("""UPDATE samples SET status='measuring',
        analyst=CASE WHEN COALESCE(analyst,'')='' THEN %s ELSE analyst END,
        status_operator=%s,status_action='measuring',status_changed_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
        updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
        (actor, actor, sid))
    after = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    audit_event(db, "status_change", "sample", sid, before=before, after=after, user=user)
    _touch_standard_session(db)
    db.commit()
    return jsonify(ok=True, status="measuring", analyst=after["analyst"])


@app.post("/api/instrument/standard/submit")
@standard_client_required
def standard_client_submit():
    data = request.json or {}
    client_id = str(data.get("client_id") or "标准仪器终端").strip()[:120]
    submission_id = str(data.get("submission_id") or "").strip()[:120]
    try:
        instrument_id = int(data.get("instrument_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="缺少仪器编号"), 400
    submitted = data.get("readings")
    if not submission_id or not isinstance(submitted, list) or not 1 <= len(submitted) <= 500:
        return jsonify(ok=False, error="提交号不能为空，且每批应包含 1 至 500 条读数"), 400
    db = get_db()
    user = _standard_session_user(db)
    if not user:
        return _standard_authorization_error()
    previous = db.execute("""SELECT response_json FROM standard_client_submissions
        WHERE client_id=%s AND submission_id=%s""", (client_id, submission_id)).fetchone()
    if previous:
        response = json.loads(previous["response_json"] or "{}")
        response["duplicate"] = True
        return jsonify(response)
    instrument = db.execute("""SELECT id,name,itype FROM instruments WHERE id=%s
        AND itype IN ('ppm','ppb','mol','percent','ph')""", (instrument_id,)).fetchone()
    if not instrument:
        return jsonify(ok=False, error="仪器不存在或不支持单值录入"), 404
    clean = []
    seen_tasks = set()
    for index, item in enumerate(submitted, 1):
        if not isinstance(item, dict):
            return jsonify(ok=False, error=f"第 {index} 条读数格式不正确"), 400
        try:
            task_id = int(item.get("task_id"))
            value = float(item.get("value"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error=f"第 {index} 条读数不是有效数字"), 400
        if not math.isfinite(value):
            return jsonify(ok=False, error=f"第 {index} 条读数不是有限数字"), 400
        if task_id in seen_tasks:
            return jsonify(ok=False, error=f"任务 {task_id} 在同一批中重复"), 400
        seen_tasks.add(task_id)
        task = db.execute("""SELECT sa.id,sa.sample_id,sa.instrument_id,sa.status,
                s.status AS sample_status,a.name AS analyte
            FROM sample_analytes sa JOIN samples s ON s.id=sa.sample_id
            JOIN analytes a ON a.id=sa.analyte_id WHERE sa.id=%s""", (task_id,)).fetchone()
        if not task or task["instrument_id"] != instrument_id:
            return jsonify(ok=False, error=f"任务 {task_id} 不属于当前仪器"), 409
        if task["status"] == "cancelled" or task["sample_status"] not in {
                "measuring", "partially_done", "completed"}:
            return jsonify(ok=False, error=f"{task['analyte']} 所在样品当前不能录入"), 409
        clean.append((task, value))
    actor = user
    imported = []
    sample_ids = set()
    for task, value in clean:
        reading = db.execute("""INSERT INTO readings(sample_analyte_id,raw,extra,use_avg,is_final)
            VALUES(%s,%s,'{}',1,0) RETURNING *""", (task["id"], value)).fetchone()
        audit_event(db, "instrument_reading", "reading", reading["id"],
                    after=reading, user=actor)
        recompute_task_progress(db, task["id"])
        sample_ids.add(task["sample_id"])
        imported.append({"task_id": task["id"], "reading_id": reading["id"],
                         "analyte": task["analyte"], "value": value})
    for sample_id in sample_ids:
        recompute_sample_progress(db, sample_id)
    response = {"ok": True, "duplicate": False, "submission_id": submission_id,
                "imported": imported}
    db.execute("""INSERT INTO standard_client_submissions(
        client_id,submission_id,instrument_id,payload_json,response_json)
        VALUES(%s,%s,%s,%s,%s)""", (client_id, submission_id, instrument_id,
        json.dumps(data, ensure_ascii=False), json.dumps(response, ensure_ascii=False)))
    audit_event(db, "instrument_submit", "standard_submission", submission_id,
                after={"instrument": instrument["name"], "client_id": client_id,
                       "count": len(imported)}, user=actor)
    _touch_standard_session(db)
    db.commit()
    return jsonify(response)


# ---------------------------------------------------------------- XRF 仪器客户端（第一阶段）

@app.route("/api/instrument/xrf/tasks")
@xrf_client_required
def xrf_client_tasks():
    """XRF 是样品级整包测量：只下发方法，不按元素拆任务。"""
    samples = rows("""SELECT s.id AS sample_id,s.lims_no,s.name AS sample_name,
            s.category,s.status AS sample_status,s.xrf_report_items,
            m.id AS method_id,m.name AS method_name
        FROM samples s LEFT JOIN methods m ON m.id=s.xrf_method_id
        WHERE s.xrf=1 AND s.status NOT IN ('reviewed','cancelled')
          AND NOT EXISTS(SELECT 1 FROM xrf_analyses xa WHERE xa.sample_id=s.id)
        ORDER BY s.id""")
    for sample in samples:
        sample["copy_name"] = sample["lims_no"] or sample["sample_name"]
        sample["method_name"] = sample["method_name"] or ""
        sample["tasks"] = []  # 保留字段以兼容第一版客户端
    return jsonify(ok=True, samples=samples, server_time=datetime.now().isoformat())


@app.route("/api/instrument/xrf/status", methods=["POST"])
@xrf_client_required
def xrf_client_status():
    """接收 XRF 终端心跳；页面据此显示当前样品、方法和批次。"""
    d = request.json or {}
    machine = str(d.get("machine_name") or d.get("client_id") or "XRF终端").strip()
    if not machine:
        return jsonify(ok=False, error="缺少终端标识"), 400
    state = str(d.get("state", "idle")).strip().lower() or "idle"
    if state not in {"idle", "reading", "uploading", "error"}:
        state = "idle"
    current = d.get("current") if isinstance(d.get("current"), dict) else {}
    db = get_db()
    before = db.execute("SELECT * FROM xrf_client_status WHERE client_id=%s", (machine,)).fetchone()
    db.execute("""INSERT INTO xrf_client_status(
        client_id,machine_name,client_version,state,current_sample,current_method,
        current_batch,current_run_id,current_position,current_started_at,
        message,seen_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'))
        ON CONFLICT(client_id) DO UPDATE SET
          machine_name=excluded.machine_name, client_version=excluded.client_version,
          state=excluded.state, current_sample=excluded.current_sample,
          current_method=excluded.current_method, current_batch=excluded.current_batch,
          current_run_id=excluded.current_run_id,
          current_position=excluded.current_position,
          current_started_at=excluded.current_started_at,
          message=excluded.message, seen_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
          updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')""", (
        machine, machine, str(d.get("version", "")).strip(), state,
        str(current.get("sample") or current.get("sample_name") or "").strip(),
        str(current.get("method") or current.get("method_name") or "").strip(),
        str(current.get("batch") or current.get("batch_name") or "").strip(),
        str(current.get("run_id") or "").strip(),
        str(current.get("position") or "").strip(),
        str(current.get("started_at") or "").strip(),
        str(d.get("message", "")).strip()[:500]))
    after = db.execute("SELECT * FROM xrf_client_status WHERE client_id=%s", (machine,)).fetchone()
    watch = ("state", "current_sample", "current_method", "current_batch",
             "current_run_id", "current_position", "current_started_at", "message")
    if before is None or any(before[k] != after[k] for k in watch):
        audit_event(db, "heartbeat", "instrument_client", machine,
                    before={k: before[k] for k in watch} if before else None,
                    after={k: after[k] for k in watch})
    db.commit()
    return jsonify(ok=True, server_time=datetime.now().isoformat())


def _uq_sample_name(value):
    """Remove the OXSAS repeat suffix while retaining the received name."""
    return re.sub(r"\s*-\s*(?:\(\s*\d+\s*\))?\s*$", "", str(value or "").strip()).strip()


def _uq_processed(film):
    normalized = str(film or "").strip().casefold().replace("μ", "µ")
    return bool(re.fullmatch(r"pp\s*4\s*(?:mu|um|µm)", normalized))


def _uq_bool(value):
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value)


def _uq_number(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _uq_options_remark(options, job):
    """Turn the operator-controlled UniQuant settings into a readable LIMS remark."""
    chemistry = options.get("chemistry")
    atmosphere = options.get("atmosphere")
    values = [
        ("化学", "氧化物" if chemistry == 1 else "元素" if chemistry == 0 else chemistry),
        ("Shape", options.get("shape")),
        ("Case", options.get("case_nb", options.get("case_number"))),
        ("Kappa", options.get("kappas", options.get("kappa_list"))),
        ("气氛", "真空" if atmosphere == 0 else atmosphere),
        ("报告限(ppm)", options.get("report_level")),
        ("直径", options.get("diameter")),
        ("质量", options.get("mass")),
        ("密度", options.get("rho")),
        ("高度", options.get("height")),
        ("扣除氧", job.get("stripped_oxygen")),
    ]
    generated = "；".join(f"{label}: {value}" for label, value in values
                           if value not in (None, ""))
    source_remark = str(options.get("remark") or "").strip()
    return "；".join(part for part in (source_remark, generated) if part)


def _xrf_reference(db):
    """元素与氧化物参考数据：换算一律取自 common_oxides，不在业务代码写死系数。"""
    elements = {row["symbol"].casefold(): row["symbol"]
                for row in db.execute("SELECT symbol FROM chemical_elements")}
    oxides = {}
    for row in db.execute("""SELECT formula,element_symbol,element_to_oxide_factor
        FROM common_oxides"""):
        oxides[row["formula"].casefold()] = {
            "formula": row["formula"], "element": row["element_symbol"],
            "factor": float(row["element_to_oxide_factor"])}
    return elements, oxides


def _xrf_target_family(token, elements, oxides):
    """把项目名解析为 (元素族, 目标口径)；未知项目按自定义原样保留。"""
    key = str(token).strip().casefold()
    if key in oxides:
        return oxides[key]["element"].casefold(), oxides[key]["formula"]
    if key in elements:
        return key, elements[key]
    return None, None


def _derive_xrf_targets(text, elements, oxides):
    """把逗号分隔的报告项目文本解析为按元素族单选的结构化口径。

    同一族出现多个口径（如 Fe 与 Fe2O3）时，以先出现的项目为准。
    """
    targets, seen = [], set()
    for part in re.split(r"[,，、;；\s]+", text or ""):
        part = part.strip()
        if not part:
            continue
        family, target = _xrf_target_family(part, elements, oxides)
        allow = 1
        if family is None:
            family, target, allow = part.casefold(), part, 0
        if family in seen:
            continue
        seen.add(family)
        targets.append({"family": family, "target": target,
                        "include": 1, "allow_conversion": allow})
    return targets


def _load_xrf_targets(db, sid):
    return [dict(row) for row in db.execute(
        """SELECT id,family,target,include,allow_conversion FROM xrf_report_targets
        WHERE sample_id=%s ORDER BY id""", (sid,))]


def _sync_sample_xrf_targets(db, sid, text):
    elements, oxides = _xrf_reference(db)
    targets = _derive_xrf_targets(text, elements, oxides)
    db.execute("DELETE FROM xrf_report_targets WHERE sample_id=%s", (sid,))
    for target in targets:
        db.execute("""INSERT INTO xrf_report_targets(sample_id,family,target,include,allow_conversion)
            VALUES(%s,%s,%s,%s,%s)""", (sid, target["family"], target["target"],
                                   target["include"], target["allow_conversion"]))
    return targets


def _element_to_target_factor(source, target, oxides):
    """元素↔氧化物换算系数与说明；无关系时返回 (None, '')。"""
    skey, tkey = str(source).casefold(), str(target).casefold()
    if tkey in oxides and oxides[tkey]["element"].casefold() == skey:
        return oxides[tkey]["factor"], f"{source} × {oxides[tkey]['factor']:.4g}"
    if skey in oxides and oxides[skey]["element"].casefold() == tkey:
        factor = 1.0 / oxides[skey]["factor"]
        return factor, f"{source} ÷ {oxides[skey]['factor']:.4g}"
    return None, ""


def _resolve_xrf_report_rows(targets, xrf_rows, reference, warnings, analyte_index):
    """按报告目标解析 XRF 最终组成：直取优先，缺项才按化学计量换算。

    返回报告行列表；换算来源与系数写入 xrf_resolution，全程可追溯。
    """
    elements, oxides = reference
    rows_out = []
    for target in targets:
        if not target["include"]:
            continue
        target_name = str(target["target"])
        tkey = target_name.casefold()
        famkey = str(target["family"]).casefold()
        family_rows = []
        for xr in xrf_rows:
            names = {str(xr["analyte"]).casefold()}
            if xr.get("alt_name"):
                names.add(str(xr["alt_name"]).casefold())
            oxide = oxides.get(str(xr["analyte"]).casefold())
            member = oxide["element"].casefold() if oxide else (
                str(xr["analyte"]).casefold() if str(xr["analyte"]).casefold() in elements else None)
            if tkey in names or member == famkey:
                family_rows.append(xr)
        # 一致性核对：同族独立存在元素与氧化物直出值时只读比对，超差仅警告。
        element_rows = [xr for xr in family_rows
                        if str(xr["analyte"]).casefold() in elements]
        oxide_rows = [xr for xr in family_rows
                      if str(xr["analyte"]).casefold() in oxides]
        for element_row in element_rows:
            for oxide_row in oxide_rows:
                factor, _ = _element_to_target_factor(
                    element_row["analyte"], oxide_row["analyte"], oxides)
                if factor is None:
                    continue
                expected = float(element_row["value"]) * factor
                oxide_value = float(oxide_row["value"])
                deviation = abs(oxide_value - expected) / max(abs(oxide_value), 1e-9)
                if deviation > 0.01:
                    warnings.append({
                        "family": target["family"], "code": "composition_mismatch",
                        "message": (f"{target['family']}: {oxide_row['analyte']} 直出 "
                                    f"{oxide_value:.5g}% 与 {element_row['analyte']} 换算 "
                                    f"{expected:.5g}% 相对偏差 {deviation:.1%}，请核对"),
                    })
        direct = next((xr for xr in family_rows
                       if str(xr["analyte"]).casefold() == tkey), None)
        chosen, factor, source_name, note = None, None, "", "直出"
        if direct is not None:
            chosen = direct
        elif target["allow_conversion"]:
            for xr in family_rows:
                if not xr.get("alt_name") or str(xr["alt_name"]).casefold() != tkey:
                    continue
                pair_factor, pair_note = _element_to_target_factor(
                    xr["analyte"], target_name, oxides)
                if pair_factor is not None:
                    chosen, factor, source_name, note = xr, pair_factor, xr["analyte"], pair_note
                    break
            if chosen is None and tkey in oxides:
                oxide = oxides[tkey]
                source = next((xr for xr in family_rows if str(xr["analyte"]).casefold()
                               == oxide["element"].casefold()), None)
                if source is not None:
                    factor = oxide["factor"]
                    chosen, source_name = source, source["analyte"]
                    note = f"{source['analyte']} × {factor:.4g}"
            if chosen is None and tkey in elements:
                candidates = {}
                for xr in oxide_rows:
                    oxide = oxides[str(xr["analyte"]).casefold()]
                    candidates.setdefault(oxide["formula"], xr)
                if len(candidates) == 1:
                    formula, source = next(iter(candidates.items()))
                    factor = 1.0 / oxides[formula.casefold()]["factor"]
                    chosen, source_name = source, source["analyte"]
                    note = f"{source['analyte']} ÷ {oxides[formula.casefold()]['factor']:.4g}"
                elif len(candidates) > 1:
                    warnings.append({
                        "family": target["family"], "code": "ambiguous_oxide",
                        "message": (f"{target['family']} 存在多个氧化物口径"
                                    f"（{'、'.join(sorted(candidates))}），请明确换算来源"),
                    })
        if chosen is None:
            if family_rows and not any(
                    warning.get("family") == target["family"]
                    for warning in warnings):
                warnings.append({
                    "family": target["family"], "code": "missing_target",
                    "message": f"缺少目标口径 {target_name}，该结果未列入报告",
                })
            continue
        raw = float(chosen["value"]) * (factor if factor is not None else 1.0)
        value = float(f"{raw:.5g}")
        analyte_id, sort_order = analyte_index.get(tkey, (None, None))
        rows_out.append({
            "sample_analyte_id": None, "xrf_value_id": chosen["xrf_value_id"],
            "analyte_id": analyte_id, "analyte": target_name,
            "analyte_sort_order": sort_order if sort_order is not None else 999999,
            "prep": "原样", "mass_g": None, "volume_ml": None, "dilution": "原样",
            "instrument": "XRF", "instrument_sort_order": -1,
            "method": chosen["method"] or "",
            "readings": [{"raw": value, "extra": {}, "used": True,
                          "value": value, "corrected_value": value}],
            "aux": {}, "value": value, "unit": "%", "selection": None,
            "analyzed_at": chosen["analyzed_at"], "external_id": chosen["external_id"],
            "xrf_resolution": {
                "via": "direct" if factor is None else "converted",
                "source": source_name or target_name,
                "factor": factor, "note": note,
            },
        })
    return rows_out


def _store_xrf_scan(db, data, *, source, kind, external_id, sample_name):
    results_in = data.get("results") or []
    if not isinstance(results_in, list) or not results_in:
        return {"ok": False, "error": "没有可导入的定量结果"}, 400
    options_in = data.get("options") if isinstance(data.get("options"), dict) else {}
    oxide_mode = options_in.get("chemistry") in {1, "1", "oxide", "氧化物"}
    clean_results, skipped = {}, {}
    for result in results_in:
        if not isinstance(result, dict):
            continue
        name = str(result.get("name") or "").strip()
        element_name = str(result.get("element_name") or "").strip()
        oxide_name = str(result.get("oxide_name") or "").strip()
        if not name:
            name = oxide_name if (kind == "uq" and oxide_mode and oxide_name) else element_name
        if not name or name.startswith("Bg"):
            skipped[name] = {"name": name, "reason": "背景项不导入"}
            continue
        try:
            value = float(result.get("value"))
        except (TypeError, ValueError):
            skipped[name] = {"name": name, "reason": "非数字"}
            continue
        if not math.isfinite(value):
            skipped[name] = {"name": name, "reason": "数值无效"}
            continue
        # UniQuant 名称对：保留当前口径的另一侧，报告换算时不需要再读 OXSAS。
        if element_name and element_name.casefold() == name.casefold():
            alt_name = oxide_name if oxide_name.casefold() != name.casefold() else ""
        elif oxide_name and oxide_name.casefold() == name.casefold():
            alt_name = element_name
        else:
            alt_name = ""
        clean_results[name] = (float(f"{value:.5g}"), alt_name)
    if not clean_results:
        return {"ok": False, "error": "分析中没有有效的定量结果", "skipped": list(skipped.values())}, 422

    existing = db.execute("SELECT * FROM xrf_analyses WHERE source=%s AND external_id=%s",
                          (source, external_id)).fetchone()
    if existing and existing["sample_id"]:
        existing_sample = db.execute("SELECT status FROM samples WHERE id=%s",
                                     (existing["sample_id"],)).fetchone()
        if existing_sample and existing_sample["status"] in {"reviewed", "cancelled"}:
            return {"ok": True, "duplicate": True, "analysis_id": existing["id"],
                    "matched": True, "sample_id": existing["sample_id"],
                    "sample_locked": True, "imported": [],
                    "skipped": list(skipped.values())}, 200
    linked_sample = db.execute("SELECT * FROM samples WHERE id=%s", (existing["sample_id"],)).fetchone() \
        if existing and existing["sample_id"] else None
    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    job = data.get("job") if isinstance(data.get("job"), dict) else {}
    remark = _uq_options_remark(options, job) if kind == "uq" else str(data.get("remark") or "").strip()
    old_sample_id = existing["sample_id"] if existing else None
    defaults = {part.strip().casefold() for part in re.split(
        r"[,，、;；\s]+", linked_sample["xrf_report_items"] or "") if part.strip()} if linked_sample else set()
    if linked_sample:
        defaults |= {target["target"].casefold() for target in
                     _load_xrf_targets(db, linked_sample["id"]) if target["include"]}
    # 幂等去重：OXSAS 客户端会反复上传同一份扫描，内容完全一致时直接确认返回，
    # 不重写 xrf_values、不写审计、不打掉报告缓存。否则重导会清空网页端 use_report 勾选。
    if existing and str(existing["kind"] or "") == str(kind or ""):
        current_values = {
            row["name"]: (row["value"], row["alt_name"] or "", int(bool(row["use_report"])))
            for row in db.execute("SELECT name,value,alt_name,use_report FROM xrf_values WHERE analysis_id=%s",
                                  (existing["id"],))
        }
        incoming_values = {
            name: (value, alt_name, int(name.casefold() in defaults))
            for name, (value, alt_name) in clean_results.items()
        }
        if current_values == incoming_values:
            return {"ok": True, "duplicate": True, "analysis_id": existing["id"],
                    "matched": linked_sample is not None,
                    "sample_id": linked_sample["id"] if linked_sample else None,
                    "sample_locked": False, "manual_assignment_required": linked_sample is None,
                    "imported": [], "skipped": list(skipped.values())}, 200
    db.execute("""INSERT INTO xrf_analyses(
        sample_id,sample_name,external_id,method,batch,analyzed_at,source,kind,remark,options_json)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source,external_id) DO UPDATE SET
          sample_name=excluded.sample_name,method=excluded.method,batch=excluded.batch,
          analyzed_at=excluded.analyzed_at,kind=excluded.kind,
          remark=excluded.remark,options_json=excluded.options_json""", (
        None, str(data.get("raw_sample_name") or sample_name).strip(),
        external_id, str(data.get("method") or "").strip(), str(data.get("batch") or "").strip(),
        data.get("analyzed_at"), source, kind, remark, json.dumps(options, ensure_ascii=False)))
    analysis = db.execute("SELECT * FROM xrf_analyses WHERE source=%s AND external_id=%s",
                          (source, external_id)).fetchone()
    db.execute("DELETE FROM xrf_values WHERE analysis_id=%s", (analysis["id"],))
    imported = []
    for name, (value, alt_name) in clean_results.items():
        value_id = db.execute("""INSERT INTO xrf_values(analysis_id,name,value,use_report,alt_name)
            VALUES(%s,%s,%s,%s,%s) RETURNING id""", (analysis["id"], name, value,
                                   int(name.casefold() in defaults), alt_name)).fetchone()["id"]
        imported.append({"name": name, "value": value, "alt_name": alt_name,
                         "xrf_value_id": value_id})
    for affected in {old_sample_id, linked_sample["id"] if linked_sample else None} - {None}:
        recompute_sample_progress(db, affected)
        _report_cache_note_write()
    audit_event(db, "instrument_import", "xrf_analysis", analysis["id"], after={
        "source": source, "external_id": external_id,
        "sample_id": linked_sample["id"] if linked_sample else None,
        "result_count": len(imported), "duplicate": existing is not None,
    })
    return {"ok": True, "duplicate": existing is not None, "analysis_id": analysis["id"],
            "matched": linked_sample is not None, "sample_id": linked_sample["id"] if linked_sample else None,
            "sample_locked": False, "manual_assignment_required": linked_sample is None,
            "imported": imported, "skipped": list(skipped.values())}, 200


def _ordinary_scan_payload(data):
    external_id = str(data.get("analysis_id") or "").strip()
    if not external_id:
        return None, {"ok": False, "error": "缺少 OXSAS analysis_id"}, 400
    method = str(data.get("method") or "").strip()
    if re.match(r"^X[_ ]?UQ", method, re.IGNORECASE):
        return None, {"ok": False, "error": "UniQuant 必须使用 UQ 导入接口"}, 400
    sample_name = str(data.get("oxsas_sample_name") or "").strip()
    return ("OXSAS", "quant", external_id, sample_name), None, None


@app.route("/api/instrument/xrf/import", methods=["POST"])
@xrf_client_required
def xrf_client_import():
    """Store every OXSAS quantitative scan without automatically assigning a LIMS sample."""
    data = request.json or {}
    scan, error, status = _ordinary_scan_payload(data)
    if error:
        return jsonify(error), status
    body, status = _store_xrf_scan(get_db(), data, source=scan[0], kind=scan[1],
                                   external_id=scan[2], sample_name=scan[3])
    if body["ok"]:
        get_db().commit()
    return jsonify(body), status


@app.route("/api/instrument/xrf/import/batch", methods=["POST"])
@xrf_client_required
def xrf_client_import_batch():
    submitted = (request.json or {}).get("analyses")
    if not isinstance(submitted, list) or not 1 <= len(submitted) <= 250:
        return jsonify(ok=False, error="每批应包含 1 至 250 条定量分析"), 400
    db, responses = get_db(), []
    for data in submitted:
        if not isinstance(data, dict):
            responses.append({"ok": False, "error": "分析格式无效"})
            continue
        scan, error, _ = _ordinary_scan_payload(data)
        if error:
            responses.append(error)
            continue
        body, _ = _store_xrf_scan(db, data, source=scan[0], kind=scan[1],
                                  external_id=scan[2], sample_name=scan[3])
        responses.append(body)
    db.commit()
    return jsonify(ok=True, results=responses,
                   imported=sum(1 for item in responses if item.get("ok")))


@app.route("/api/instrument/xrf/uq/import", methods=["POST"])
@xrf_client_required
def xrf_uq_import():
    """Store only manually finalized UniQuant composition values, never spectrum channels."""
    d = request.json or {}
    general_id = str(d.get("general_id") or "").strip()
    job_id = str(d.get("job_id") or "").strip()
    if not general_id or not job_id:
        return jsonify(ok=False, error="缺少 UniQuant general_id 或 job_id"), 400
    processed = _uq_bool(d.get("processed")) or _uq_processed(d.get("film"))
    if not processed:
        return jsonify(ok=True, skipped=True, processed=False, imported=[])
    original_name = str(d.get("sample_name") or "").strip()
    normalized_name = _uq_sample_name(original_name)
    d["raw_sample_name"] = original_name
    body, status = _store_xrf_scan(get_db(), d, source="OXSAS-UniQuant", kind="uq",
                                   external_id=f"{general_id}:{job_id}", sample_name=normalized_name)
    body.update(processed=True, normalized_sample_name=normalized_name)
    if body["ok"]:
        get_db().commit()
    return jsonify(body), status


@app.route("/api/instrument/xrf/uq/import/batch", methods=["POST"])
@xrf_client_required
def xrf_uq_import_batch():
    submitted = (request.json or {}).get("analyses")
    if not isinstance(submitted, list) or not 1 <= len(submitted) <= 250:
        return jsonify(ok=False, error="每批应包含 1 至 250 条 UniQuant 分析"), 400
    db, responses = get_db(), []
    for data in submitted:
        if not isinstance(data, dict):
            responses.append({"ok": False, "error": "分析格式无效"})
            continue
        general_id = str(data.get("general_id") or "").strip()
        job_id = str(data.get("job_id") or "").strip()
        processed = _uq_bool(data.get("processed")) or _uq_processed(data.get("film"))
        if not general_id or not job_id:
            responses.append({"ok": False, "error": "缺少 UniQuant 编号"})
            continue
        if not processed:
            responses.append({"ok": True, "skipped": True, "processed": False})
            continue
        original_name = str(data.get("sample_name") or "").strip()
        normalized_name = _uq_sample_name(original_name)
        data["raw_sample_name"] = original_name
        body, _ = _store_xrf_scan(db, data, source="OXSAS-UniQuant", kind="uq",
                                  external_id=f"{general_id}:{job_id}", sample_name=normalized_name)
        body.update(processed=True, normalized_sample_name=normalized_name)
        responses.append(body)
    db.commit()
    return jsonify(ok=True, results=responses,
                   imported=sum(1 for item in responses if item.get("ok") and not item.get("skipped")))


@app.route("/api/instrument/xrf/sync-state")
@xrf_client_required
def xrf_sync_state():
    ordinary, uq = 0, 0
    ordinary_ids, uq_ids = [], []
    for row in get_db().execute("""SELECT source,external_id,sample_id FROM xrf_analyses
            WHERE source IN (%s,%s)""", ("OXSAS", "OXSAS-UniQuant")).fetchall():
        try:
            if row["source"] == "OXSAS":
                ordinary = max(ordinary, int(row["external_id"]))
                ordinary_ids.append(str(row["external_id"]))
            else:
                uq = max(uq, int(str(row["external_id"]).split(":", 1)[0]))
                uq_ids.append(str(row["external_id"]))
        except (TypeError, ValueError):
            continue
    return jsonify(ok=True, ordinary_after=ordinary, uq_after_general=uq,
                   ordinary_ids=ordinary_ids, uq_ids=uq_ids)


# ---------------------------------------------------------------- 报告

@app.route("/api/special-results/<int:sid>", methods=["PUT"])
@capability_required("result_edit")
def update_special_result(sid):
    db = get_db()
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample or sample["workflow_type"] != "special":
        return jsonify(ok=False, error="专项样品不存在"), 404
    if sample["status"] in {"received", "queued", "reviewed", "cancelled"}:
        return jsonify(ok=False, error="当前样品状态不能录入专项数据"), 409
    result = db.execute("""SELECT sr.*,sm.schema_json FROM special_results sr
        JOIN special_methods sm ON sm.id=sr.method_id WHERE sr.sample_id=%s""", (sid,)).fetchone()
    if not result:
        return jsonify(ok=False, error="专项方法尚未建立"), 409
    raw = (request.json or {}).get("raw_data", {})
    if not isinstance(raw, dict):
        return jsonify(ok=False, error="专项原始数据格式无效"), 400
    clean = {}
    for key, value in raw.items():
        if value in (None, ""):
            continue
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = value.strip()
        clean[str(key)] = value
    schema = json.loads(result["schema_json"] or "{}")
    calculated, complete = calculate_special(schema, clean)
    status = "completed" if complete else ("in_progress" if clean else "pending")
    before = {"raw_data": json.loads(result["raw_data"] or "{}"),
              "calculated_data": json.loads(result["calculated_data"] or "{}"),
              "status": result["status"]}
    db.execute("""UPDATE special_results SET raw_data=%s,calculated_data=%s,status=%s,
        updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),updated_by=%s WHERE sample_id=%s""",
        (json.dumps(clean, ensure_ascii=False), json.dumps(calculated, ensure_ascii=False),
         status, g.user["id"], sid))
    db.execute("UPDATE samples SET updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s", (sid,))
    audit_event(db, "special_result", "sample", sid, before=before,
                after={"raw_data": clean, "calculated_data": calculated, "status": status})
    db.commit()
    return jsonify(ok=True, raw_data=clean, calculated_data=calculated, status=status)

def _default_report_rows(groups):
    rows_out = []
    for group in groups:
        if group.get("print") is False:
            continue
        final = group.get("final")
        if not final:
            continue
        rows_out.append({
            "item": str(group.get("analyte") or ""),
            "result": str(final.get("value") if final.get("value") is not None else ""),
            "unit": str(final.get("unit") or ""),
            "note": str(final.get("mode") or "系统计算"),
            "include": True,
        })
    return rows_out


def _clean_report_rows(value):
    if not isinstance(value, list) or len(value) > 200:
        raise BusinessExcelError("手工报告内容必须是最多 200 行的表格")
    clean = []
    limits = {"item": 120, "result": 120, "unit": 40, "note": 300}
    for raw in value:
        if not isinstance(raw, dict):
            raise BusinessExcelError("手工报告行格式不正确")
        row = {key: str(raw.get(key) or "").strip() for key in limits}
        if not any(row.values()):
            continue
        if not row["item"] or not row["result"]:
            raise BusinessExcelError("每条手工报告内容都必须填写报告项目和报告结果")
        if any(len(row[key]) > limit for key, limit in limits.items()):
            raise BusinessExcelError("手工报告内容过长")
        row["include"] = bool(raw.get("include", True))
        clean.append(row)
    return clean


def _attach_report_override(db, sid, payload):
    default_rows = _default_report_rows(payload.get("groups", []))
    override = db.execute("""SELECT ro.*,u.display_name,u.username FROM report_overrides ro
        LEFT JOIN users u ON u.id=ro.updated_by WHERE ro.sample_id=%s""", (sid,)).fetchone()
    manual = None
    if override:
        try:
            override_rows = _clean_report_rows(json.loads(override["rows_json"] or "[]"))
        except (BusinessExcelError, TypeError, json.JSONDecodeError):
            override_rows = []
        excludes = _report_print_excludes(payload["sample"])
        report_rows = []
        for row in override_rows:
            report_row = dict(row)
            report_row["include"] = f"m:{row['item'].casefold()}" not in excludes
            report_rows.append(report_row)
        manual = {
            "rows": override_rows,
            "updated_at": override["updated_at"],
            "updated_by": override["display_name"] or override["username"] or "未知用户",
        }
    payload["default_report_rows"] = default_rows
    payload["manual_report"] = manual
    payload["report_rows"] = report_rows if manual else default_rows
    payload["data_editors"] = _sample_data_editors(db, sid)
    return payload


def _attach_report_profile(db, payload):
    sample = payload["sample"]
    profile = None
    if sample.get("report_profile_id"):
        profile = db.execute("SELECT * FROM report_profiles WHERE id=%s",
                             (sample["report_profile_id"],)).fetchone()
    if not profile:
        profile = db.execute("SELECT * FROM report_profiles ORDER BY id LIMIT 1").fetchone()
    payload["report_profile"] = dict(profile) if profile else {
        "id": None, "name": "默认", "company_name_cn": "", "company_name_en": "",
        "raw_code": "", "final_code": "",
    }
    return payload


def _sample_data_editors(db, sid):
    """从审计历史聚合填写或修改过该样品结果数据的用户，按参与次数降序。"""
    counts = {}

    def record(username, user_id, cnt):
        if not username or username == "system" or cnt <= 0:
            return
        key = user_id or username
        entry = counts.setdefault(key, {"username": username, "user_id": user_id, "count": 0})
        entry["count"] += cnt

    for row in db.execute("""
            SELECT al.username, al.user_id, COUNT(*) AS cnt
            FROM audit_logs al
            WHERE al.entity_type='reading' AND CAST(al.entity_id AS INTEGER) IN (
                SELECT r.id FROM readings r JOIN sample_analytes sa ON sa.id=r.sample_analyte_id
                WHERE sa.sample_id=%s)
            GROUP BY al.user_id, al.username""", (sid,)):
        record(row["username"], row["user_id"], row["cnt"])
    for row in db.execute("""
            SELECT al.username, al.user_id, COUNT(*) AS cnt
            FROM audit_logs al
            WHERE al.entity_type='sample_analyte' AND CAST(al.entity_id AS INTEGER) IN (
                SELECT sa.id FROM sample_analytes sa WHERE sa.sample_id=%s)
            GROUP BY al.user_id, al.username""", (sid,)):
        record(row["username"], row["user_id"], row["cnt"])
    for row in db.execute("""
            SELECT al.username, al.user_id, COUNT(*) AS cnt
            FROM audit_logs al
            WHERE (al.entity_type='xrf_value' AND CAST(al.entity_id AS INTEGER) IN (
                    SELECT xv.id FROM xrf_values xv JOIN xrf_analyses xa ON xa.id=xv.analysis_id
                    WHERE xa.sample_id=%s))
                OR (al.entity_type='xrf_analysis' AND CAST(al.entity_id AS INTEGER) IN (
                    SELECT xa.id FROM xrf_analyses xa WHERE xa.sample_id=%s))
            GROUP BY al.user_id, al.username""", (sid, sid)):
        record(row["username"], row["user_id"], row["cnt"])
    for row in db.execute("""
            SELECT al.username, al.user_id, COUNT(*) AS cnt
            FROM audit_logs al
            WHERE al.entity_type='sample' AND al.entity_id=%s AND al.action IN
                ('excel_data_overwrite','special_result','result_override')
            GROUP BY al.user_id, al.username""", (str(sid),)):
        record(row["username"], row["user_id"], row["cnt"])

    editors = []
    for entry in counts.values():
        display = entry["username"]
        if entry["user_id"]:
            user = db.execute("SELECT display_name FROM users WHERE id=%s",
                              (entry["user_id"],)).fetchone()
            if user and user["display_name"]:
                display = user["display_name"]
        editors.append({"name": display, "count": entry["count"]})
    editors.sort(key=lambda item: (-item["count"], item["name"]))
    return editors


def build_report_payload(db, sid):
    """Build the single calculated payload shared by JSON and Excel reports."""
    sample_row = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample_row:
        raise BusinessExcelError("样品不存在")
    sample = dict(sample_row)
    attach_sample_status_history(db, [sample])
    if sample.get("workflow_type") == "special":
        special_row = db.execute("""SELECT sr.*,sm.code,sm.name AS method_name,
            sm.instrument,sm.schema_json FROM special_results sr JOIN special_methods sm
            ON sm.id=sr.method_id WHERE sr.sample_id=%s""", (sid,)).fetchone()
        special = dict(special_row) if special_row else None
        if special:
            special["schema"] = json.loads(special.pop("schema_json") or "{}")
            special["raw_data"] = json.loads(special["raw_data"] or "{}")
            special["calculated_data"] = json.loads(special["calculated_data"] or "{}")
        return _attach_report_profile(db, {
            "sample": sample, "preps": [], "groups": [], "special": special,
            "default_report_rows": [], "manual_report": None, "report_rows": [],
        })
    preps = [dict(row) for row in db.execute("""SELECT p.*,p.dilution_factor AS factor
        FROM preparations p
        WHERE p.sample_id=%s ORDER BY p.id""", (sid,))]
    items = [dict(row) for row in db.execute("""SELECT sa.*,a.name AS analyte,
        a.sort_order AS analyte_sort_order,a.default_unit AS analyte_default_unit,i.name AS instrument,i.itype,
        i.sort_order AS instrument_sort_order,m.name AS method_name,m.formula,m.note AS method_note,
        m.constants AS method_constants,m.output_unit AS method_output_unit,r.aux,p.name AS prep_name,
        p.mass_g AS prep_mass,p.volume_ml AS prep_vol,p.dilution_factor AS prep_factor,
        p.dilution_label AS prep_dilution FROM sample_analytes sa JOIN analytes a ON a.id=sa.analyte_id
        LEFT JOIN instruments i ON i.id=sa.instrument_id LEFT JOIN methods m ON m.id=sa.method_id
        LEFT JOIN results r ON r.sample_analyte_id=sa.id LEFT JOIN preparations p ON p.id=sa.preparation_id
        WHERE sa.sample_id=%s ORDER BY sa.id""", (sid,))]
    readings = db.execute("""SELECT rd.* FROM readings rd JOIN sample_analytes sa
        ON sa.id=rd.sample_analyte_id WHERE sa.sample_id=%s ORDER BY rd.id""", (sid,)).fetchall()
    by_task_readings = {}
    for reading in readings:
        by_task_readings.setdefault(reading["sample_analyte_id"], []).append(dict(reading))
    for item in items:
        item["readings"] = by_task_readings.get(item["id"], [])
    # 先算每行结果(calc_result 现在返回 值, 单位, 读数明细)
    rows_out = []
    for sa in items:
        if sa.get("itype") == "xrf":
            continue
        val, unit, details = calc_result(sa, sample["is_liquid"])
        aux = json.loads(sa["aux"] or "{}")
        rows_out.append({
            "sample_analyte_id": sa["id"],
            "analyte_id": sa["analyte_id"],
            "analyte": sa["analyte"],
            "analyte_sort_order": sa["analyte_sort_order"],
            "analyte_default_unit": sa.get("analyte_default_unit") or "",
            "prep": sa["prep_name"] or "原样",
            "mass_g": sa["prep_mass"],
            "volume_ml": sa["prep_vol"],
            "dilution": sa["prep_dilution"] or ("原样" if sa["preparation_id"] is None else "—"),
            "instrument": sa["instrument"],
            "instrument_sort_order": sa["instrument_sort_order"],
            "method": sa["method_name"] or "",
            "readings": details,
            "aux": aux,
            "value": val, "unit": unit,
            "selection": sa["selection"],
        })
    # XRF 是样品级整包结果：报告保留全部项目，是否列入最终报告由 use_report 控制。
    xrf_rows = [dict(row) for row in db.execute("""SELECT xv.id AS xrf_value_id, xv.name AS analyte, xv.value,
            xv.alt_name, xv.use_report, xa.method, xa.kind, xa.analyzed_at, xa.external_id,
            a.id AS analyte_id, a.sort_order AS analyte_sort_order
        FROM xrf_values xv JOIN xrf_analyses xa ON xa.id=xv.analysis_id
        LEFT JOIN analytes a ON lower(a.name)=lower(xv.name)
        WHERE xa.sample_id=%s ORDER BY xa.analyzed_at DESC, xv.id""", (sid,))]
    xrf_warnings = []
    xrf_targets = _load_xrf_targets(db, sid)
    if xrf_targets:
        # 结构化口径配置生效：按元素族单选目标，直取优先、缺项换算、全程可追溯。
        analyte_index = {}
        for row in db.execute("SELECT name,id,sort_order FROM analytes"):
            analyte_index[str(row["name"]).casefold()] = (row["id"], row["sort_order"])
        rows_out.extend(_resolve_xrf_report_rows(
            xrf_targets, xrf_rows, _xrf_reference(db), xrf_warnings, analyte_index))
    else:
        for xr in xrf_rows:
            value = float(f"{float(xr['value']):.5g}")
            rows_out.append({
                "sample_analyte_id": None, "xrf_value_id": xr["xrf_value_id"],
                "analyte_id": xr["analyte_id"], "analyte": xr["analyte"],
                "analyte_sort_order": xr["analyte_sort_order"] if xr["analyte_sort_order"] is not None else 999999,
                "prep": "原样", "mass_g": None, "volume_ml": None, "dilution": "原样",
                "instrument": "XRF", "instrument_sort_order": -1, "method": xr["method"] or "",
                "readings": [{"raw": value, "extra": {}, "used": bool(xr["use_report"]),
                              "value": value, "corrected_value": value}],
                "aux": {}, "value": value, "unit": "%",
                "selection": None if xr["use_report"] else "exclude",
                "analyzed_at": xr["analyzed_at"], "external_id": xr["external_id"],
            })
    analyte_defaults = {row["id"]: row["default_unit"] or "" for row in db.execute(
        "SELECT id,default_unit FROM analytes")}
    for row in rows_out:
        row.setdefault("analyte_default_unit", analyte_defaults.get(row.get("analyte_id"), ""))
    try:
        selected_units = json.loads(sample.get("result_units") or "{}")
    except (TypeError, json.JSONDecodeError):
        selected_units = {}
    if not isinstance(selected_units, dict):
        selected_units = {}
    density = sample.get("density_g_ml") if sample.get("is_liquid") else None
    # 按元素分组、统一显示单位后计算最终值。
    groups = []
    by_analyte = {}
    for r in rows_out:
        key = ("a", r["analyte_id"]) if r["analyte_id"] is not None else ("x", r["analyte"].casefold())
        by_analyte.setdefault(key, []).append(r)
    sample_order_key = _sample_analyte_order_key(db, sample)
    ordered_analytes = sorted(by_analyte, key=lambda key: sample_order_key(by_analyte[key][0]))
    print_excludes = _report_print_excludes(sample)
    for analyte_id in ordered_analytes:
        group_key = f"{analyte_id[0]}:{analyte_id[1]}"
        rs = sorted(by_analyte[analyte_id], key=lambda row: (
            row["instrument_sort_order"] is None,
            row["instrument_sort_order"] or 0,
            row["prep"],
            row.get("sample_analyte_id") or row.get("xrf_value_id") or 0,
        ))
        analyte = rs[0]["analyte"]
        quant = [r for r in rs if r["value"] is not None and isinstance(r["value"], (int, float))]
        chosen = [r for r in quant if r["selection"] != "exclude"]
        source_rows = chosen or quant
        available_units = result_unit_options(source_rows[0]["unit"], density) if source_rows else []
        for row in source_rows[1:]:
            compatible = set(result_unit_options(row["unit"], density))
            available_units = [unit for unit in available_units if unit in compatible]
        preferred_unit = normalized_result_unit(
            selected_units.get(group_key) or rs[0].get("analyte_default_unit"))
        target_unit = (preferred_unit if preferred_unit in available_units else
                       (normalized_result_unit(source_rows[0]["unit"]) if source_rows else ""))
        for row in rs:
            source_unit = normalized_result_unit(row.get("unit"))
            row["source_value"], row["source_unit"] = row.get("value"), source_unit
            if row.get("value") is not None and target_unit in result_unit_options(source_unit, density):
                row["value"] = rounded_display_value(
                    convert_result_unit(row["value"], source_unit, target_unit, density),
                    target_unit, bool(row.get("xrf_value_id")))
                row["unit"] = target_unit
                for detail in row.get("readings", []):
                    detail_source = normalized_result_unit(detail.get("unit") or source_unit)
                    if target_unit not in result_unit_options(detail_source, density):
                        continue
                    for field in ("value", "corrected_value"):
                        if detail.get(field) is not None:
                            detail[field] = rounded_display_value(
                                convert_result_unit(detail[field], detail_source, target_unit, density),
                                target_unit, bool(row.get("xrf_value_id")))
                    detail["unit"] = target_unit
        final = None
        if chosen:
            values = [r["value"] for r in chosen]
            average = sum(values) / len(values)
            avg = (float(f"{average:.5g}") if all(r.get("xrf_value_id") for r in chosen)
                   else round(average, 4))
            final = {"value": avg, "unit": chosen[0]["unit"], "based_on": len(chosen),
                     "mode": "单值" if len(chosen) == 1 else "自动平均"}
        groups.append({"analyte_id": analyte_id[1] if analyte_id[0] == "a" else None, "analyte": analyte,
                        "key": group_key, "print": group_key not in print_excludes,
                        "final": final, "available_units": available_units, "rows": rs})
    payload = _attach_report_override(db, sid, {
        "sample": sample, "preps": preps, "groups": groups, "special": None,
        "xrf_warnings": xrf_warnings, "xrf_targets": xrf_targets,
    })
    return _attach_report_profile(db, payload)


# 报告 payload 计算较重（多次查询 + 逐项目计算，实测数百毫秒），做进程内缓存：
# 只要样品数据没变就一直复用（带 10 分钟兜底 TTL 防极端并发竞态）。
# 所有数据变更都通过本进程的非 GET 接口写入，写入后立即清空缓存，
# 并登记受影响样品交给后台线程：静默 30 秒后自动重算，让缓存始终保持"热"的。
REPORT_PAYLOAD_CACHE = {}
REPORT_PAYLOAD_CACHE_MAX = 512
REPORT_PAYLOAD_CACHE_TTL = 600.0
_REPORT_CACHE_STALE_SECONDS = 30.0
_REPORT_CACHE_LOCK = threading.Lock()
_REPORT_CACHE_GEN = 0
_REPORT_CACHE_PENDING = None
_REPORT_CACHE_WAKE = threading.Event()
_REPORT_CACHE_REBUILDER_STARTED = False


def cached_report_payload(db, sid):
    cache_key = (str(database_target()), sid)
    now = time.monotonic()
    cached = REPORT_PAYLOAD_CACHE.get(cache_key)
    if cached and now - cached[0] < REPORT_PAYLOAD_CACHE_TTL:
        return cached[1]
    with _REPORT_CACHE_LOCK:
        generation = _REPORT_CACHE_GEN
    payload = build_report_payload(db, sid)
    with _REPORT_CACHE_LOCK:
        if generation == _REPORT_CACHE_GEN:
            if len(REPORT_PAYLOAD_CACHE) >= REPORT_PAYLOAD_CACHE_MAX:
                REPORT_PAYLOAD_CACHE.pop(next(iter(REPORT_PAYLOAD_CACHE)))
            REPORT_PAYLOAD_CACHE[cache_key] = (time.monotonic(), payload)
    return payload


def _report_cache_note_write():
    """写入请求完成后调用：立即作废全部缓存，并把之前缓存过的样品登记为待重算。"""
    global _REPORT_CACHE_PENDING, _REPORT_CACHE_GEN, _REPORT_CACHE_REBUILDER_STARTED
    now = time.monotonic()
    with _REPORT_CACHE_LOCK:
        sids = {sid for (_db, sid) in REPORT_PAYLOAD_CACHE}
        if _REPORT_CACHE_PENDING is None:
            _REPORT_CACHE_PENDING = {"sids": sids, "at": now}
        else:
            _REPORT_CACHE_PENDING["sids"] |= sids
            _REPORT_CACHE_PENDING["at"] = now
        _REPORT_CACHE_GEN += 1
        REPORT_PAYLOAD_CACHE.clear()
        if not _REPORT_CACHE_REBUILDER_STARTED:
            _REPORT_CACHE_REBUILDER_STARTED = True
            threading.Thread(target=_report_cache_rebuild_loop,
                             name="lims-report-rebuild", daemon=True).start()
    _REPORT_CACHE_WAKE.set()


def _report_cache_rebuild_loop():
    """防抖后台重算：写入静默 30 秒后，把被作废的样品 payload 重新算好。"""
    global _REPORT_CACHE_PENDING
    while True:
        _REPORT_CACHE_WAKE.wait()
        _REPORT_CACHE_WAKE.clear()
        pending = None
        while True:
            with _REPORT_CACHE_LOCK:
                pending = _REPORT_CACHE_PENDING
                wait_left = (_REPORT_CACHE_STALE_SECONDS -
                             (time.monotonic() - pending["at"])) if pending else 0
            if pending is None:
                break
            if wait_left > 0:
                _REPORT_CACHE_WAKE.wait(min(wait_left, 2.0))
                _REPORT_CACHE_WAKE.clear()
                continue
            with _REPORT_CACHE_LOCK:
                pending = _REPORT_CACHE_PENDING
                _REPORT_CACHE_PENDING = None
            _rebuild_report_payloads(pending["sids"], pending["at"])


def _rebuild_report_payloads(sids, cleared_at):
    if not sids:
        return
    try:
        connection = connect_database(database_target())
    except Exception:
        return
    try:
        for sid in sids:
            cache_key = (str(database_target()), sid)
            cached = REPORT_PAYLOAD_CACHE.get(cache_key)
            if cached and cached[0] >= cleared_at:
                continue  # 等待期内已被请求同步重建过，数据更新，跳过
            with _REPORT_CACHE_LOCK:
                generation = _REPORT_CACHE_GEN
            try:
                payload = build_report_payload(connection, sid)
            except Exception:
                REPORT_PAYLOAD_CACHE.pop(cache_key, None)
                continue
            with _REPORT_CACHE_LOCK:
                if generation == _REPORT_CACHE_GEN:
                    if len(REPORT_PAYLOAD_CACHE) >= REPORT_PAYLOAD_CACHE_MAX:
                        REPORT_PAYLOAD_CACHE.pop(next(iter(REPORT_PAYLOAD_CACHE)))
                    REPORT_PAYLOAD_CACHE[cache_key] = (time.monotonic(), payload)
    finally:
        connection.close()


@app.route("/api/report/<int:sid>")
def report(sid):
    try:
        return jsonify(cached_report_payload(get_db(), sid))
    except BusinessExcelError as exc:
        return excel_error(exc, 404)


@app.route("/api/reports/<int:sid>/manual", methods=["PUT", "DELETE"])
@capability_required("result_override")
def manual_report(sid):
    db = get_db()
    data = request.get_json(silent=True) or {}
    sample = db.execute("SELECT id,status,workflow_type FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="样品不存在"), 404
    if sample["workflow_type"] != "regular":
        return jsonify(ok=False, error="专项检测报告暂不使用手工报告表"), 400
    if sample["status"] not in {"completed", "reviewed"}:
        return jsonify(ok=False, error="样品测量完成后才能手工补录结果"), 409
    reason = str(data.get("reason", "")).strip()
    if not reason:
        return jsonify(ok=False, error="手工补录或恢复结果必须填写原因"), 400
    try:
        payload = cached_report_payload(db, sid)
        submitted = [] if request.method == "DELETE" else _clean_report_rows(data.get("rows"))
    except BusinessExcelError as exc:
        return excel_error(exc, 400)
    if request.method == "PUT" and not submitted:
        return jsonify(ok=False, error="请至少填写一条手工报告内容"), 400
    actor = consume_forced_authorization("result_override")
    if not actor:
        return jsonify(ok=False, code="forced_authorization_required",
                       capability="result_override",
                       error="本次操作必须重新输入具备审核退回与手工结果补录权限的用户密码"), 428
    old_manual = payload.get("manual_report")
    old_rows = old_manual["rows"] if old_manual else payload["default_report_rows"]
    target_rows = submitted or payload["default_report_rows"]
    target_source = "system" if request.method == "DELETE" or submitted == payload["default_report_rows"] else "manual"
    old_source = "manual" if old_manual else "system"
    if old_rows == target_rows and old_source == target_source:
        return jsonify(ok=True, changed=False)
    if target_source == "system":
        db.execute("DELETE FROM report_overrides WHERE sample_id=%s", (sid,))
    else:
        db.execute("""INSERT INTO report_overrides(sample_id,rows_json,updated_by,updated_at)
            VALUES(%s,%s,%s,to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')) ON CONFLICT(sample_id) DO UPDATE SET
            rows_json=excluded.rows_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (sid, json.dumps(submitted, ensure_ascii=False), actor["id"]))
    db.execute("UPDATE samples SET updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s", (sid,))
    audit_event(db, "result_override", "sample", sid,
                before={"source": old_source, "report_rows": old_rows},
                after={"source": target_source, "report_rows": target_rows},
                reason=reason, user=actor)
    db.commit()
    return jsonify(ok=True, changed=True)


@app.route("/api/excel/reports/<int:sid>")
def excel_report(sid):
    try:
        payload = cached_report_payload(get_db(), sid)
        output = build_report(payload)
        sample = payload["sample"]
        return send_file(output, as_attachment=True,
                         download_name=f"分析报告-{sample['lims_no'] or sid}.xlsx", mimetype=EXCEL_MIME)
    except BusinessExcelError as exc:
        return excel_error(exc, 404 if str(exc) == "样品不存在" else 400)


@app.route("/api/excel/results-report")
def excel_results_report():
    raw_ids = [item.strip() for item in request.args.get("sample_ids", "").split(",")
               if item.strip()]
    try:
        sample_ids = list(dict.fromkeys(int(item) for item in raw_ids))
    except ValueError:
        return jsonify(ok=False, error="样品列表格式无效"), 400
    if not sample_ids or len(sample_ids) > 200:
        return jsonify(ok=False, error="请选择 1 至 200 个样品"), 400
    db = get_db()
    template_items = []
    template_name = "系统默认"
    requested_template_id = request.args.get("template_id", "").strip()
    template_id = None
    if requested_template_id:
        try:
            template = db.execute("SELECT name,items_json FROM result_order_templates WHERE id=%s",
                                  (int(requested_template_id),)).fetchone()
        except ValueError:
            template = None
        if not template:
            return jsonify(ok=False, error="通用顺序模板不存在"), 404
        template_id = int(requested_template_id)
        template_items = json.loads(template["items_json"] or "[]")
        template_name = template["name"] or "系统默认"
    else:
        template_id = _default_order_template_id(db)
        template = db.execute("SELECT name FROM result_order_templates WHERE id=%s",
                              (template_id,)).fetchone() if template_id else None
        if template and template["name"]:
            template_name = template["name"]
    payloads = []
    for sid in sample_ids:
        try:
            payload = cached_report_payload(db, sid)
        except BusinessExcelError as exc:
            return excel_error(exc, 404)
        sample = payload["sample"]
        if sample.get("workflow_type") != "regular" or sample.get("status") not in {
                "completed", "reviewed"}:
            return jsonify(ok=False, error="结果矩阵只能导出测量完成的常规样品"), 409
        payloads.append(payload)
    columns, column_keys = [], set()
    for item in template_items:
        name = str(item).strip()
        if name and name.casefold() not in column_keys:
            columns.append(name)
            column_keys.add(name.casefold())
    remaining = {}
    for payload in payloads:
        for row in payload.get("report_rows", []):
            name = str(row.get("item") or "").strip()
            if row.get("include", True) and name and name.casefold() not in column_keys:
                remaining.setdefault(name.casefold(), name)
    order_key = _universal_order_key(db, template_id)
    for name in sorted(remaining.values(), key=order_key):
        columns.append(name)
        column_keys.add(name.casefold())
    canonical = {name.casefold(): name for name in columns}
    sample_rows = []
    for payload in payloads:
        values = {}
        for row in payload.get("report_rows", []):
            if not row.get("include", True):
                continue
            key = str(row.get("item") or "").strip().casefold()
            if key not in canonical:
                continue
            value = row.get("result")
            try:
                value = float(value)
            except (TypeError, ValueError):
                pass
            values[canonical[key]] = value
        sample = payload["sample"]
        sample_rows.append({"sample_no": sample.get("name"), "sample_name": sample.get("category"),
                            "values": values})
    output = build_result_report(columns, sample_rows, datetime.now().strftime("%Y-%m-%d"))
    safe_name = re.sub(r'[\\/:*?"<>|]', "", template_name).strip() or "全局默认"
    return send_file(output, as_attachment=True,
                     download_name=f"结果报告-{safe_name}-{datetime.now().strftime('%Y%m%d')}.xlsx",
                     mimetype=EXCEL_MIME)


@app.route("/api/xrf/reference")
def xrf_reference():
    """元素与常见氧化物参考数据，供报告口径选择界面使用。"""
    db = get_db()
    elements = rows("""SELECT atomic_number,symbol,name_zh,atomic_weight,is_mass_number
        FROM chemical_elements ORDER BY atomic_number""")
    oxides = rows("""SELECT formula,name_zh,element_symbol,element_count,oxygen_count,
        element_to_oxide_factor,is_conventional FROM common_oxides ORDER BY formula""")
    return jsonify(ok=True, elements=elements, oxides=oxides)


@app.route("/api/xrf/samples/<int:sid>")
def xrf_sample_results(sid):
    db = get_db()
    sample = db.execute("""SELECT s.id,s.name,s.lims_no,s.status,s.xrf,s.xrf_report_items,
        m.name AS method_name FROM samples s LEFT JOIN methods m ON m.id=s.xrf_method_id
        WHERE s.id=%s""", (sid,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="样品不存在"), 404
    analyses = rows("SELECT * FROM xrf_analyses WHERE sample_id=%s ORDER BY id DESC", (sid,))
    for analysis in analyses:
        try:
            analysis["options"] = json.loads(analysis.get("options_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            analysis["options"] = {}
        analysis["values"] = rows("""SELECT id,name,value,use_report,alt_name FROM xrf_values
            WHERE analysis_id=%s AND lower(substr(name,1,2))<>'bg'
            ORDER BY value DESC,id""", (analysis["id"],))
    return jsonify(ok=True, sample=dict(sample), analyses=analyses,
                   targets=_load_xrf_targets(db, sid))


@app.route("/api/xrf/samples/<int:sid>/targets", methods=["PUT"])
@capability_required("report_edit")
def xrf_sample_targets(sid):
    """保存样品级 XRF 报告口径：每个元素族只选一个目标。"""
    db = get_db()
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sid,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="样品不存在"), 404
    if sample["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="已审核、已出报告或已作废样品不能修改报告口径"), 409
    submitted = (request.json or {}).get("targets")
    if not isinstance(submitted, list):
        return jsonify(ok=False, error="报告口径格式无效"), 400
    elements, oxides = _xrf_reference(db)
    cleaned, seen = [], set()
    for item in submitted:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target") or "").strip()
        if not target:
            return jsonify(ok=False, error="报告目标不能为空"), 400
        family, target_name = _xrf_target_family(target, elements, oxides)
        if family is None:
            family, target_name, allow = target.casefold(), target, 0
        else:
            allow = int(bool(item.get("allow_conversion", True)))
        if family in seen:
            return jsonify(ok=False, error=f"元素族 {family} 出现了多个报告口径"), 400
        seen.add(family)
        cleaned.append({"family": family, "target": target_name,
                        "include": int(bool(item.get("include", True))),
                        "allow_conversion": allow})
    before = _load_xrf_targets(db, sid)
    db.execute("DELETE FROM xrf_report_targets WHERE sample_id=%s", (sid,))
    for item in cleaned:
        db.execute("""INSERT INTO xrf_report_targets(sample_id,family,target,include,allow_conversion)
            VALUES(%s,%s,%s,%s,%s)""", (sid, item["family"], item["target"],
                                   item["include"], item["allow_conversion"]))
    report_items = ", ".join(item["target"] for item in cleaned if item["include"])
    db.execute("""UPDATE samples SET xrf_report_items=%s,
        updated_at=to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS') WHERE id=%s""",
               (report_items, sid))
    included = {item["target"].casefold() for item in cleaned if item["include"]}
    db.execute("""UPDATE xrf_values SET use_report=0 WHERE analysis_id IN
        (SELECT id FROM xrf_analyses WHERE sample_id=%s)""", (sid,))
    for name in included:
        db.execute("""UPDATE xrf_values SET use_report=1 WHERE lower(name)=%s AND analysis_id IN
            (SELECT id FROM xrf_analyses WHERE sample_id=%s)""", (name, sid))
    after = _load_xrf_targets(db, sid)
    audit_event(db, "xrf_targets_update", "sample", sid,
                before={"targets": before, "xrf_report_items": sample["xrf_report_items"]},
                after={"targets": after, "xrf_report_items": report_items})
    db.commit()
    return jsonify(ok=True, targets=after, xrf_report_items=report_items)


@app.route("/api/xrf/analyses/<int:analysis_id>/sample", methods=["PUT", "DELETE"])
@capability_required("result_edit")
def assign_xrf_analysis(analysis_id):
    db = get_db()
    analysis = db.execute("SELECT * FROM xrf_analyses WHERE id=%s", (analysis_id,)).fetchone()
    if not analysis:
        return jsonify(ok=False, error="XRF 扫描不存在"), 404
    if request.method == "DELETE":
        old_sample_id = analysis["sample_id"]
        if old_sample_id is None:
            return jsonify(ok=True, analysis_id=analysis_id, sample_id=None, unchanged=True)
        sample = db.execute("SELECT * FROM samples WHERE id=%s", (old_sample_id,)).fetchone()
        if sample and sample["status"] in {"reviewed", "cancelled"}:
            return jsonify(ok=False, error="已审核或已作废样品不能解绑 XRF 扫描"), 409
        before = dict(analysis)
        db.execute("UPDATE xrf_analyses SET sample_id=NULL WHERE id=%s", (analysis_id,))
        db.execute("UPDATE xrf_values SET use_report=0 WHERE analysis_id=%s", (analysis_id,))
        recompute_sample_progress(db, old_sample_id)
        after = dict(db.execute("SELECT * FROM xrf_analyses WHERE id=%s", (analysis_id,)).fetchone())
        audit_event(db, "xrf_unassign", "xrf_analysis", analysis_id, before=before, after=after)
        db.commit()
        return jsonify(ok=True, analysis_id=analysis_id, sample_id=None)
    try:
        sample_id = int((request.json or {}).get("sample_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="请选择要关联的 LIMS 样品"), 400
    sample = db.execute("SELECT * FROM samples WHERE id=%s", (sample_id,)).fetchone()
    if not sample:
        return jsonify(ok=False, error="LIMS 样品不存在"), 404
    if (sample["workflow_type"] or "regular") != "regular" or not sample["xrf"]:
        return jsonify(ok=False, error="只能关联已启用 XRF 的常规样品"), 409
    if sample["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="已审核或已作废样品不能关联 XRF 扫描"), 409
    old_sample_id = analysis["sample_id"]
    if old_sample_id == sample_id:
        return jsonify(ok=True, analysis_id=analysis_id, sample_id=sample_id, unchanged=True)
    if old_sample_id is not None:
        return jsonify(ok=False, error="该 XRF 扫描已关联其他样品"), 409
    occupied = db.execute("SELECT id FROM xrf_analyses WHERE sample_id=%s LIMIT 1",
                          (sample_id,)).fetchone()
    if occupied:
        return jsonify(ok=False, error="该样品已关联 XRF 扫描，请先解绑原扫描"), 409

    defaults = {part.strip().casefold() for part in re.split(
        r"[,，、;；\s]+", sample["xrf_report_items"] or "") if part.strip()}
    before = dict(analysis)
    try:
        assigned = db.execute("UPDATE xrf_analyses SET sample_id=%s WHERE id=%s AND sample_id IS NULL",
                              (sample_id, analysis_id))
    except INTEGRITY_ERRORS:
        db.rollback()
        return jsonify(ok=False, error="该样品已关联 XRF 扫描，请先解绑原扫描"), 409
    if assigned.rowcount != 1:
        return jsonify(ok=False, error="该 XRF 扫描已关联其他样品"), 409
    db.execute("UPDATE xrf_values SET use_report=0 WHERE analysis_id=%s", (analysis_id,))
    if defaults:
        values = db.execute("SELECT id,name FROM xrf_values WHERE analysis_id=%s", (analysis_id,)).fetchall()
        db.executemany("UPDATE xrf_values SET use_report=1 WHERE id=%s",
                       [(value["id"],) for value in values if value["name"].casefold() in defaults])
    recompute_sample_progress(db, sample_id)
    after = dict(db.execute("SELECT * FROM xrf_analyses WHERE id=%s", (analysis_id,)).fetchone())
    audit_event(db, "xrf_assign", "xrf_analysis", analysis_id, before=before, after=after)
    db.commit()
    return jsonify(ok=True, analysis_id=analysis_id, sample_id=sample_id,
                   sample_name=sample["name"], lims_no=sample["lims_no"])


@app.route("/api/xrf/monitor")
def xrf_monitor():
    """仪器页监控 XRF 终端状态和服务器保存的完整扫描历史。"""
    db = get_db()
    client = db.execute("""SELECT * FROM xrf_client_status
        ORDER BY updated_at DESC LIMIT 1""").fetchone()
    client_data = dict(client) if client else None
    if client_data:
        try:
            seen_at = datetime.strptime(client_data["seen_at"], "%Y-%m-%d %H:%M:%S")
            client_data["online"] = (datetime.now() - seen_at).total_seconds() <= 45
        except (TypeError, ValueError):
            client_data["online"] = False
    standard_clients = rows("""SELECT scs.client_id,scs.machine_name,scs.client_version,
            scs.network_position,scs.seen_at,i.id AS instrument_id,i.name AS instrument_name,
            u.username,u.display_name
        FROM standard_client_status scs
        LEFT JOIN instruments i ON i.id=scs.instrument_id
        LEFT JOIN users u ON u.id=scs.user_id
        WHERE scs.seen_at::timestamp >= clock_timestamp() - interval '60 seconds'
        ORDER BY scs.seen_at DESC,scs.client_id""")
    for standard_client in standard_clients:
        latest = db.execute("""SELECT response_json,created_at
            FROM standard_client_submissions WHERE client_id=%s ORDER BY id DESC LIMIT 1""",
                            (standard_client["client_id"],)).fetchone()
        standard_client["recent_entry"] = None
        if latest:
            try:
                imported = json.loads(latest["response_json"] or "{}").get("imported") or []
            except (TypeError, json.JSONDecodeError):
                imported = []
            standard_client["recent_entry"] = {
                "at": latest["created_at"], "count": len(imported),
                "items": [f"{item.get('analyte', '')} {item.get('value', '')}".strip()
                          for item in imported[:6] if isinstance(item, dict)],
            }
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(10, int(request.args.get("limit", 25))))
    except (TypeError, ValueError):
        page, page_size = 1, 25
    query = str(request.args.get("q") or "").strip().casefold()
    kind = str(request.args.get("kind") or "all").strip().casefold()
    match = str(request.args.get("match") or "all").strip().casefold()
    conditions, params = ["1=1"], []
    if query:
        conditions.append("""lower(COALESCE(xa.sample_name,'') || ' ' || COALESCE(s.name,'') ||
            ' ' || COALESCE(s.lims_no,'') || ' ' || COALESCE(xa.method,'') ||
            ' ' || COALESCE(xa.batch,'') || ' ' || COALESCE(xa.external_id,'')) LIKE %s""")
        params.append(f"%{query}%")
    if kind in {"quant", "uq"}:
        conditions.append("COALESCE(xa.kind,'quant')=%s")
        params.append(kind)
    if match == "matched":
        conditions.append("xa.sample_id IS NOT NULL")
    elif match == "unmatched":
        conditions.append("xa.sample_id IS NULL")
    where = " AND ".join(conditions)
    total = db.execute(f"""SELECT COUNT(*) FROM xrf_analyses xa
        LEFT JOIN samples s ON s.id=xa.sample_id WHERE {where}""", params).fetchone()[0]
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    scans = rows(f"""SELECT xa.*,s.name AS lims_sample_name,s.lims_no,
            s.status AS sample_status FROM xrf_analyses xa
        LEFT JOIN samples s ON s.id=xa.sample_id WHERE {where}
        ORDER BY COALESCE(xa.analyzed_at,xa.created_at) DESC,xa.id DESC LIMIT %s OFFSET %s""",
                 (*params, page_size, (page - 1) * page_size))
    option_labels = {
        "chemistry": "化学表示", "shape": "Shape", "case_nb": "Case",
        "case_number": "Case", "kappas": "Kappa", "kappa_list": "Kappa",
        "atmosphere": "气氛", "report_level": "报告限(ppm)", "sector": "Sector",
        "area": "面积", "diameter": "直径", "gross_diameter": "总直径",
        "mass": "质量", "gross_mass": "总质量", "height": "高度", "rho": "密度",
        "shadow_loss": "阴影损耗", "known_conc": "已知浓度", "rest": "Rest",
        "do_s": "DoS", "remark": "备注",
    }
    for scan in scans:
        try:
            options = json.loads(scan.pop("options_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            options = {}
        chemistry = options.get("chemistry")
        scan["oxide"] = chemistry in {1, "1", "oxide", "氧化物"}
        scan["matched"] = scan["sample_id"] is not None
        scan["options"] = options
        seen_labels, details = set(), []
        for key, label in option_labels.items():
            value = options.get(key)
            if value in (None, "", []) or label in seen_labels:
                continue
            seen_labels.add(label)
            if key == "chemistry":
                value = "氧化物" if scan["oxide"] else "元素" if value in {0, "0", "element"} else value
            elif key == "atmosphere" and value in {0, "0"}:
                value = "真空"
            details.append({"label": label, "value": value})
        scan["option_details"] = details
        values = rows("""SELECT id,name,value,use_report FROM xrf_values
            WHERE analysis_id=%s AND lower(substr(name,1,2))<>'bg'
            ORDER BY value DESC,id""", (scan["id"],))
        scan["values"] = values
        scan["value_count"] = len(values)
        scan["used_count"] = sum(1 for value in values if value["use_report"])
        scan["top_values"] = [f"{value['name']} {float(value['value']):.5g}%" for value in values[:5]]
        if scan["kind"] == "uq":
            scan["option_details"] = [detail for detail in scan["option_details"] if detail["label"].casefold() != "film"]
            scan["film"] = None
    return jsonify(ok=True, standard_clients=standard_clients, client=client_data,
                   scans=scans, total=total, page=page, page_size=page_size, pages=pages)


@app.route("/api/xrf/uq/<int:uid>")
def xrf_uq_detail(uid):
    db = get_db()
    analysis = db.execute("""SELECT ua.*,s.name AS lims_sample_name,s.lims_no,
            s.status AS sample_status FROM uq_analyses ua
            LEFT JOIN samples s ON s.id=ua.sample_id WHERE ua.id=%s""", (uid,)).fetchone()
    if not analysis:
        return jsonify(ok=False, error="UniQuant 记录不存在"), 404
    result = dict(analysis)
    for source, target in (("options_json", "options"), ("job_json", "job")):
        try:
            result[target] = json.loads(result.pop(source) or "{}")
        except (TypeError, json.JSONDecodeError):
            result[target] = {}
    channels = rows("SELECT * FROM uq_channels WHERE uq_analysis_id=%s ORDER BY id", (uid,))
    for channel in channels:
        try:
            channel["payload"] = json.loads(channel.pop("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            channel["payload"] = {}
    result["channels"] = channels
    return jsonify(ok=True, analysis=result)


@app.route("/api/xrf/values/<int:vid>/report-use", methods=["PUT"])
@capability_required("report_edit")
def xrf_report_use(vid):
    db = get_db()
    row = db.execute("""SELECT xv.*,xa.sample_id,s.status FROM xrf_values xv
        JOIN xrf_analyses xa ON xa.id=xv.analysis_id JOIN samples s ON s.id=xa.sample_id
        WHERE xv.id=%s""", (vid,)).fetchone()
    if not row:
        return jsonify(ok=False, error="XRF 结果不存在"), 404
    if row["status"] in {"reviewed", "cancelled"}:
        return jsonify(ok=False, error="已审核或已作废，不能改变结果参与计算状态"), 409
    use = bool((request.json or {}).get("use", True))
    db.execute("UPDATE xrf_values SET use_report=%s WHERE id=%s", (int(use), vid))
    audit_event(db, "xrf_report_use", "xrf_value", vid, before=dict(row),
                after={"use_report": int(use)})
    db.commit()
    return jsonify(ok=True, use=use)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
