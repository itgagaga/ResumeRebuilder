import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("RESUME_DATA_DIR", ROOT / "projects"))
RUNTIME = ROOT / "runtime"
MAX_UPLOAD = 25 * 1024 * 1024
MAX_PIXELS = 30_000_000
MAX_PAGES = 20


class AppError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status
