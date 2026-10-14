"""Start the local editor with: python run.py."""
import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser(description="启动 Resume Rebuilder 本地编辑器")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    options = parser.parse_args()
    executable = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file() or not (ROOT / "frontend/dist/index.html").is_file():
        print("请先在项目目录运行 setup.ps1，安装依赖并构建前端。", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "runtime/browsers")
    print(f"Resume Rebuilder: {URL}\n保持此窗口打开，按 Ctrl+C 停止服务。", flush=True)
    timer = None
    if not options.no_browser:
        timer = threading.Timer(1.5, lambda: webbrowser.open(URL))
        timer.daemon = True
        timer.start()
    try:
        return subprocess.call([str(executable), "-m", "backend.main"], cwd=ROOT, env=environment)
    except KeyboardInterrupt:
        return 0
    finally:
        if timer:
            timer.cancel()


if __name__ == "__main__":
    sys.exit(main())
