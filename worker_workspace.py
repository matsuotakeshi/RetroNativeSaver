"""Supervisor-owned disposable files survive worker hard exit, then are reclaimed.

Only this generation's freshly created directory is removed, and only after
Job accounting proves every descendant has exited. Unknown/live owners keep
their files. Save/state and RetroArch handoff content are not stored here.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import tempfile
import time

ENV = 'RNS_WORKSPACE'


class JobAccounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in
                ('user', 'kernel', 'period_user', 'period_kernel')] + [
                (name, wintypes.DWORD) for name in
                ('faults', 'total', 'active', 'terminated')]


def active_processes(kernel, job):
    info = JobAccounting()
    query = kernel.QueryInformationJobObject
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                      wintypes.DWORD, ctypes.c_void_p]
    query.restype = wintypes.BOOL
    if not query(job, 1, ctypes.byref(info), ctypes.sizeof(info), None):
        raise OSError('Cannot verify worker Job process count')
    return info.active


class WorkerWorkspace:
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix='rns_worker_')).resolve()

    def apply(self, env):
        env[ENV] = str(self.path)

    def cleanup(self, kernel, job, proc=None, assigned=True, pump=None):
        if not assigned and proc is not None:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        if job:
            if active_processes(kernel, job):
                if not kernel.TerminateJobObject(job, 0):
                    raise OSError('Cannot stop worker Job before removing temporary files')
                deadline = time.monotonic() + 5
                while active_processes(kernel, job):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Worker descendants still alive; keeping temporary files')
                    if pump is not None:
                        pump()
                    time.sleep(.025)
        elif proc is not None and proc.poll() is None:
            raise RuntimeError('Cannot verify live worker without its Job')
        # No finalizer: even host shutdown must not delete unverified live data.
        if self.path.exists():
            shutil.rmtree(self.path)


def worker_temp_parent():
    return os.environ.get(ENV) or None
