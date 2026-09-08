"""insta 后端应用工厂：只读 API + 前端静态托管（生产模式）。

开发时前端走 Vite dev server 代理 /api；生产时 Flask 直接托管 frontend/dist。
"""

import json
from pathlib import Path

from flask import Flask, g, jsonify, send_from_directory

import db as db_module
from api import exports, overview, samples, xrf

DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app():
    app = Flask(__name__, static_folder=None)

    @app.before_request
    def open_db():
        # 只给 API 请求建连接，静态资源不碰数据库
        from flask import request
        if request.path.startswith("/api/"):
            g.db = db_module.connect()

    @app.teardown_request
    def close_db(exc):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.errorhandler(Exception)
    def on_error(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("API 异常")
        return jsonify(ok=False, error=f"服务端错误：{exc}"), 500

    app.register_blueprint(samples.bp, url_prefix="/api")
    app.register_blueprint(overview.bp, url_prefix="/api")
    app.register_blueprint(xrf.bp, url_prefix="/api")
    app.register_blueprint(exports.bp, url_prefix="/api")

    @app.get("/api/health")
    def health():
        g.db.execute("SELECT 1")
        return jsonify(ok=True, service="insta")

    @app.get("/api/order-templates")
    def order_templates():
        rows = g.db.execute("""SELECT id,name,items_json,is_default
            FROM result_order_templates ORDER BY is_default DESC, id""").fetchall()
        return jsonify(ok=True, items=[{
            "id": row["id"], "name": row["name"], "is_default": bool(row["is_default"]),
            "items": json.loads(row["items_json"] or "[]"),
        } for row in rows])

    # ---- 前端静态托管（生产：已构建的 dist 存在时）----
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if not DIST_DIR.is_dir():
            return jsonify(ok=False, error="前端未构建：请先 npm run build，或使用 Vite dev server"), 404
        target = DIST_DIR / path
        if path and target.is_file():
            # 哈希资源可长缓存
            resp = send_from_directory(DIST_DIR, path)
            if path.startswith("assets/"):
                resp.cache_control.public = True
                resp.cache_control.max_age = 31536000
                resp.cache_control.immutable = True
            return resp
        # index.html 永不缓存，保证发版后浏览器立刻拿到新入口
        resp = send_from_directory(DIST_DIR, "index.html")
        resp.cache_control.no_store = True
        return resp

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5100, debug=True)
