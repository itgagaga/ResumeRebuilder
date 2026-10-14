"""Prefer a bundled Chromium, with an installed Chromium browser as an offline fallback."""
import os
import sys
from pathlib import Path

from .config import RUNTIME


def system_browser():
    explicit = os.environ.get("RESUME_BROWSER_PATH")
    candidates = [Path(explicit)] if explicit else []
    if sys.platform == "win32":
        candidates.extend([Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
                           Path("C:/Program Files/Google/Chrome/Application/chrome.exe")])
    return next((path for path in candidates if path.is_file()), None)


def bundled_browser_ready():
    root = RUNTIME / "browsers"
    return any(root.glob("chromium-*/chrome-win*/chrome.exe")) or any(root.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe")) or any(root.glob("chromium-*/chrome-linux*/chrome"))


def browser_ready():
    return bundled_browser_ready() or system_browser() is not None


def launch_browser(playwright):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(RUNTIME / "browsers"))
    if bundled_browser_ready():
        # channel=chromium uses the regular browser if only the full Chromium exists.
        if any((RUNTIME / "browsers").glob("chromium_headless_shell-*")):
            return playwright.chromium.launch(headless=True)
        return playwright.chromium.launch(headless=True, channel="chromium")
    executable = system_browser()
    if executable:
        return playwright.chromium.launch(headless=True, executable_path=str(executable))
    return playwright.chromium.launch(headless=True)
