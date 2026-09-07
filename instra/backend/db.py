"""数据库连接：仅 PostgreSQL，只读用途。

地址优先级：INSTA_DATABASE_URL > LIMS_DATABASE_URL > 下方写死的默认配置
（与 toy-lims app.py 的 POSTGRES_CONFIG 同一套，内网部署可直接用）。
连接封装复用 server/db_backend.py（? 占位符风格、Row 字典访问）。
"""

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from db_backend import connect_database, postgres_dsn  # noqa: E402

# 默认连接（与 toy-lims 同库）；内网部署可直接用，环境变量优先。
POSTGRES_CONFIG = {
    "host": "192.168.2.4",
    "port": 5432,
    "database": "toy_lims",
    "user": "cxltx",
    "password": "qwe123qwe123",
}

DATABASE_URL = (os.environ.get("INSTA_DATABASE_URL") or
                os.environ.get("LIMS_DATABASE_URL") or "").strip() or postgres_dsn(POSTGRES_CONFIG)


def connect():
    """新建一个只读连接（调用方负责 close）。

    只读站开 autocommit：避免每条 SELECT 挂起事务变成 idle in transaction
    （toy-lims 曾因此阻塞 VACUUM）；会话级只读做双保险。
    """
    connection = connect_database(DATABASE_URL)
    try:
        # db_backend 建连时已 SET TIME ZONE（处于事务中），先提交才能切 autocommit
        connection.commit()
        connection.raw.autocommit = True
        connection.execute("SET default_transaction_read_only=on")
    except Exception:
        connection.close()
        raise
    return connection
