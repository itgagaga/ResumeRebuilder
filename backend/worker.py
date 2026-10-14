"""Isolate untrusted source parsing from the API process; caller imposes a wall-clock timeout."""
import json
import sys
from pathlib import Path

from .config import AppError
from .parser import import_source

if __name__ == "__main__":
    path = Path(sys.argv[1])
    try:
        project = import_source(path.read_bytes(), sys.argv[2], sys.argv[4])
        result = {"project": project.model_dump()}
    except AppError as exc:
        result = {"error": exc.message}
    except Exception:
        result = {"error": "文件处理失败，请检查输入文件"}
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
