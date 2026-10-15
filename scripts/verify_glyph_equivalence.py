"""Compare optimized glyphs byte for byte with a Git revision, including warm caches."""
import argparse
import json
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def baseline_module(name, revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:backend/{name}.py'], cwd=ROOT).decode('utf-8')
    module = types.ModuleType(f'backend.before_{name}')
    module.__package__ = 'backend'
    exec(compile(source, f'<{revision}:{name}>', 'exec'), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-ref', default='HEAD')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/glyph-equivalence')
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options', f'{args.baseline_ref}^{{commit}}'], cwd=ROOT).decode().strip()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['RESUME_GLYPH_CACHE_DIR'] = str(output/'cache')
    from playwright.sync_api import sync_playwright
    from backend import image_layout, browser_typography
    from backend.browser import launch_browser
    from backend.glyph_cache import flush_caches
    from backend.typography import LATIN_CHOICES
    original_pillow = baseline_module('image_layout', revision)
    original_browser = baseline_module('browser_typography', revision)
    choices = [(f'{latin[0]}, {chinese[0]}', *chinese[1:3], *latin[1:]) for chinese in image_layout.FONT_CHOICES for latin in LATIN_CHOICES]
    requests = [(char, choice, bold, size, antialias) for choice in choices for char in '中永体简历Aa09'
                for bold in (False, True) for size in (8, 8.5, 12, 17.5, 22.5, 30, 48) for antialias in (False, True)]
    expected = [original_pillow.render_glyph(*request) for request in requests]
    def compare_pillow():
        for request, old in zip(requests, expected):
            new = image_layout.render_glyph(*request)
            if old is None:
                assert new is None, request
            else:
                assert new is not None and old.dtype == new.dtype and old.shape == new.shape and old.tobytes() == new.tobytes(), request
    image_layout._render_glyph.cache_clear()
    compare_pillow()
    flush_caches()
    image_layout._render_glyph.cache_clear()
    compare_pillow()
    browser_requests = [[family, char, weight, size, resolution] for family in dict.fromkeys(browser_typography.FAMILIES.values())
                        for char in '中永体简历Aa09' for weight in (400, 700)
                        for size in (8, 8.5, 12, 17.5, 22.5, 30, 48) for resolution in (1, 1.5, 2)]
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            tab = browser.new_page()
            tab.route('**/*', lambda route: route.abort())
            old = tab.evaluate(original_browser.RENDER_GLYPHS, browser_requests)
            new = tab.evaluate(browser_typography.RENDER_GLYPHS, browser_requests)
            assert old == new, 'Browser glyph pixels changed'
        finally:
            browser.close()
    report = {'baselineRevision': revision, 'pillowGlyphCases': len(requests),
              'browserGlyphCases': len(browser_requests), 'coldAndWarmPixelsIdentical': True}
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
