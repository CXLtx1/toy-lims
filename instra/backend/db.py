"""Read-only PostgreSQL connection for the standalone instrument site."""

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from db_backend import connect_database  # noqa: E402

DATABASE_URL = (os.environ.get("INSTA_DATABASE_URL") or
                os.environ.get("LIMS_DATABASE_URL") or "").strip()


def connect():
    """新建一个只读连接（调用方负责 close）。

    只读站开 autocommit：避免每条 SELECT 挂起事务变成 idle in transaction
    （toy-lims 曾因此阻塞 VACUUM）；会话级只读做双保险。
    """
    if not DATABASE_URL:
        raise RuntimeError("Configure INSTA_DATABASE_URL or LIMS_DATABASE_URL")
    connection = connect_database(DATABASE_URL)
    try:
        # Finish the timezone setup transaction before enabling autocommit.
        connection.commit()
        connection.autocommit = True
        connection.execute("SET default_transaction_read_only=on")
    except Exception:
        connection.close()
        raise
    return connection
