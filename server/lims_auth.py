"""首次初始化、终端登录、用户授权、能力权限和审计查询。"""

import json
import time
from functools import wraps

from flask import (Blueprint, current_app, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from lims_workflow import audit_changes, audit_event


bp = Blueprint("auth", __name__)
CAPABILITIES = {
    "sample_manage": "样品登记与修改",
    "result_edit": "检测数据录入",
    "report_edit": "报告编辑",
    "result_override": "审核退回与手工结果补录",
    "review_release": "审核与发布",
    "settings_manage": "基础设置维护",
    "user_manage": "用户管理",
    "terminal_manage": "终端管理",
}
LEGACY_ROLE_CAPABILITIES = {
    "receiver": {"sample_manage"},
    "analyst": {"sample_manage", "result_edit", "report_edit"},
    "reviewer": {"report_edit", "review_release"},
    "admin": set(CAPABILITIES),
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUTHORIZATION_SECONDS = 120
FORCED_AUTHORIZATION_SECONDS = 60
TERMINAL_KINDS = {"standard", "admin"}
PASSWORD_METHOD = "pbkdf2:sha256:20000"


def hash_password(password):
    return generate_password_hash(password, method=PASSWORD_METHOD)


def _check_password(db, row, password, entity):
    if not check_password_hash(row["password_hash"], password):
        return False
    if not row["password_hash"].startswith(PASSWORD_METHOD + "$"):
        table = "users" if entity == "user" else "terminals"
        db.execute(f"UPDATE {table} SET password_hash=? WHERE id=?",
                   (hash_password(password), row["id"]))
        db.commit()
    return True


def get_db():
    return current_app.extensions["lims_get_db"]()


def _public_user(user):
    result = {key: user[key] for key in ("id", "username", "display_name")}
    result["permissions"] = sorted(user_permissions(user))
    return result


def user_permissions(user):
    if not user:
        return set()
    try:
        raw = user["permissions"]
    except (KeyError, IndexError, TypeError):
        raw = None
    try:
        permissions = set(json.loads(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        permissions = set()
    if not permissions:
        try:
            permissions = set(LEGACY_ROLE_CAPABILITIES.get(user["role"], set()))
        except (KeyError, IndexError, TypeError):
            pass
    return permissions & set(CAPABILITIES)


def _clean_permissions(value):
    if not isinstance(value, list):
        return None
    permissions = {str(item) for item in value}
    return permissions if permissions <= set(CAPABILITIES) else None


def _matching_users(db, password, *, active=True):
    where = " WHERE active=1" if active else ""
    return [row for row in db.execute("SELECT * FROM users" + where).fetchall()
            if _check_password(db, row, password, "user")]


def authenticate_capable_user(db, password, capability):
    """Return the unique active user matching a password and capability."""
    matches = _matching_users(db, password)
    if len(matches) != 1:
        return None, "用户密码不正确或不唯一"
    user = matches[0]
    if capability not in user_permissions(user):
        return None, f"该用户没有“{CAPABILITIES[capability]}”权限"
    return user, None


def _password_in_use(db, password, excluding_user_id=None):
    return any(row["id"] != excluding_user_id and
               _check_password(db, row, password, "user")
                for row in db.execute("SELECT id,password_hash FROM users WHERE active=1"))


def _terminal_password_in_use(db, password, excluding_terminal_id=None):
    return any(row["id"] != excluding_terminal_id and
                 _check_password(db, row, password, "terminal")
                for row in db.execute(
                    "SELECT id,password_hash FROM terminals WHERE active=1 AND kind<>'personal'"))


def _permission_inheritance_error(permissions):
    inherited = user_permissions(getattr(g, "user", None))
    excess = set(permissions) - inherited
    if not excess:
        return None
    labels = "、".join(CAPABILITIES[item] for item in sorted(excess))
    return f"不能授予当前用户不具备的能力：{labels}"


def capability_required(capability):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if current_app.config.get("AUTH_DISABLED"):
                return view(*args, **kwargs)
            if request.method in SAFE_METHODS and getattr(g, "terminal", None):
                return view(*args, **kwargs)
            if not g.user:
                return jsonify(ok=False, error="请先授权用户"), 401
            if capability not in user_permissions(g.user):
                return jsonify(ok=False,
                               error=f"当前用户没有“{CAPABILITIES[capability]}”权限",
                               code="permission_denied",
                               capability=capability), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def consume_forced_authorization(capability):
    """Consume a one-time password confirmation for a sensitive operation."""
    if current_app.config.get("AUTH_DISABLED"):
        return g.user
    purpose = session.pop("forced_authorization_purpose", None)
    user_id = session.pop("forced_authorization_user_id", None)
    confirmed_at = session.pop("forced_authorization_at", 0)
    try:
        current = time.time() - float(confirmed_at) <= FORCED_AUTHORIZATION_SECONDS
    except (TypeError, ValueError):
        current = False
    if purpose != capability or not user_id or not current:
        return None
    user = get_db().execute(
        "SELECT id,username,display_name,role,permissions,active FROM users WHERE id=? AND active=1",
        (user_id,)).fetchone()
    return user if user and capability in user_permissions(user) else None


def load_user():
    g.authorization_should_extend = False
    if current_app.config.get("AUTH_DISABLED"):
        g.terminal = None
        g.user = {"id": None, "username": "test", "display_name": "测试管理员",
                  "permissions": json.dumps(sorted(CAPABILITIES))}
        return
    db = get_db()
    personal_user_id = session.get("personal_user_id")
    if personal_user_id:
        g.terminal = {"id": None, "name": "个人终端", "kind": "personal", "active": 1}
        g.user = db.execute(
            "SELECT id,username,display_name,role,permissions,active FROM users WHERE id=? AND active=1",
            (personal_user_id,)).fetchone()
        if not g.user:
            session.clear()
            g.terminal = None
        return
    terminal_id = session.get("terminal_id")
    g.terminal = db.execute(
        "SELECT id,name,kind,active FROM terminals WHERE id=? AND active=1",
        (terminal_id,)).fetchone() if terminal_id else None
    g.user = None
    if not g.terminal:
        return
    if g.terminal["kind"] == "admin":
        g.user = {"id": None, "username": f"terminal:{g.terminal['name']}",
                  "display_name": f"管理员 · {g.terminal['name']}",
                  "permissions": json.dumps(sorted(CAPABILITIES))}
        return
    user_id = session.get("authorized_user_id")
    authorized_at = session.get("last_write", 0)
    try:
        current = time.time() - float(authorized_at) <= AUTHORIZATION_SECONDS
    except (TypeError, ValueError):
        current = False
    if user_id and current:
        g.user = db.execute(
            "SELECT id,username,display_name,role,permissions,active FROM users WHERE id=? AND active=1",
            (user_id,)).fetchone()
    if not g.user:
        session.pop("authorized_user_id", None)
        session.pop("last_write", None)


def login_required_before_request():
    endpoint = request.endpoint or ""
    if current_app.config.get("AUTH_DISABLED") or endpoint.startswith("static"):
        return None
    if endpoint == "health":
        return None
    # 仪器客户端使用自己的本机/设备令牌认证，不依赖浏览器 Session。
    if request.path.startswith(("/api/instrument/xrf", "/api/instrument/standard")):
        return None
    db = get_db()
    has_users = db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    has_terminals = db.execute("SELECT 1 FROM terminals LIMIT 1").fetchone()
    if not has_users or not has_terminals:
        if endpoint == "auth.setup":
            return None
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="系统尚未完成初始化，请先设置用户和终端"), 503
        return redirect(url_for("auth.setup"))
    if endpoint in {"auth.login", "auth.setup"}:
        return None
    if not g.terminal:
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="终端登录已失效，请重新登录"), 401
        return redirect(url_for("auth.login", next=request.full_path))
    if request.method in SAFE_METHODS or endpoint in {
            "auth.logout", "auth.authorize", "auth.clear_authorization"}:
        return None
    if g.terminal["kind"] in {"admin", "personal"}:
        return None
    if not g.user:
        return jsonify(ok=False, code="authorization_required",
                       error="请输入用户密码以确认本次修改"), 428
    g.authorization_should_extend = True
    return None


def extend_write_authorization(response):
    if (not current_app.config.get("AUTH_DISABLED") and
            getattr(g, "authorization_should_extend", False) and response.status_code < 400):
        session["last_write"] = time.time()
    return response


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    db = get_db()
    has_users = bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())
    has_terminals = bool(db.execute("SELECT 1 FROM terminals LIMIT 1").fetchone())
    if has_users and has_terminals:
        return redirect(url_for("auth.login"))
    error = ""
    if request.method == "POST":
        user_password = (request.form.get("password") or request.form.get("user_password") or
                         request.form.get("current_admin_password") or
                         (request.form.get("admin_password")
                          if request.form.get("admin_terminal_password") else ""))
        standard_password = (request.form.get("standard_password") or
                             request.form.get("normal_terminal_password") or
                             request.form.get("standard_terminal_password") or
                             request.form.get("terminal_password") or "")
        admin_password = (request.form.get("admin_terminal_password") or
                          request.form.get("management_terminal_password") or
                          (request.form.get("admin_password")
                           if request.form.get("password") or request.form.get("user_password") else ""))
        display_name = request.form.get("display_name", "").strip() or "cxl"
        if not user_password or not standard_password or not admin_password:
            error = "所有密码均不能为空"
        elif standard_password == admin_password:
            error = "两个终端必须使用不同的密码"
        elif has_users:
            matches = _matching_users(db, user_password)
            if len(matches) != 1 or "user_manage" not in user_permissions(matches[0]):
                error = "请输入具备用户管理能力的启用用户密码"
        if not error:
            if not has_users:
                permissions = json.dumps(sorted(CAPABILITIES))
                cur = db.execute("""INSERT INTO users(
                    username,password_hash,display_name,role,permissions)
                    VALUES('cxl',?,?,'custom',?)""",
                    (hash_password(user_password), display_name, permissions))
                audit_event(db, "setup", "user", cur.lastrowid,
                            after={"username": "cxl", "permissions": sorted(CAPABILITIES)},
                            user={"id": cur.lastrowid, "username": "cxl"})
            if not has_terminals:
                db.executemany("""INSERT INTO terminals(name,password_hash,kind,sort_order)
                    VALUES(?,?,?,?)""", [
                    ("二组", hash_password(standard_password), "standard", 1),
                    ("管理终端", hash_password(admin_password), "admin", 2),
                ])
            db.commit()
            session.clear()
            return redirect(url_for("auth.login"))
    return render_template("setup.html", error=error, has_users=has_users,
                            needs_terminals=not has_terminals)


@bp.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()
    if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone() or not db.execute(
            "SELECT 1 FROM terminals LIMIT 1").fetchone():
        return redirect(url_for("auth.setup"))
    terminals = db.execute(
        "SELECT id,name,kind FROM terminals WHERE active=1 AND kind IN ('standard','admin') "
        "ORDER BY sort_order,id").fetchall()
    error = ""
    if request.method == "POST":
        login_kind = request.form.get("terminal_kind", "")
        try:
            terminal_id = int(request.form.get("terminal_id", ""))
        except (TypeError, ValueError):
            terminal_id = None
        password = request.form.get("password", "")
        user = None
        if login_kind == "personal":
            terminal = {"id": None, "name": "个人终端", "kind": "personal", "active": 1}
            username = request.form.get("username", "").strip()
            user = db.execute("SELECT * FROM users WHERE username=? AND active=1",
                              (username,)).fetchone()
            if not user or not _check_password(db, user, password, "user"):
                error = "用户名或用户密码不正确"
        else:
            terminal = db.execute("""SELECT * FROM terminals
                WHERE id=? AND active=1 AND kind IN ('standard','admin')""",
                (terminal_id,)).fetchone() if terminal_id else None
            if (not terminal or login_kind not in {"", terminal["kind"]} or
                    not _check_password(db, terminal, password, "terminal")):
                error = "终端或密码不正确"
        if not error:
            session.clear()
            if login_kind == "personal":
                session["personal_user_id"] = user["id"]
            else:
                session["terminal_id"] = terminal["id"]
            g.terminal = terminal
            g.user = user if login_kind == "personal" else None
            actor = user or {"id": None, "username": f"terminal:{terminal['name']}"}
            audit_event(db, "login", "session", terminal["id"] or user["id"], user=actor)
            db.commit()
            return redirect(url_for("index"))
    return render_template("login.html", error=error, terminals=terminals,
                           selected_terminal_id=request.form.get("terminal_id", type=int),
                           selected_terminal_kind=request.form.get("terminal_kind", ""),
                           username=request.form.get("username", "").strip())


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    if getattr(g, "terminal", None):
        db = get_db()
        audit_event(db, "logout", "session", g.terminal["id"])
        db.commit()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.post("/api/authorize")
def authorize():
    data = request.json or {}
    purpose = str(data.get("purpose") or "").strip()
    if purpose and purpose not in CAPABILITIES:
        return jsonify(ok=False, error="授权用途无效"), 400
    if purpose:
        for key in ("forced_authorization_purpose", "forced_authorization_user_id",
                    "forced_authorization_at"):
            session.pop(key, None)
    if g.terminal["kind"] in {"admin", "personal"} and not purpose:
        return jsonify(ok=True, user=_public_user(g.user))
    password = str(data.get("password", ""))
    matches = _matching_users(get_db(), password)
    if len(matches) != 1:
        session.pop("authorized_user_id", None)
        session.pop("last_write", None)
        return jsonify(ok=False, error="用户密码不正确或不唯一"), 401
    user = matches[0]
    if purpose and purpose not in user_permissions(user):
        return jsonify(ok=False, error=f"该用户没有“{CAPABILITIES[purpose]}”权限"), 403
    session["authorized_user_id"] = user["id"]
    session["last_write"] = time.time()
    if purpose:
        session["forced_authorization_purpose"] = purpose
        session["forced_authorization_user_id"] = user["id"]
        session["forced_authorization_at"] = time.time()
    return jsonify(ok=True, user=_public_user(user))


@bp.post("/api/authorization/clear")
def clear_authorization():
    for key in ("authorized_user_id", "last_write", "forced_authorization_purpose",
                "forced_authorization_user_id", "forced_authorization_at"):
        session.pop(key, None)
    return jsonify(ok=True)


@bp.get("/api/users")
@capability_required("user_manage")
def list_users():
    users = get_db().execute("""SELECT id,username,display_name,permissions,active,created_at
        FROM users ORDER BY id""").fetchall()
    result = []
    for user in users:
        item = dict(user)
        item["permissions"] = sorted(user_permissions(user))
        result.append(item)
    return jsonify(result)


@bp.post("/api/users")
@capability_required("user_manage")
def add_user():
    data = request.json or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    permissions = _clean_permissions(data.get("permissions"))
    if len(username) < 3 or not password or permissions is None:
        return jsonify(ok=False, error="用户名至少 3 位、密码不能为空，并请选择有效能力"), 400
    inheritance_error = _permission_inheritance_error(permissions)
    if inheritance_error:
        return jsonify(ok=False, error=inheritance_error, code="permission_inheritance"), 403
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify(ok=False, error="用户名已存在"), 409
    if _password_in_use(db, password):
        return jsonify(ok=False, error="该密码已被其他启用用户使用，请设置唯一密码"), 409
    cur = db.execute("""INSERT INTO users(username,password_hash,display_name,role,permissions)
        VALUES(?,?,?,'custom',?)""", (username, hash_password(password),
                              str(data.get("display_name", "")).strip() or username,
                              json.dumps(sorted(permissions))))
    audit_event(db, "create", "user", cur.lastrowid,
                after={"username": username, "permissions": sorted(permissions)})
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@bp.put("/api/users/<int:user_id>")
@capability_required("user_manage")
def update_user(user_id):
    data = request.json or {}
    db = get_db()
    before = db.execute("SELECT id,username,display_name,role,permissions,active FROM users WHERE id=?",
                        (user_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="用户不存在"), 404
    inheritance_error = _permission_inheritance_error(user_permissions(before))
    if inheritance_error:
        return jsonify(ok=False, error="不能修改权限高于当前用户的账号",
                       code="permission_inheritance"), 403
    username = str(data.get("username", before["username"])).strip()
    if len(username) < 3:
        return jsonify(ok=False, error="用户名至少 3 个字符"), 400
    if get_db().execute("SELECT 1 FROM users WHERE username=? AND id<>?",
                        (username, user_id)).fetchone():
        return jsonify(ok=False, error="用户名已存在"), 409
    permissions = (_clean_permissions(data["permissions"])
                   if "permissions" in data else user_permissions(before))
    active = int(bool(data.get("active", before["active"])))
    if permissions is None:
        return jsonify(ok=False, error="用户能力无效"), 400
    inheritance_error = _permission_inheritance_error(permissions)
    if inheritance_error:
        return jsonify(ok=False, error=inheritance_error, code="permission_inheritance"), 403
    if g.user["id"] is not None and user_id == g.user["id"] and not active:
        return jsonify(ok=False, error="不能停用当前登录账号"), 400
    if "user_manage" in user_permissions(before) and before["active"] and (
            "user_manage" not in permissions or not active):
        managers = [row for row in db.execute(
            "SELECT role,permissions FROM users WHERE active=1 AND id<>?", (user_id,))
                    if "user_manage" in user_permissions(row)]
        if not managers:
            return jsonify(ok=False, error="系统必须至少保留一个具备用户管理能力的启用账号"), 400
    password = str(data.get("password", ""))
    if password and _password_in_use(db, password, user_id):
        return jsonify(ok=False, error="该密码已被其他启用用户使用，请设置唯一密码"), 409
    display_name = str(data.get("display_name", before["display_name"])).strip()
    db.execute("""UPDATE users SET username=?,display_name=?,role='custom',permissions=?,active=?
        WHERE id=?""", (username, display_name, json.dumps(sorted(permissions)), active, user_id))
    if password:
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (hash_password(password), user_id))
    after = db.execute("SELECT id,username,display_name,role,permissions,active FROM users WHERE id=?",
                       (user_id,)).fetchone()
    audit_event(db, "update", "user", user_id, before=before, after=after)
    db.commit()
    return jsonify(ok=True)


@bp.get("/api/terminals")
@capability_required("terminal_manage")
def list_terminals():
    terminals = get_db().execute("""SELECT id,name,kind,active,sort_order,created_at,updated_at
        FROM terminals WHERE kind IN ('standard','admin') ORDER BY sort_order,id""").fetchall()
    return jsonify([dict(terminal) for terminal in terminals])


@bp.post("/api/terminals")
@capability_required("terminal_manage")
def add_terminal():
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    password = str(data.get("password", ""))
    kind = str(data.get("kind", "standard"))
    if not name or kind not in TERMINAL_KINDS:
        return jsonify(ok=False, error="请输入终端名称并选择有效类型"), 400
    if not password:
        return jsonify(ok=False, error="终端密码不能为空"), 400
    db = get_db()
    if db.execute("SELECT 1 FROM terminals WHERE name=?", (name,)).fetchone():
        return jsonify(ok=False, error="终端名称已存在"), 409
    if _terminal_password_in_use(db, password):
        return jsonify(ok=False, error="该密码已被其他启用终端使用，请设置唯一密码"), 409
    sort_order = db.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM terminals").fetchone()[0]
    cur = db.execute("""INSERT INTO terminals(name,password_hash,kind,sort_order)
        VALUES(?,?,?,?)""", (name, hash_password(password), kind, sort_order))
    audit_event(db, "create", "terminal", cur.lastrowid,
                after={"name": name, "kind": kind, "active": 1})
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@bp.put("/api/terminals/<int:terminal_id>")
@capability_required("terminal_manage")
def update_terminal(terminal_id):
    data = request.json or {}
    db = get_db()
    before = db.execute("SELECT id,name,kind,active FROM terminals WHERE id=?",
                        (terminal_id,)).fetchone()
    if not before:
        return jsonify(ok=False, error="终端不存在"), 404
    name = str(data.get("name", before["name"])).strip()
    kind = str(data.get("kind", before["kind"]))
    active = int(bool(data.get("active", before["active"])))
    password = str(data.get("password", ""))
    if not name or kind not in TERMINAL_KINDS:
        return jsonify(ok=False, error="终端名称或类型无效"), 400
    if db.execute("SELECT 1 FROM terminals WHERE name=? AND id<>?",
                  (name, terminal_id)).fetchone():
        return jsonify(ok=False, error="终端名称已存在"), 409
    if before["kind"] == "personal" and kind != "personal" and not password:
        return jsonify(ok=False, error="个人终端切换为密码终端时必须设置终端密码"), 400
    if password and _terminal_password_in_use(db, password, terminal_id):
        return jsonify(ok=False, error="该密码已被其他启用终端使用，请设置唯一密码"), 409
    current_terminal_id = g.terminal["id"] if getattr(g, "terminal", None) else None
    if terminal_id == current_terminal_id and (not active or kind != before["kind"]):
        return jsonify(ok=False, error="不能停用当前终端或修改当前终端的类型"), 400
    if before["kind"] == "admin" and before["active"] and (kind != "admin" or not active):
        active_admins = db.execute(
            "SELECT COUNT(*) FROM terminals WHERE kind='admin' AND active=1").fetchone()[0]
        if active_admins <= 1:
            return jsonify(ok=False, error="系统必须至少保留一个启用的管理终端"), 400
    db.execute("""UPDATE terminals SET name=?,kind=?,active=?,
        updated_at=datetime('now','localtime') WHERE id=?""",
        (name, kind, active, terminal_id))
    if password:
        db.execute("""UPDATE terminals SET password_hash=?,
            updated_at=datetime('now','localtime') WHERE id=?""",
            (hash_password(password), terminal_id))
    after = db.execute("SELECT id,name,kind,active FROM terminals WHERE id=?",
                       (terminal_id,)).fetchone()
    audit_event(db, "update", "terminal", terminal_id, before=before, after=after)
    db.commit()
    return jsonify(ok=True)


@bp.put("/api/terminals/<int:terminal_id>/order")
@capability_required("terminal_manage")
def move_terminal(terminal_id):
    direction = str((request.json or {}).get("direction", ""))
    if direction not in {"up", "down"}:
        return jsonify(ok=False, error="终端排序方向无效"), 400
    db = get_db()
    ordered = db.execute("""SELECT id,name,kind,active,sort_order FROM terminals
        WHERE kind IN ('standard','admin') ORDER BY sort_order,id""").fetchall()
    current_index = next((index for index, item in enumerate(ordered)
                          if item["id"] == terminal_id), None)
    if current_index is None:
        return jsonify(ok=False, error="终端不存在"), 404
    target_index = current_index + (-1 if direction == "up" else 1)
    if target_index < 0 or target_index >= len(ordered):
        return jsonify(ok=True, changed=False)
    before = ordered[current_index]
    target = ordered[target_index]
    for index, item in enumerate(ordered, start=1):
        db.execute("UPDATE terminals SET sort_order=? WHERE id=?", (index, item["id"]))
    db.execute("UPDATE terminals SET sort_order=? WHERE id=?", (target_index + 1, terminal_id))
    db.execute("UPDATE terminals SET sort_order=? WHERE id=?", (current_index + 1, target["id"]))
    after = db.execute("SELECT id,name,kind,active,sort_order FROM terminals WHERE id=?",
                       (terminal_id,)).fetchone()
    audit_event(db, "update", "terminal", terminal_id, before=before, after=after)
    db.commit()
    return jsonify(ok=True, changed=True)


@bp.get("/api/audit")
def list_audit():
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    rows = get_db().execute("""SELECT id,user_id,username,terminal_id,terminal_name,action,
        entity_type,entity_id,reason,before_json,after_json,ip_address,created_at
        FROM audit_logs ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["changes"] = audit_changes(item.get("before_json"), item.get("after_json"))
        result.append(item)
    return jsonify(result)
