"""Production Waitress entry point."""

import os
import threading

import app as lims
from db_backend import connect_database


def warm_report_cache():
    """启动后台预热：把已有样品的报告 payload 都算好缓存，首次展开即秒开。"""
    try:
        connection = connect_database(lims.database_target())
    except Exception:
        print("[报告缓存预热] 数据库连接失败", flush=True)
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
    except Exception:
        print("[报告缓存预热] 中断", flush=True)
    finally:
        connection.close()


def main():
    lims.database_target()
    from waitress import serve

    try:
        lims.init_db()
    except Exception:
        raise SystemExit("Database initialization failed; check external database configuration") from None
    host = os.environ.get("LIMS_HOST", "127.0.0.1")
    port = int(os.environ.get("LIMS_PORT", "5000"))
    # 每个浏览器的 SSE 协同推送连接会常驻占用一个线程，线程数需要留出余量。
    threads = max(int(os.environ.get("LIMS_THREADS", "32")), 8)
    print(f"toy-lims 正式服务启动：http://{host}:{port}", flush=True)
    threading.Thread(target=warm_report_cache, name="lims-report-warmup", daemon=True).start()
    trust_proxy = os.environ.get("LIMS_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}
    if trust_proxy:
        # Waitress accepts one proxy address, not a comma-separated list.
        # Keep the backend inaccessible except through that trusted proxy.
        serve(lims.app, host=host, port=port, threads=threads,
              trusted_proxy=os.environ.get("LIMS_TRUSTED_PROXY", "127.0.0.1"),
              trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"})
    else:
        serve(lims.app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
