"""正式运行入口：Waitress；SQLite 模式附带每日在线备份。"""

import os
import threading
from datetime import datetime
from pathlib import Path
from time import sleep

import app as lims
from db_backend import connect_database
from maintenance import create_backup


def warm_report_cache():
    """启动后台预热：把已有样品的报告 payload 都算好缓存，首次展开即秒开。"""
    try:
        connection = connect_database(lims.DB)
    except Exception as exc:
        print(f"[报告缓存预热] 数据库连接失败：{exc}", flush=True)
        return
    try:
        rows = connection.execute("SELECT id FROM samples ORDER BY id").fetchall()
        done = 0
        for row in rows:
            try:
                lims.cached_report_payload(connection, row[0])
                done += 1
            except Exception:
                continue  # 单个样品失败不影响预热其他样品
        print(f"[报告缓存预热] 完成：{done}/{len(rows)} 个样品", flush=True)
    except Exception as exc:
        print(f"[报告缓存预热] 中断：{exc}", flush=True)
    finally:
        connection.close()


def backup_loop():
    backup_hour = min(max(int(os.environ.get("LIMS_BACKUP_HOUR", "2")), 0), 23)
    keep_days = max(int(os.environ.get("LIMS_BACKUP_KEEP_DAYS", "30")), 1)
    backup_dir = os.environ.get("LIMS_BACKUP_DIR", str(lims.BASE_DIR / "backups"))
    today_pattern = f"toy-lims-{datetime.now():%Y%m%d}-*.db"
    last_day = datetime.now().date() if any(Path(backup_dir).glob(today_pattern)) else None
    while True:
        now = datetime.now()
        if now.hour >= backup_hour and now.date() != last_day:
            try:
                target = create_backup(lims.DB, backup_dir, keep_days)
                print(f"[{now:%Y-%m-%d %H:%M:%S}] 数据库备份完成：{target}", flush=True)
                last_day = now.date()
            except Exception as exc:  # 后台任务失败不能终止 Web 服务
                print(f"[{now:%Y-%m-%d %H:%M:%S}] 数据库备份失败：{exc}", flush=True)
        sleep(60)


def main():
    from waitress import serve

    lims.init_db()
    if not lims.is_postgres_database(lims.DB):
        threading.Thread(target=backup_loop, name="lims-backup", daemon=True).start()
    host = os.environ.get("LIMS_HOST", "127.0.0.1")
    port = int(os.environ.get("LIMS_PORT", "5000"))
    # 每个浏览器的 SSE 协同推送连接会常驻占用一个线程，线程数需要留出余量。
    threads = max(int(os.environ.get("LIMS_THREADS", "32")), 8)
    print(f"toy-lims 正式服务启动：http://{host}:{port}", flush=True)
    threading.Thread(target=warm_report_cache, name="lims-report-warmup", daemon=True).start()
    trust_proxy = os.environ.get("LIMS_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}
    if trust_proxy:
        # waitress 3.x 默认剥离“不可信来源”的 X-Forwarded-* 头（clear_untrusted_proxy_headers），
        # 且 trusted_proxy_headers 默认只放行 x-forwarded-proto；反代部署时必须显式信任本机
        # nginx 转发来的 X-Forwarded-For/Proto，否则 app.py 里的 ProxyFix 拿不到 XFF，
        # 审计记录的 IP 永远是 127.0.0.1。
        serve(lims.app, host=host, port=port, threads=threads,
              trusted_proxy="127.0.0.1,::1",
              trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"})
    else:
        serve(lims.app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
