"""SQLite 在线备份与保留策略。"""

import sqlite3
from datetime import datetime
from pathlib import Path


def create_backup(database_path, backup_dir="backups", keep_days=30):
    source_path = Path(database_path).resolve()
    target_dir = Path(backup_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"toy-lims-{datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    cutoff = datetime.now().timestamp() - keep_days * 86400
    for old in target_dir.glob("toy-lims-*.db"):
        if old != target and old.stat().st_mtime < cutoff:
            old.unlink()
    return target
