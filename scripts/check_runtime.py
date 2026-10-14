import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.ocr import get_engine, model_paths
from backend.browser import launch_browser

if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    paths = model_paths()
    get_engine()
    print("OCR models available locally:")
    inventory = {}
    for kind, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        inventory[kind] = {"filename": path.name, "sha256": digest, "bytes": path.stat().st_size}
        print(kind, path.name, digest)
    (ROOT / "runtime").mkdir(exist_ok=True)
    (ROOT / "runtime" / "models.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "runtime" / "browsers")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        browser.close()
    print("Chromium ready. Runtime requires no model/browser downloads.")
