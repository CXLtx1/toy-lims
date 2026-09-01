"""供 Windows 任务计划程序或管理员手动执行的一次性备份。"""

import os

import app as lims
from maintenance import create_backup


if __name__ == "__main__":
    if lims.is_postgres_database(lims.DB):
        raise SystemExit("当前使用 PostgreSQL；请在数据库服务器使用 pg_dump 或快照备份。")
    target = create_backup(
        lims.DB,
        os.environ.get("LIMS_BACKUP_DIR", str(lims.BASE_DIR / "backups")),
        int(os.environ.get("LIMS_BACKUP_KEEP_DAYS", "30")),
    )
    print(target)
