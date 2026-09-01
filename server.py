"""兼容启动入口；真正的服务端代码位于 server/。"""

import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    server_dir = Path(__file__).resolve().parent / "server"
    sys.path.insert(0, str(server_dir))
    runpy.run_path(str(server_dir / "run.py"), run_name="__main__")
