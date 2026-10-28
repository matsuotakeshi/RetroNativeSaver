"""Small keyboard UI for independent tiles; native core processes stay isolated."""
from collections import deque
import ctypes
import mmap
import os
import struct
import time

LEFT, UP, RIGHT, DOWN, INSERT, DELETE = 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E
ENTER = 0x0D
KEYS = (LEFT, UP, RIGHT, DOWN, INSERT, DELETE, ENTER)
KEY_MESSAGE = 0x8000 + 215
TIMEOUT = 5.0
STATE = struct.Struct('<IiidI')  # matching sequence numbers bracket the payload
NORMAL, ADDED, EXISTS, BLOCKED, ERROR, REMOVED = range(6)
LAUNCH_ERROR = 6


def enabled(cfg):
    return bool(cfg.get('saver_controls_enabled', False) and cfg.get('independent_slots_enabled', False))


def handle_message(control, msg, key, lparam):
    if control is None or msg not in (0x0100, KEY_MESSAGE) or key not in KEYS:
        return False
    repeat = bool(lparam & (1 << 30))
    # One-shot actions must not repeat on a replacement ROM while held down.
    if key not in (UP, DOWN, INSERT, DELETE, ENTER) or not repeat:
        return control.key(key) is not False
    return True


class ForwardKeys:
    def __init__(self, user32, target=lambda: None):
        self.user32, self.target = user32, target

    def key(self, key):
        hwnd = self.target()
        if hwnd and self.user32.IsWindow(hwnd):
            if self.user32.PostMessageW(hwnd, KEY_MESSAGE, key, 0):
                return True
            else:
                print('[saver-control] key forwarding failed', flush=True)
        return False if key == ENTER else None


def window_for_process(user32, pid):
    """Only route to the currently owned worker PID and our window class."""
    if not pid:
        return None
    from ctypes import wintypes as wt
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    found = []
    @callback_type
    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            name = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, name, len(name))
            if name.value == 'RetroNativeSaverWindow':
                found.append(hwnd)
                return False
        return True
    user32.EnumWindows(visit, 0)
    return found[0] if found else None


class Selection:
    """Selection follows a tile position; queued actions bind to its exact process."""
    def __init__(self, slots, clock=time.monotonic):
        self.slots, self.clock = slots, clock
        self.index, self.until, self.status = None, 0., NORMAL
        self.actions = deque()
        self.favorite_skip = None  # previous favorite for a single manual refill

    def visible(self, now):
        if now >= self.until:
            self.index = None
        return self.index

    def key(self, key):
        now = self.clock()
        if key in (UP, DOWN):
            # Global action, including loading/empty tiles; no selection needed.
            if not any(k == key for k, _, _ in self.actions):
                self.actions.append((key, None, None))
            self.index, self.until, self.status = None, 0., NORMAL
            return
        selected = self.visible(now)
        ready = [i for i, r in enumerate(self.slots) if r is not None and r['ready']]
        if key == ENTER and selected not in ready:
            return False  # Enter without a visible/live selection still exits.
        if key in (LEFT, RIGHT):
            if not ready:
                return
            if selected not in ready:
                self.index = ready[0]
            else:
                self.index = ready[(ready.index(selected) + (1 if key == RIGHT else -1)) % len(ready)]
            self.status = NORMAL
        elif selected is not None:
            record = self.slots[selected]
            if record is not None and record['ready']:
                if not any(k == key and i == selected and r is record for k, i, r in self.actions):
                    self.actions.append((key, selected, record))
        else:
            return  # Delete/Insert alone never start an invisible selection.
        self.until = now + TIMEOUT


class SchedulerControls(Selection):
    def __init__(self, slots):
        super().__init__(slots)
        self.tag = f'RNS_Selection_{os.getpid()}_{time.monotonic_ns()}'
        self.shared = mmap.mmap(-1, STATE.size, tagname=self.tag)
        self.sequence = 0
        self.publish()

    def publish(self):
        index = self.visible(self.clock())
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        self.shared[:] = STATE.pack(self.sequence, -1 if index is None else index,
                                   self.status, self.until, self.sequence)

    def close(self):
        self.shared.close()


class TileControls(ForwardKeys):
    def __init__(self, api, spec):
        super().__init__(api.user32, lambda: spec['parent'])
        self.index = spec['index']
        self.shared = mmap.mmap(-1, STATE.size, tagname=spec['selection_tag'], access=mmap.ACCESS_READ)

    def draw(self, api, win):
        sequence, index, status, until, end = STATE.unpack(self.shared[:])
        if sequence != end or index != self.index or time.monotonic() >= until:
            return
        from gdi_safety import checked
        width, height = win.client_size()
        thickness = min(5, max(1, min(width, height)//2))
        color = 0x4040FF if status in (ERROR, LAUNCH_ERROR) else 0x00D7FF
        brush = checked('GetStockObject', api.gdi32.GetStockObject, 18)  # borrowed DC_BRUSH
        old = checked('SetDCBrushColor', api.gdi32.SetDCBrushColor, win.mem_dc, color,
                      invalid=(None, -1, 0xFFFFFFFF))
        try:
            for x1, y1, x2, y2 in ((0,0,width,thickness), (0,height-thickness,width,height),
                                   (0,0,thickness,height), (width-thickness,0,width,height)):
                rect = api.RECT(x1,y1,x2,y2)
                checked('FillRect', api.user32.FillRect, win.mem_dc, ctypes.byref(rect), brush)
        finally:
            checked('SetDCBrushColor', api.gdi32.SetDCBrushColor, win.mem_dc, old,
                    invalid=(None, -1, 0xFFFFFFFF))
        delete_label = 'お気に入り解除' if self.index == 0 else '除外'
        label = {ADDED:'お気に入り登録済み', EXISTS:'お気に入り登録済み',
                 BLOCKED:'ブラックリスト登録済み', REMOVED:'お気に入り解除済み',
                 ERROR:'保存失敗：ログを確認', LAUNCH_ERROR:'RetroArch起動準備失敗：ログを確認'}.get(status,
                 f'←→ 選択 / Enter RetroArchで起動\n↑ モード再抽選 / ↓ お気に入り入替 / Del {delete_label} / Ins 登録')
        top, _, bottom = label.partition('\n')
        color = '#FF4040' if status in (ERROR, LAUNCH_ERROR) else '#FFD700'
        win.draw_overlay(top if bottom else '', bottom or top, 0, max(0,height-56), width, 56,
            dict(enabled=True, scroll_enabled=False, system_font_size=12, game_font_size=12, margin=8, padding=3,
                 system_color=color,
                 game_color=color, background_alpha=224))

    def close(self):
        self.shared.close()


def process_actions(control, slots, cfg, catalogs, favorites_path, state_path, state, white,
                    resolve_path, banned, dispose, next_try, now, favorite_catalogs=None, launch_request=None, reselect=None):
    from saver_actions import blacklist_rom, add_favorite, remove_favorite
    while control.actions:
        key, index, target = control.actions.popleft()
        if key == UP:
            control.index, control.until, control.status = None, 0., NORMAL
            control.favorite_skip = None
            control.publish()
            print(f'[saver-control] replacing all tiles count={sum(r is not None for r in slots)}', flush=True)
            # Reuse the existing kill/wait/trace/temp cleanup, including for
            # children still loading. Any cleanup failure aborts before refill.
            for slot_index in range(len(slots)):
                dispose(slot_index)
            if reselect is not None:
                reselect()
                control.actions.clear()
                return
            next_try[:] = [now] * len(next_try)
            # The scheduler refills with its normal favorite/resource policy.
            # Session quarantine, saved lists and failure evidence are untouched.
            continue
        if key == DOWN:
            control.index, control.until, control.status = None, 0., NORMAL
            control.publish()
            if slots:
                record = slots[0]
                print('[saver-control] replacing favorite tile slot=1', flush=True)
                dispose(0)
                if record is not None:
                    system, rom = record['pick']
                    control.favorite_skip = (system['id'], str(rom))
                next_try[0] = now
            continue
        record = slots[index]
        # A delayed event may never act on the next program in the same tile.
        if record is not target or record['proc'].poll() is not None:
            continue
        system, rom = record['pick']
        name = system.get('name',system['id'])
        if key == ENTER:
            try:
                if launch_request is None:
                    raise RuntimeError('RetroArch handoff is unavailable')
                launch_request(system, rom)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                control.status = LAUNCH_ERROR
                print(f'[retroarch] request failed slot={index+1} [{name}] {rom}: {exc}', flush=True)
                continue
            control.actions.clear()
            control.publish()
            return
        try:
            if key == INSERT:
                added = add_favorite(favorites_path, system, rom,
                                     catalogs if favorite_catalogs is None else favorite_catalogs)
                status = ADDED if added else EXISTS
                print(f'[saver-control] favorite {"added" if added else "already present"} slot={index+1} [{name}] {rom.name}', flush=True)
            elif key == DELETE and index == 0:
                removed = remove_favorite(favorites_path, system, rom,
                                          catalogs if favorite_catalogs is None else favorite_catalogs)
                status = REMOVED
                print(f'[saver-control] favorite {"removed" if removed else "already absent"} slot=1 [{name}] {rom.name}; replacing tile', flush=True)
            else:
                if not cfg.get('persistent_rom_blacklist_enabled', True):
                    raise ValueError('persistent_rom_blacklist_enabled is false')
                updated, updated_white = blacklist_rom(state_path,
                    resolve_path(cfg.get('persistent_rom_whitelist_file'),'state/persistent_rom_whitelist.json'),
                    resolve_path(cfg.get('persistent_rom_whitelist_seed_file'),'persistent_rom_whitelist.default.json'),
                    name, rom.name)
                state.clear(); state.update(updated)
                white.clear(); white.update(updated_white)
                # Exclude basename aliases from ordinary picks only. Favorites
                # retain their own catalog; banned is reserved for real failures.
                sid = system['id']
                catalogs[sid] = [p for p in catalogs.get(sid, []) if p.name.casefold() != rom.name.casefold()]
                status = BLOCKED
                print(f'[saver-control] blacklisted slot={index+1} [{name}] {rom.name}; replacing tile', flush=True)
        except (OSError, ValueError, RuntimeError) as exc:
            if control.index == index:
                control.status = ERROR
            print(f'[saver-control] save failed slot={index+1} [{name}] {rom.name}: {exc}', flush=True)
            continue
        if control.index == index:
            control.status = status
        if key == DELETE:
            # Keep the established process kill/wait/trace/temp cleanup path.
            # Cleanup failures propagate; do not reuse resource capacity early.
            dispose(index)
            next_try[index] = now
    control.publish()
