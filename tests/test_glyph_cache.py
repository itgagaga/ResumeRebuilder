import zlib

import numpy as np
import pytest

from backend.glyph_cache import GlyphCache, MISS, MAX_ENTRY, encode, decode, flush_caches


@pytest.mark.parametrize('value', [None, np.arange(35, dtype=np.uint8).reshape(5, 7),
                                  np.array([[True, False], [False, True]]),
                                  np.arange(35, dtype=np.float32).reshape(5, 7)/255])
def test_glyph_pixels_survive_a_new_cache_instance(tmp_path, value):
    key = ('Microsoft YaHei', '字', 700, 18.5)
    cold = GlyphCache(tmp_path, ('renderer-v1', 'fonts-v1'))
    assert cold.get(key) is MISS
    cold.put(key, value)
    cold.flush()
    warm = GlyphCache(tmp_path, ('renderer-v1', 'fonts-v1')).get(key)
    if value is None:
        assert warm is None
    else:
        assert warm.dtype == value.dtype
        assert warm.shape == value.shape
        assert warm.tobytes() == value.tobytes()


def test_font_or_renderer_change_cannot_reuse_old_glyphs(tmp_path):
    key = ('SimSun', '字', 400, 20)
    original = GlyphCache(tmp_path, ('renderer-v1', 'fonts-v1'))
    original.put(key, np.ones((4, 4), dtype=np.uint8))
    original.flush()
    assert GlyphCache(tmp_path, ('renderer-v2', 'fonts-v1')).get(key) is MISS
    assert GlyphCache(tmp_path, ('renderer-v1', 'fonts-v2')).get(key) is MISS


@pytest.mark.parametrize('payload', [b'not-zlib', zlib.compress(b'f\x00\x04\x00\x04bad'),
                                    zlib.compress(b'x'*(MAX_ENTRY+1))])
def test_invalid_glyph_is_a_cache_miss(tmp_path, payload):
    cache = GlyphCache(tmp_path, 'renderer')
    key = ('A', 20)
    connection = cache.connect()
    with connection:
        connection.execute('INSERT INTO glyphs VALUES (?,?)', (cache.key(key), payload))
    assert cache.get(key) is MISS
    value = np.full((8, 6), 255, dtype=np.uint8)
    cache.put(key, value)
    cache.flush()
    assert np.array_equal(GlyphCache(tmp_path, 'renderer').get(key), value)


def test_unwritable_or_corrupt_database_keeps_computation_available(tmp_path):
    blocked = tmp_path/'file'
    blocked.write_bytes(b'not-a-directory')
    cache = GlyphCache(blocked, 'renderer')
    assert cache.get(('A', 20)) is MISS
    cache.put(('A', 20), np.ones((4, 4), dtype=np.uint8))
    cache.flush()
    corrupt = tmp_path/'corrupt'
    corrupt.mkdir()
    (corrupt/'glyphs.sqlite3').write_bytes(b'not-a-database')
    assert GlyphCache(corrupt, 'renderer').get(('A', 20)) is MISS


def test_oversized_glyph_is_not_persisted():
    assert encode(np.zeros((1024, 1024), dtype=np.float32)) is None
    with pytest.raises(ValueError):
        decode(zlib.compress(b'x'*(MAX_ENTRY+1)))


def test_cache_size_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.glyph_cache.MAX_DATABASE', 16*1024)
    cache = GlyphCache(tmp_path, 'renderer')
    random = np.random.default_rng(17)
    cache.put_many({('A', i): random.integers(0, 256, (32, 32), dtype=np.uint8) for i in range(100)})
    cache.flush()
    connection = cache.connect()
    page_size = connection.execute('PRAGMA page_size').fetchone()[0]
    pages = connection.execute('PRAGMA page_count').fetchone()[0]
    free = connection.execute('PRAGMA freelist_count').fetchone()[0]
    assert (pages-free)*page_size <= 16*1024


def test_pillow_reuses_exact_pixels_after_memory_cache_is_cleared(monkeypatch):
    from backend import image_layout
    if image_layout.load_font('arial.ttf', 40) is None:
        pytest.skip('System font unavailable')
    image_layout._render_glyph.cache_clear()
    cold = image_layout.render_glyph('A', image_layout.FONT_CHOICES[0], False, 19.5, True)
    flush_caches()
    image_layout._render_glyph.cache_clear()
    def unexpected_render(*args, **kwargs):
        raise AssertionError('The identical cached glyph should be reused')
    monkeypatch.setattr(image_layout.ImageDraw, 'Draw', unexpected_render)
    warm = image_layout.render_glyph('A', image_layout.FONT_CHOICES[0], False, 19.5, True)
    assert warm.tobytes() == cold.tobytes()


def test_browser_reuses_glyphs_without_skipping_any_font_candidate(tmp_path, monkeypatch):
    import base64
    from contextlib import nullcontext
    from backend import browser_typography
    from backend.image_layout import FONT_CHOICES
    text = '可缓存文字'
    words = [(char, .99, [[i*20, 0], [i*20+18, 0], [i*20+18, 22], [i*20, 22]]) for i, char in enumerate(text)]
    rows = [(np.array([[0, 0], [120, 0], [120, 22], [0, 22]]), text, .99, words)]
    analyses = [(FONT_CHOICES[0], 20, 400, (np.zeros((22, 120), bool), np.array([255]*3), (0, 0, 120, 22)), {})]
    calls = []
    class Tab:
        def route(self, *args): pass
        def evaluate(self, script, requests):
            calls.append(requests)
            return [[3, 3, base64.b64encode(bytes([255]*9)).decode()]]*len(requests)
    class Browser:
        version = 'test-cache-browser-v1'
        def new_page(self): return Tab()
        def close(self): pass
    monkeypatch.setattr('playwright.sync_api.sync_playwright', lambda: nullcontext(None))
    monkeypatch.setattr('backend.browser.launch_browser', lambda _: Browser())
    monkeypatch.setattr(browser_typography, 'match_typography', lambda *args, **kwargs: analyses[0])
    monkeypatch.setattr(browser_typography, 'smooth_typography', lambda values, **kwargs: values)
    _, cold = browser_typography.refine_typography(np.full((40, 120, 3), 255, np.uint8), rows, analyses)
    assert calls
    calls.clear()
    _, warm = browser_typography.refine_typography(np.full((40, 120, 3), 255, np.uint8), rows, analyses)
    assert not calls
    for choice in FONT_CHOICES:
        for char in text:
            for bold in (False, True):
                old, new = cold(char, choice, bold, 20), warm(char, choice, bold, 20)
                assert len(old) == len(new) == 3
                assert all(np.array_equal(a, b) for a, b in zip(old, new))
