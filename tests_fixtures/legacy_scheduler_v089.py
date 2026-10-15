"""Experimental per-tile process scheduler. Native cores never live in the scheduler."""
import ctypes
import json
import math
import mmap
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time

from favorites import load_favorites, favorite_candidates
from runtime_policy import persistent_failure, FramePacer, tile_hung, tile_exit_status
from resource_policy import independent_usage, independent_can_add, independent_fits

COMPLETE = 75
FAILED = 76


def duration_seconds(cfg, rng=random):
    center = float(cfg.get('cycle_seconds', 180))
    jitter = abs(float(cfg.get('independent_jitter_seconds', 60)))
    if not math.isfinite(center) or not math.isfinite(jitter):
        raise ValueError('Cycle duration and jitter must be finite')
    return rng.uniform(max(5., center - jitter), max(5., center + jitter))


def fade_alpha(elapsed, duration, fade):
    if fade <= 0:
        return 0
    fade = min(fade, duration / 2)
    return max(0, min(255, round(255 * max(1 - elapsed / fade,
                                                   1 - (duration - elapsed) / fade))))


def select_slot(index, systems, catalogs, cfg, occupied, favorites, banned, suspended, rng=random, normal_occupied=None):
    """Reservations include loading slots. The replacing slot is already stopped."""
    counts, usage = independent_usage(occupied)
    def allowed(system):
        if not system.get('enabled', True) or system.get('name', system['id']) in suspended:
            return False
        if str(system.get('render_backend', 'software')).lower() not in ('software', 'opengl', 'glcore'):
            return False
        return independent_can_add(system, counts, usage, cfg)
    def fits(system, picks):
        return independent_fits(system, picks, cfg)

    viable_favorites = [(s, r) for s, r in favorites
                        if s.get('enabled', True) and s.get('name', s['id']) not in suspended
                        and str(s.get('render_backend', 'software')).lower() in ('software', 'opengl', 'glcore')
                        and r in catalogs.get(s['id'], []) and (s['id'], str(r)) not in banned
                        and fits(s, [])]
    pools = {}
    eligible = []
    for system in systems:
        if allowed(system) and (index == 0 or normal_occupied is None or all(
                fits(favorite, list(normal_occupied) + [(system, None)])
                for favorite, _ in viable_favorites)):
            pool = [r for r in catalogs.get(system['id'], [])
                    if (system['id'], str(r)) not in banned]
            if pool:
                eligible.append(system)
                pools[system['id']] = pool
    if index == 0:
        candidates = [(s, r) for s, r in favorites if s['id'] in pools and r in pools[s['id']]]
        if candidates:
            return rng.choice(candidates)
        if viable_favorites:
            # Changed favorites may need existing ordinary tiles to drain first.
            return None
    if not eligible:
        return None
    # Spread systems when capacity permits; don't duplicate a running ROM unless unavoidable.
    system = rng.choice([s for s in eligible if not counts.get(s['id'])] or eligible)
    used = {(s['id'], str(r)) for s, r in occupied}
    pool = pools[system['id']]
    unique = [r for r in pool if (system['id'], str(r)) not in used]
    return system, rng.choice(unique or pool)


def run_slot(api, spec_path):
    """One native core, one child window, one cycle. Always terminate without DLL teardown."""
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    api.init_runtime_trace_from_env()
    system, rom = spec['system'], Path(spec['rom'])
    index, cfg = spec['index'], spec['cfg']
    api.write_runtime_trace('START_ENTER', slot=index + 1, system=system['name'], rom=rom.name)
    # Do not enter a native core until the owner successfully assigns our Job Object.
    gate = Path(spec['gate'])
    until = time.monotonic() + 10
    while not gate.exists():
        if time.monotonic() > until or not api.user32.IsWindow(spec['parent']):
            api.hard_exit_process(FAILED)
        time.sleep(.02)
    win = api.GDIWindow(fullscreen=False, parent_hwnd=spec['parent'],
                        mouse_exit_threshold=int(cfg.get('mouse_exit_threshold', 12)),
                        hide_cursor=spec['hide_cursor'], embedded_rect=spec['rect'])
    if win.create() is False:
        api.hard_exit_process(0)
    with tempfile.TemporaryDirectory(prefix='rns_tile_', dir=spec['content_dir'],
                                     ignore_cleanup_errors=True) as folder:
        core, av, _, _ = api.start_slot_with_retry(index, system, rom, [system],
            {system['id']: [rom]}, cfg, Path(folder), set(), max_attempts=1, worker_mode=True)
        duration = spec['duration']
        fade = max(0, float(cfg.get('fade_duration_ms', 800)) / 1000) if cfg.get('fade_enabled', True) else 0
        pacer = FramePacer(av.timing.fps, cfg.get('independent_max_fps', 30), time.monotonic())
        print(f'[timing] slot={index+1} core_fps={av.timing.fps:.3f} display_fps={1/pacer.display_period:.3f}', flush=True)
        start = None
        calls = 0
        while True:
            win.pump()
            if win.should_close or not api.user32.IsWindow(spec['parent']):
                print(f"[exit-diagnostic] tile exit slot={index+1} hwnd={win.hwnd} parent={spec['parent']} should_close={win.should_close} reason={win.exit_reason} parent_alive={bool(api.user32.IsWindow(spec['parent']))}", flush=True)
                api.write_runtime_trace('SLOT_USER_EXIT', slot=index + 1)
                api.hard_exit_process(0)
            calls += 1
            api.write_runtime_trace('RUN_ENTER', slot=index + 1, system=system['name'],
                                    rom=rom.name, call_count=calls)
            core.run_frame()
            now = time.monotonic()
            if core.frame_bytes and start is None:
                start = now
                print(f"[independent] slot={index + 1} first frame; duration={duration:.1f}s [{system['name']}] {rom.name}", flush=True)
            elapsed = now - start if start is not None else 0
            api.write_runtime_trace('SLOT_RUNNING' if start is not None else 'WAIT_FRAME',
                                    slot=index + 1, system=system['name'], rom=rom.name, call_count=calls)
            if pacer.should_present(now):
                win.begin_composite()
                if core.frame_bytes:
                    width, height = win.client_size()
                    win.draw_frame_to_rect(core.frame_bytes, core.frame_w, core.frame_h,
                        core.frame_pitch, core.pixel_format, core.display_aspect, 0, 0, width, height,
                        bottom_up=core.frame_bottom_up)
                    if cfg.get('overlay', {}).get('enabled', True):
                        win.draw_overlay(system['name'], spec['title'], 0, 0, width, height, cfg.get('overlay', {}))
                alpha = fade_alpha(elapsed, duration, fade)
                if alpha:
                    win.draw_fade_black(alpha)
                win.present()
            if start is not None and cfg.get('cycle_enabled', True) and elapsed >= duration:
                # Commit a fully black final frame before discarding this window/process.
                win.begin_composite()
                win.present()
                api.write_runtime_trace('SLOT_COMPLETE', slot=index + 1, system=system['name'], rom=rom.name)
                api.hard_exit_process(COMPLETE)
            time.sleep(pacer.delay(time.monotonic()))


def run_scheduler(api, win, rects, systems, catalogs, cfg, favorites_path, title_maps):
    slots = [None] * len(rects)
    banned, suspended, failures = set(), set(), {}
    next_try = [0.] * len(rects)
    favorite_stamp, favorites = object(), []
    state_path = api.resolve_app_relative_path(cfg.get('persistent_rom_blacklist_file'), 'state/persistent_rom_blacklist.json')
    state = api._load_persistent_rom_state(state_path)
    white_path = api.resolve_app_relative_path(cfg.get('persistent_rom_whitelist_file'), 'state/persistent_rom_whitelist.json')
    white = api._persistent_whitelisted_roms(api._load_persistent_rom_whitelist(white_path))
    if cfg.get('persistent_rom_blacklist_enabled', True):
        effective, _ = api._apply_persistent_whitelist(
            api._persistent_blacklisted_roms(state),
            white if cfg.get('persistent_rom_whitelist_enabled', True) else {})
        catalogs = {s['id']: [r for r in catalogs.get(s['id'], [])
                    if not api._rom_in_name_map(effective, s.get('name', s['id']), r.name)]
                    for s in systems}
    session = os.environ.get('RNS_SLOT_SESSION_ID', f'independent-{os.getpid()}')
    job = api._create_worker_job_object()
    if not job:
        raise RuntimeError('Independent mode requires a kill-on-close Job Object')
    temp = tempfile.TemporaryDirectory(prefix='rns_scheduler_', ignore_cleanup_errors=True)
    folder = Path(temp.name)
    print(f"[independent] enabled slots={len(rects)} center={cfg.get('cycle_seconds', 180)} jitter={cfg.get('independent_jitter_seconds', 60)}", flush=True)
    win.begin_composite()
    win.present()

    def dispose(index):
        record = slots[index]
        if record is None:
            return
        proc = record['proc']
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        record['trace'].close()
        shutil.rmtree(record['content_dir'], ignore_errors=True)
        slots[index] = None
        win.present()  # WS_CLIPCHILDREN protects all the remaining tiles.

    def fail(record, snapshot, reason, exit_code=None):
        system, rom = record['pick']
        name = system.get('name', system['id'])
        print(f"[independent] slot={record['index'] + 1} {reason}; quarantined [{name}] {rom.name}", flush=True)
        # Always exclude this failing ROM from the experimental run to avoid a restart storm.
        banned.add((system['id'], str(rom)))
        failures[name] = failures.get(name, 0) + 1
        if failures[name] >= max(1, int(cfg.get('session_system_crash_limit', 3))):
            suspended.add(name)
        durable = persistent_failure(snapshot, exit_code)
        print(f'[failure-policy] persistent={durable} phase={(snapshot or {}).get("phase")} reason={reason}', flush=True)
        if durable and cfg.get('persistent_rom_blacklist_enabled', True) and not (
            cfg.get('persistent_rom_whitelist_enabled', True) and api._rom_in_name_map(white, name, rom.name)
        ):
            api._record_persistent_rom_failure(state, state_path, session,
                max(1, int(cfg.get('persistent_rom_blacklist_threshold_sessions', 2))),
                name, rom.name, (snapshot or {}).get('phase', 'SLOT_START'), reason)

    try:
        while not win.should_close:
            win.pump()
            if win.should_close:
                break
            if getattr(win, 'power_idle', False):
                if job:
                    if not api.kernel32.CloseHandle(job):
                        raise RuntimeError('Could not stop tile Job Object')
                    job = None
                for index in range(len(slots)):
                    dispose(index)
                win.begin_composite()
                win.present()
                print('[power-standby] tiles stopped; retaining existing parent hwnd=' + str(win.hwnd), flush=True)
                api.write_runtime_trace('SLOT_POWER_IDLE')
                while not win.should_close:
                    win.pump()
                    if not win.should_close:
                        time.sleep(.05)
                return 0
            now = time.monotonic()
            # This worker is only the scheduler; no native core can block its event pump.
            api.write_runtime_trace('SLOT_SCHEDULER', call_count=int(now * 1000))
            try:
                stat = Path(favorites_path).stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                stamp = None
            if stamp != favorite_stamp:
                favorite_stamp = stamp
                try:
                    favorites = favorite_candidates(systems, catalogs, load_favorites(favorites_path))
                except (ValueError, OSError) as exc:
                    favorites = []
                    print(f"[favorites] configuration error: {exc}", flush=True)

            starting = False
            for index, record in enumerate(slots):
                if record is None:
                    continue
                snapshot = api.read_runtime_trace(record['trace']) or {}
                phase = snapshot.get('phase', '')
                if phase == 'SLOT_RUNNING':
                    record['ready'] = True
                raw = snapshot.get('raw', '')
                if raw != record['last_trace']:
                    record['last_trace'], record['progress'] = raw, now
                code = record['proc'].poll()
                if code is not None:
                    exit_status = tile_exit_status(code, phase, COMPLETE)
                    if exit_status == 'user_exit':
                        win._note_exit(win.hwnd, 'tile-user-exit', f"slot={index+1} pid={record['proc'].pid} phase={phase}")
                        win.should_close = True
                        break
                    if exit_status == 'failure':
                        fail(record, snapshot, f'exit={code}', code)
                    else:
                        print(f"[independent] slot={index + 1} completed; replacing only this tile", flush=True)
                    dispose(index)
                    next_try[index] = now
                    continue
                hung = tile_hung(record, cfg, now)
                if hung:
                    record['proc'].kill()
                    record['proc'].wait(timeout=5)
                    fail(record, snapshot, 'hang')
                    dispose(index)
                    next_try[index] = now + 1
                elif not record['ready']:
                    starting = True
            if win.should_close:
                break
            # Serialize core startup to avoid simultaneous disk/GPU initialization spikes.
            if not starting:
                for index, record in enumerate(slots):
                    if record is not None or now < next_try[index]:
                        continue
                    occupied = [r['pick'] for r in slots if r is not None]
                    pick = select_slot(index, systems, catalogs, cfg, occupied, favorites, banned, suspended,
                                       normal_occupied=[r['pick'] for i, r in enumerate(slots) if i != 0 and r is not None])
                    if pick is None:
                        next_try[index] = now + 2
                        continue
                    system, rom = pick
                    duration = duration_seconds(cfg)
                    if index == 0:
                        status = 'favorite' if any(s['id'] == system['id'] and r == rom for s, r in favorites) else 'normal fallback (no eligible favorite)'
                        print(f"[independent] slot=1 {status}", flush=True)
                    tag = f'RNS_Tile_{os.getpid()}_{index}_{time.monotonic_ns()}'
                    trace = mmap.mmap(-1, api.RUNTIME_TRACE_SIZE, tagname=tag)
                    gate = folder / f'gate_{index}'
                    gate.unlink(missing_ok=True)
                    spec_path = folder / f'slot_{index}.json'
                    content_dir = folder / f'content_{index}'
                    content_dir.mkdir(exist_ok=True)
                    spec = dict(system=system, rom=str(rom), index=index, cfg=cfg,
                                parent=int(win.hwnd), rect=rects[index], duration=duration,
                                gate=str(gate), hide_cursor=bool(win.fullscreen),
                                content_dir=str(content_dir),
                                title=api.resolve_display_title(system, rom, title_maps))
                    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
                    env = os.environ.copy()
                    env[api.RUNTIME_TRACE_ENV] = tag
                    cmd = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-u', str(Path(api.__file__).resolve())]
                    try:
                        proc = subprocess.Popen(cmd + ['--slot-worker', str(spec_path)], env=env)
                    except Exception:
                        trace.close()
                        raise
                    slots[index] = dict(proc=proc, trace=trace, pick=pick, index=index,
                                        content_dir=content_dir,
                                        spawned=time.monotonic(), progress=time.monotonic(),
                                        last_trace='', ready=False)
                    if not api._assign_worker_to_job(job, proc):
                        dispose(index)
                        raise RuntimeError('Cannot safely assign tile process to Job Object')
                    gate.touch()
                    print(f"[independent] start slot={index + 1} pid={proc.pid} duration={duration:.1f}s [{system['name']}] {rom.name}", flush=True)
                    break
            time.sleep(.03)
        return 0
    finally:
        print(f"[exit-diagnostic] scheduler leaving hwnd={win.hwnd} should_close={win.should_close} reason={win.exit_reason} standby={getattr(win, 'power_idle', False)}", flush=True)
        if job:
            api.kernel32.CloseHandle(job)
        for index in range(len(slots)):
            try:
                dispose(index)
            except Exception as exc:
                print(f"[independent] cleanup warning slot={index + 1}: {exc}", flush=True)
        temp.cleanup()
