"""Cooperating JSON writers share a bounded, crash-released per-path lock.

The sidecar remains on disk: unlinking it could split two writers onto different
locks. JSON readers still use atomic replacement and need no lock. External
editors do not participate; callers retain their optimistic revision checks.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import errno
import os
import threading
import time

_registry_guard = threading.Lock()
_locks = {}
_held = threading.local()


def _key(path):
    return os.path.normcase(str(Path(path).resolve()))


@contextmanager
def file_lock(path, timeout=5):
    if path is None:
        yield
        return
    key = _key(path)
    with _registry_guard:
        local = _locks.setdefault(key, threading.RLock())
    if not local.acquire(timeout=timeout):
        raise TimeoutError(f'{path}: another writer is busy; try again')
    try:
        held = getattr(_held, 'paths', None)
        if held is None:
            held = _held.paths = set()
        if key in held:
            yield
            return
        sidecar = Path(key + '.lock')
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        with sidecar.open('a+b') as stream:
            if not stream.seek(0, os.SEEK_END):
                stream.write(b'\0')
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                stream.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'{path}: another writer is busy; try again') from exc
                    time.sleep(.025)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        local.release()


@contextmanager
def file_locks(*paths):
    with ExitStack() as stack:
        for path in sorted({_key(p) for p in paths if p is not None}):
            stack.enter_context(file_lock(path))
        yield


def replace_checked(temporary, path, original, timeout=1):
    """Retry transient Windows sharing denial without losing a newer revision.

    Caller holds file_lock(path). Readers outside our lock (including the saver
    and antivirus) may briefly keep a Windows handle that denies replacement.
    """
    path = Path(path)
    deadline = time.monotonic() + timeout
    while True:
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise RuntimeError(f'{path.name}: another edit detected; reopen and try again')
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                raise
            time.sleep(.025)
