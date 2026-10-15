"""Bounded startup observations; no scheduling, rendering or cleanup decisions.

Enabled only by the measurement launcher (RNS_STARTUP_TIMING=1). No ordinary-run
trace files or process queries. A successful GDI submit
does not prove non-black content, DWM composition, or physical monitor visibility.
"""
from contextlib import contextmanager
from time import monotonic as _clock
import datetime
import json
import os
from pathlib import Path
import threading

_path = None
_identity = {}
_lock = threading.RLock()


def record(event, **data):
    try:
        if _path is None:
            return
        row = dict(time=datetime.datetime.now().astimezone().isoformat(timespec='milliseconds'),
                   monotonic=_clock(), **_identity, event=event, **data)
        with _lock, _path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    except Exception:
        pass


def _process_identity(pid):
    """Creation time only, to pair measured children without PID reuse ambiguity."""
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
    kernel.GetProcessTimes.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    result = dict(pid=pid)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if handle:
        try:
            times = [W.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(handle, *(C.byref(t) for t in times)):
                result['creation_filetime'] = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            kernel.CloseHandle(handle)
    return result


def start(directory, version, argv):
    global _path, _identity
    if _path is not None or os.environ.get('RNS_STARTUP_TIMING') != '1' or '--supervisor-guard' in argv:
        return
    try:
        role = next((arg[2:] for arg in argv if arg in ('--worker', '--slot-worker')), 'host')
        _identity = dict(pid=os.getpid(), parent_pid=os.getppid(), role=role, version=version)
        _path = Path(directory) / f'startup_trace_{datetime.datetime.now():%Y%m%d_%H%M%S_%f}_{os.getpid()}.jsonl'
        record('process_entry', arguments=list(argv))
        process = _process_identity(os.getpid())
        parent = _process_identity(os.getppid())
        if parent.get('creation_filetime', 0) > process.get('creation_filetime', 0):
            parent = dict(pid=os.getppid())
        record('process_context', reason='startup', process=process, parent=parent)
    except Exception:
        pass


def point(name, **data):
    try:
        record('startup_point', name=name, **data)
    except Exception:
        pass


@contextmanager
def span(name, **data):
    started = _clock()
    point(name + '_begin', **data)
    completed = False
    try:
        yield
        completed = True
    finally:
        point(name + '_end', elapsed_seconds=_clock() - started,
              completed=completed, **data)


def measure(name, function, *args, **kwargs):
    with span(name):
        return function(*args, **kwargs)


def arm_presentation(window, slots, alpha):
    """Arm only after drawing game frames. Full black fade is not a submit milestone."""
    try:
        done = getattr(window, '_startup_presented_slots', set())
        faded = getattr(window, '_startup_unfaded_slots', set())
        window._startup_pending_present = [
            (slot, alpha) for slot in slots
            if alpha < 255 and (slot not in done or (alpha == 0 and slot not in faded))
        ]
    except Exception:
        pass


def presented(window, pending):
    """Called exclusively after checked BitBlt succeeds, never on early return."""
    try:
        if not pending:
            return
        done = getattr(window, '_startup_presented_slots', set())
        faded = getattr(window, '_startup_unfaded_slots', set())
        for slot, alpha in pending:
            if slot not in done:
                point('first_game_gdi_submit', slot=slot, fade_alpha=alpha,
                      physical_visibility_verified=False)
                done.add(slot)
            if alpha == 0 and slot not in faded:
                point('first_unfaded_gdi_submit', slot=slot,
                      physical_visibility_verified=False)
                faded.add(slot)
        window._startup_presented_slots = done
        window._startup_unfaded_slots = faded
    except Exception:
        pass
