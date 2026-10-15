"""Optional, bounded cache of system-font glyphs; never stores document crops."""
import atexit
import hashlib
import json
import os
import platform
import sqlite3
import struct
import threading
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import RUNTIME

MISS = object()
MAX_ENTRY = 256 * 1024
MAX_DATABASE = 128 * 1024 * 1024
DTYPES = {b'u': np.dtype('uint8'), b'b': np.dtype('bool'), b'f': np.dtype('float32')}


@lru_cache(maxsize=1)
def font_environment():
    roots = [Path('C:/Windows/Fonts'), Path(os.environ.get('LOCALAPPDATA', ''))/'Microsoft/Windows/Fonts'] if os.name == 'nt' else [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'), Path.home()/'.local/share/fonts', Path.home()/'.fonts']
    fonts = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*')):
            if path.suffix.lower() not in {'.ttf', '.ttc', '.otf', '.otc'}:
                continue
            stat = path.stat()
            fonts.append((str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return hashlib.sha256(json.dumps([platform.platform(), fonts]).encode()).hexdigest()


def encode(value):
    if value is None:
        return zlib.compress(b'n', 1)
    value = np.asarray(value)
    code = next((key for key, dtype in DTYPES.items() if value.dtype == dtype), None)
    if code is None or value.ndim != 2 or not value.size or value.nbytes > MAX_ENTRY - 5 or max(value.shape) > 2048:
        return None
    return zlib.compress(struct.pack('!cHH', code, *value.shape) + value.tobytes(), 1)


def decode(payload):
    inflater = zlib.decompressobj()
    raw = inflater.decompress(payload, MAX_ENTRY + 1)
    if len(raw) > MAX_ENTRY or not inflater.eof or inflater.unused_data:
        raise ValueError('Invalid cached glyph')
    if raw == b'n':
        return None
    code, height, width = struct.unpack('!cHH', raw[:5])
    dtype = DTYPES[code]
    if not height or not width or max(height, width) > 2048 or len(raw) != 5 + height * width * dtype.itemsize:
        raise ValueError('Invalid cached glyph dimensions')
    return np.frombuffer(raw, dtype=dtype, offset=5).reshape(height, width).copy()


class GlyphCache:
    def __init__(self, directory, identity):
        self.directory, self.identity = directory, identity
        self.connection = None
        self.failed = directory is None
        self.pending = {}
        self.lock = threading.RLock()

    def connect(self):
        if self.failed:
            return None
        if self.connection is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.directory/'glyphs.sqlite3', timeout=.1, check_same_thread=False)
            self.connection.execute('PRAGMA journal_mode=WAL')
            self.connection.execute('PRAGMA synchronous=NORMAL')
            self.connection.execute('CREATE TABLE IF NOT EXISTS glyphs (key BLOB PRIMARY KEY, value BLOB NOT NULL)')
        return self.connection

    def key(self, key):
        return hashlib.sha256(json.dumps([self.identity, key], ensure_ascii=True, separators=(',', ':')).encode()).digest()

    def get_many(self, keys):
        if self.failed or not keys:
            return {}
        with self.lock:
            try:
                connection = self.connect()
                hashes = {self.key(key): key for key in keys}
                found = {key: self.pending[key] for key in hashes if key in self.pending}
                missing = [key for key in hashes if key not in found]
                for start in range(0, len(missing), 400):
                    batch = missing[start:start+400]
                    found.update(connection.execute(f'SELECT key,value FROM glyphs WHERE key IN ({",".join("?" for _ in batch)})', batch))
                values = {}
                for key, payload in found.items():
                    try:
                        values[hashes[key]] = decode(payload)
                    except (ValueError, KeyError, struct.error, zlib.error):
                        pass
                return values
            except (OSError, sqlite3.Error):
                self.failed = True
                return {}

    def get(self, key):
        if self.failed:
            return MISS
        with self.lock:
            try:
                digest = self.key(key)
                payload = self.pending.get(digest)
                if payload is None:
                    row = self.connect().execute('SELECT value FROM glyphs WHERE key=?', (digest,)).fetchone()
                    if row is None:
                        return MISS
                    payload = row[0]
                try:
                    return decode(payload)
                except (ValueError, KeyError, struct.error, zlib.error):
                    return MISS
            except (OSError, sqlite3.Error):
                self.failed = True
                return MISS

    def put_many(self, values):
        if self.failed:
            return
        with self.lock:
            try:
                for key, value in values.items():
                    payload = encode(value)
                    if payload is not None:
                        self.pending[self.key(key)] = payload
                if len(self.pending) >= 512:
                    self.flush()
            except (OSError, sqlite3.Error):
                self.failed = True
                self.pending.clear()

    def put(self, key, value):
        self.put_many({key: value})

    def flush(self):
        if self.failed or not self.pending:
            return
        with self.lock:
            try:
                connection = self.connect()
                with connection:
                    connection.executemany('INSERT OR REPLACE INTO glyphs VALUES (?,?)', self.pending.items())
                    page_size = connection.execute('PRAGMA page_size').fetchone()[0]
                    pages = connection.execute('PRAGMA page_count').fetchone()[0]
                    free = connection.execute('PRAGMA freelist_count').fetchone()[0]
                    while (pages-free)*page_size > MAX_DATABASE:
                        connection.execute('DELETE FROM glyphs WHERE rowid IN (SELECT rowid FROM glyphs ORDER BY rowid LIMIT 4096)')
                        free = connection.execute('PRAGMA freelist_count').fetchone()[0]
                self.pending.clear()
            except (OSError, sqlite3.Error):
                self.failed = True
                self.pending.clear()


_caches = {}


def get_cache(renderer):
    directory = os.environ.get('RESUME_GLYPH_CACHE_DIR', str(RUNTIME/'glyph-cache'))
    if os.environ.get('RESUME_GLYPH_CACHE') == '0':
        directory = None
    key = (directory, renderer)
    if key not in _caches:
        try:
            identity = (renderer, font_environment())
        except OSError:
            directory, identity = None, renderer
        _caches[key] = GlyphCache(Path(directory) if directory else None, identity)
    return _caches[key]


def flush_caches():
    for cache in list(_caches.values()):
        cache.flush()


atexit.register(flush_caches)
