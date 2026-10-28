"""Resolution-aware fullscreen grids and live PageUp/PageDown changes.

Only tile_rows is mutable during a session. Other configuration remains frozen.
The scheduler owns geometry; each child applies its rectangle on its own thread.
"""
import ctypes
import json
import mmap
import os
from pathlib import Path
import struct
import time

MIN_HEIGHT = 270  # Existing 1080-pixel display divided into four rows.
MAX_TILES = 64
MAX_ROWS = 64
ROW_KEY_MESSAGE = 0x8000 + 216
WM_KEYDOWN = 0x0100
PAGE_UP, PAGE_DOWN = 0x21, 0x22
DEBOUNCE = .18


def configured_rows(cfg):
    value = cfg.get('tile_rows', 0)
    if type(value) is not int or not 0 <= value <= MAX_ROWS:
        print(f'[layout] invalid tile_rows={value!r}; using legacy layout', flush=True)
        return 0
    return value


def resize_keys_enabled(cfg):
    # Carry over the v0.22.1 toggle, without ever assigning the mouse wheel.
    return cfg.get('tile_resize_keys_enabled', cfg.get('tile_wheel_enabled', True)) is True


def refresh_saved_rows(cfg, path):
    """Worker recycle retains live row edits without reloading other settings."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if isinstance(data, dict):
            return dict(cfg, tile_rows=configured_rows(data))
    except (OSError, ValueError) as exc:
        print(f'[layout] cannot reload saved rows: {exc}; keeping snapshot', flush=True)
    return cfg


def save_rows(path, rows):
    """Merge only this field into the latest document under the existing lock."""
    from file_transaction import file_locks
    from settings_store import SettingsDocument
    with file_locks(path):
        return SettingsDocument(path).save({('tile_rows',): rows})


def grids(monitors, rows):
    if not monitors or not 1 <= rows <= MAX_ROWS:
        raise ValueError('A display and positive tile row count are required')
    result = []
    for left, top, right, bottom in monitors:
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise ValueError('Display dimensions must be positive')
        count = min(rows, max(1, height // MIN_HEIGHT))
        # One row deliberately means one fullscreen tile on each monitor.
        cols = 1 if count == 1 else max(1, (width * count * 2 + height) // (2 * height))
        result.append((cols, count))
    return result


def max_rows(monitors, limit=MAX_TILES):
    if not monitors or len(monitors) > limit:
        raise ValueError('Too many displays for the tile limit')
    upper = min(MAX_ROWS, max(max(1, (bottom-top)//MIN_HEIGHT) for _, top, _, bottom in monitors))
    allowed = 1
    for rows in range(1, upper + 1):
        if sum(c*r for c, r in grids(monitors, rows)) > limit:
            break
        allowed = rows
    return allowed


def plan(monitors, origin, requested, gap=0, limit=MAX_TILES):
    from screen_layout import _cell_rect
    rows = min(max(1, requested), max_rows(monitors, limit))
    layout = grids(monitors, rows)
    rects = []
    for (left, top, right, bottom), (cols, count) in zip(monitors, layout):
        width, height = right-left, bottom-top
        left, top = left-origin[0], top-origin[1]
        for row in range(count):
            for col in range(cols):
                rects.append(_cell_rect(left+width*col//cols, top+height*row//count,
                                       left+width*(col+1)//cols, top+height*(row+1)//count, gap))
    return rows, rects, layout


def initial_rows(monitors, origin, rects):
    """Infer the largest row count from legacy grids without changing them."""
    counts = []
    for left, top, right, bottom in monitors:
        ys = {y for x, y, w, h in rects
              if left <= x+origin[0]+w/2 < right and top <= y+origin[1]+h/2 < bottom}
        counts.append(len(ys))
    return max(counts, default=1)


def handle_keys(control, msg, key, lparam=0):
    if control is None or msg not in (WM_KEYDOWN, ROW_KEY_MESSAGE) or key not in (PAGE_UP, PAGE_DOWN):
        return False
    # One physical press changes one row, even if the key is held down.
    if not lparam & (1 << 30):
        control.step(1 if key == PAGE_UP else -1)
    return True


class RowKeyForward:
    def __init__(self, user32, target=lambda: None):
        self.user32, self.target = user32, target

    def step(self, direction):
        hwnd = self.target()
        if hwnd and self.user32.IsWindow(hwnd):
            key = PAGE_UP if direction > 0 else PAGE_DOWN
            if not self.user32.PostMessageW(hwnd, ROW_KEY_MESSAGE, key, 0):
                print('[layout] row key forwarding failed', flush=True)


class Controller:
    def __init__(self, cfg, path, monitors, origin, rects, limit=MAX_TILES, clock=time.monotonic):
        self.cfg, self.path = cfg, Path(path)
        self.monitors, self.origin, self.limit = monitors, origin, limit
        self.gap = max(0, int(cfg.get('gap_pixels', 0)))
        self.clock = clock
        self.upper = max_rows(monitors, limit)
        requested = configured_rows(cfg)
        self.rows = min(self.upper, requested) if requested else max(1, initial_rows(monitors, origin, rects))
        self.pending = self.rows
        self.due = None

    def step(self, steps):
        if steps:
            if steps < 0 or self.pending < self.upper:
                self.pending = min(self.upper, max(1, self.pending + steps))
            self.due = self.clock() + DEBOUNCE

    def take(self, now):
        if self.due is None or now < self.due:
            return None
        self.due = None
        if self.pending == self.rows:
            return None
        rows, rects, layout = plan(self.monitors, self.origin, self.pending, self.gap, self.limit)
        try:
            save_rows(self.path, rows)
        except (OSError, ValueError, RuntimeError) as exc:
            self.pending = self.rows
            print(f'[layout] save failed; layout unchanged: {exc}', flush=True)
            return None
        self.rows = self.pending = rows
        self.cfg['tile_rows'] = rows
        print(f'[layout] saved rows={rows} grids={layout} tiles={len(rects)}', flush=True)
        return rects


# A bounded, sequence-bracketed snapshot. Children never write shared geometry.
_PAYLOAD = struct.Struct('<I' + 'iiii' * MAX_TILES)
_SIZE = _PAYLOAD.size + 8


class Geometry:
    def __init__(self, tag=None):
        self.owner = tag is None
        self.tag = tag or f'Local\\RNSLayout_{os.getpid()}_{time.monotonic_ns()}'
        self.shared = mmap.mmap(-1, _SIZE, tagname=self.tag,
                                access=mmap.ACCESS_WRITE if self.owner else mmap.ACCESS_READ)
        self.sequence = 0

    def publish(self, rects):
        if not self.owner or not 1 <= len(rects) <= MAX_TILES:
            raise ValueError('Invalid shared geometry')
        self.sequence += 2
        seq = self.sequence & 0xfffffffe
        struct.pack_into('<I', self.shared, 0, seq | 1)
        payload = [v for rect in rects for v in rect]
        payload += [0] * (4 * MAX_TILES - len(payload))
        _PAYLOAD.pack_into(self.shared, 4, len(rects), *payload)
        struct.pack_into('<I', self.shared, _SIZE-4, seq)
        struct.pack_into('<I', self.shared, 0, seq)

    def rectangle(self, index):
        first, = struct.unpack_from('<I', self.shared, 0)
        data = self.shared[:]
        begin, = struct.unpack_from('<I', data, 0)
        end, = struct.unpack_from('<I', data, _SIZE-4)
        last, = struct.unpack_from('<I', self.shared, 0)
        if first != begin or begin != end or end != last or begin & 1:
            return None
        count, = struct.unpack_from('<I', data, 4)
        if not 0 <= index < count <= MAX_TILES:
            return None
        return struct.unpack_from('<iiii', data, 8 + index * 16)

    def close(self):
        self.shared.close()


def resize_tile(api, win, geometry, index):
    rect = geometry.rectangle(index)
    if rect is None or tuple(win.embedded_rect) == rect:
        return
    from ctypes import wintypes as W
    move = api.user32.SetWindowPos
    move.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT]
    move.restype = W.BOOL
    if not move(win.hwnd, None, *rect, 0x0004 | 0x0010):  # NOZORDER | NOACTIVATE
        raise ctypes.WinError()
    win.embedded_rect = rect


def resize_slots(slots, next_try, rects, replacement, dispose, now):
    """Keep surviving processes; release excess children before shrinking arrays."""
    for index in range(len(slots)-1, len(replacement)-1, -1):
        dispose(index)  # Confirmed wait/cleanup; failures abort before losing ownership.
    del slots[len(replacement):]
    del next_try[len(replacement):]
    slots.extend([None] * (len(replacement)-len(slots)))
    next_try.extend([now] * (len(replacement)-len(next_try)))
    rects[:] = replacement
