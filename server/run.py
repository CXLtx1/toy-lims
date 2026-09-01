"""正式运行入口：Waitress；SQLite 模式附带每日在线备份。"""

import os
import threading
from datetime import datetime
from pathlib import Path
from time import sleep

import app as lims
from maintenance import create_backup


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
    print(f"toy-lims 正式服务启动：http://{host}:{port}", flush=True)
    serve(lims.app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
