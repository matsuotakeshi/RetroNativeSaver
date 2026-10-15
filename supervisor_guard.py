"""Out-of-process watchdog for one explicitly identified supervisor instance."""
import ctypes as C
from ctypes import wintypes as W
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import uuid


def report(event, **data):
    # The saver already owns the daily log; no separate diagnostic file.
    try:
        print('[supervisor-guard]', event, data, flush=True)
    except Exception:
        pass


class StallTracker:
    def __init__(self, now, timeout=30):
        self.timeout = timeout
        self.last_sample = self.changed = now
        self.value = None

    def stalled(self, value, now):
        # Suspend/resume or a descheduled watchdog is not evidence of a hung parent.
        if now - self.last_sample > 10 or value != self.value:
            self.changed, self.value = now, value
        self.last_sample = now
        return now - self.changed >= self.timeout


def bind():
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.WaitForSingleObject.restype = W.DWORD
    k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)]*4
    k.GetProcessTimes.restype = W.BOOL
    k.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    k.TerminateProcess.restype = W.BOOL
    k.CloseHandle.argtypes = [W.HANDLE]
    k.CloseHandle.restype = W.BOOL
    return k


def created_at(k, handle):
    times = [W.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(handle, *(C.byref(t) for t in times)):
        raise C.WinError(C.get_last_error())
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


class Guard:
    def __init__(self, app_dir, log_dir):
        self.map = mmap.mmap(-1, 8, tagname=(tag := 'Local\\RNSGuard_' + uuid.uuid4().hex))
        self.counter = 0
        self.beat()
        k = bind()
        handle = k.OpenProcess(0x1000, False, os.getpid())
        if not handle:
            self.map.close()
            raise C.WinError(C.get_last_error())
        try:
            creation = created_at(k, handle)
        finally:
            k.CloseHandle(handle)
        command = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-u', str(Path(app_dir)/'native_saver.py')]
        try:
            self.process = subprocess.Popen(command + ['--supervisor-guard', str(os.getpid()), str(creation), tag, str(log_dir)],
                                            close_fds=True, creationflags=0x08000000,
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self.map.close()
            raise
        print(f'[supervisor-guard] pid={self.process.pid}; main-thread timeout=30s', flush=True)

    def beat(self):
        self.counter += 1
        self.map.seek(0)
        self.map.write(struct.pack('<Q', self.counter))

    def close(self):
        self.map.seek(0)
        self.map.write(bytes(8))  # Explicit normal completion; never means stalled.
        self.map.close()


def watch(pid, creation, tag, log_dir, timeout=30):
    k = bind()
    handle = k.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
    if not handle:
        report('guard_unavailable', parent_pid=pid, error=C.get_last_error())
        return
    try:
        if created_at(k, handle) != creation:
            report('identity_mismatch', parent_pid=pid)
            return
        report('guard_started', parent_pid=pid, creation=creation, timeout_seconds=timeout)
        with mmap.mmap(-1, 8, tagname=tag, access=mmap.ACCESS_READ) as shared:
            tracker = StallTracker(time.monotonic(), timeout)
            while True:
                status = k.WaitForSingleObject(handle, 0)
                if status == 0:
                    report('parent_exited')
                    return
                if status != 0x102:
                    report('wait_failed', status=status)
                    return
                shared.seek(0)
                value = struct.unpack('<Q', shared.read(8))[0]
                if value == 0:
                    report('normal_completion')
                    return
                if tracker.stalled(value, time.monotonic()):
                    report('supervisor_stalled', parent_pid=pid, timeout_seconds=timeout)
                    ok = k.TerminateProcess(handle, 77)
                    report('terminate_result', success=bool(ok), error=0 if ok else C.get_last_error())
                    return
                time.sleep(1)
    finally:
        k.CloseHandle(handle)
