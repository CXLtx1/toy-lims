"""insta 正式运行入口：Waitress。

环境变量：
  INSTA_DATABASE_URL / LIMS_DATABASE_URL  PostgreSQL 连接串（缺省用 db.py 写死的内网配置）
  INSTA_HOST / INSTA_PORT                 监听地址（默认 127.0.0.1:5100）
  INSTA_THREADS                           Waitress 线程数（默认 16）
"""

import os

from waitress import serve

from app import app


def main():
    host = os.environ.get("INSTA_HOST", "127.0.0.1")
    port = int(os.environ.get("INSTA_PORT", "5100"))
    threads = max(int(os.environ.get("INSTA_THREADS", "16")), 4)
    print(f"insta 正式服务启动：http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
