from __future__ import annotations

import faulthandler
import ctypes
import json
import datetime
import mmap
import os
import subprocess
import random
import shutil
import sys
import tempfile
import time
import uuid
from ctypes import (
    CFUNCTYPE, POINTER, Structure, byref,
    c_bool, c_char_p, c_double, c_float, c_int16, c_int64, c_size_t, c_uint, c_uint64, c_void_p,
    c_int, c_long, c_ushort, c_ulong, c_wchar_p
)
from pathlib import Path
from favorites import load_favorites, favorite_candidates, show_favorites_editor
from runtime_policy import PREPARATION_PHASES, watchdog_timeout, progress_key, NATIVE_CRASH_CODES
from app_version import APP_VERSION

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def resolve_app_relative_path(value, default_name):
    """
    Resolve config paths that belong to Retro Native Saver itself.

    Windows launches .scr files with a working directory that is not guaranteed
    to be the application's install directory (commonly System32 after reboot).
    Therefore writable relative paths such as "save" must be anchored to
    APP_DIR, not to os.getcwd().
    """
    raw = value
    if raw is None or str(raw).strip() == "":
        raw = default_name

    path = Path(raw)
    if not path.is_absolute():
        path = APP_DIR / path
    return path.resolve()

# Persistent diagnostics.
#
# PyInstaller --windowed / --noconsole sets sys.stdout and sys.stderr to None.
# Instead of throwing diagnostics away, always append them to a daily log file.
# Console launches still tee to the visible console as well.
_LOG_DIR = APP_DIR / "logs"
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _LOG_DIR = Path(tempfile.gettempdir()) / "retro_native_saver_logs"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

_LOG_PATH = _LOG_DIR / (
    "retro_native_saver_" + datetime.datetime.now().strftime("%Y%m%d") + ".log"
)
_LOG_HANDLE = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)

_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr


from diagnostic_io import _DiagnosticStream


sys.stdout = _DiagnosticStream(_ORIGINAL_STDOUT, _LOG_HANDLE, "OUT")
sys.stderr = _DiagnosticStream(_ORIGINAL_STDERR, _LOG_HANDLE, "ERR")

print(
    "=== Retro Native Saver process start "
    f"pid={os.getpid()} ppid={os.getppid()} "
    f"argv={sys.argv[1:]} log={_LOG_PATH} version={APP_VERSION} ===",
    flush=True,
)
print(
    f"[process] app_dir={APP_DIR} cwd={Path.cwd()}",
    flush=True,
)

from startup_timing import start as start_startup_timing
start_startup_timing(_LOG_DIR, APP_VERSION, sys.argv[1:])
from startup_timing import point as startup_point
startup_point("logging_ready")

WORKER_RESTART_EXIT_CODE = 75

RUNTIME_TRACE_ENV = "RNS_RUNTIME_TRACE_TAG"
from diagnostic_io import RUNTIME_TRACE_SIZE
_RUNTIME_TRACE_MAP = None

SESSION_QUARANTINE_ENV = "RNS_SESSION_QUARANTINE_JSON"
SESSION_DISABLED_SYSTEMS_ENV = "RNS_SESSION_DISABLED_SYSTEMS_JSON"


def _runtime_trace_clean(value) -> str:
    from diagnostic_io import _runtime_trace_clean as clean
    return clean(value)


def init_runtime_trace_from_env():
    """
    Open the supervisor-owned named memory mapping.

    This mapping is intentionally memory-backed rather than a per-frame disk
    log. The worker can update the current native call hundreds of times per
    second without creating disk-I/O pressure. After a raw native crash the
    supervisor still owns the mapping and can log the final record.
    """
    global _RUNTIME_TRACE_MAP

    tag = os.environ.get(RUNTIME_TRACE_ENV, "").strip()
    if not tag or os.name != "nt":
        return None

    try:
        _RUNTIME_TRACE_MAP = mmap.mmap(
            -1,
            RUNTIME_TRACE_SIZE,
            tagname=tag,
        )
        print(
            f"[runtime-trace] worker attached shared trace tag={tag}",
            flush=True,
        )
    except Exception as exc:
        _RUNTIME_TRACE_MAP = None
        print(
            f"[runtime-trace] worker could not attach shared trace: {exc}",
            flush=True,
        )
    return _RUNTIME_TRACE_MAP


def write_runtime_trace(
    phase,
    cycle=0,
    slot=0,
    system="",
    rom="",
    loop_count=0,
    call_count=0,
):
    from diagnostic_io import write_runtime_trace as write
    return write(_RUNTIME_TRACE_MAP, phase, cycle, slot, system, rom, loop_count, call_count)


def read_runtime_trace(mm):
    from diagnostic_io import read_runtime_trace as read
    return read(mm)


def log_runtime_trace_snapshot(mm, worker_pid, reason):
    from diagnostic_io import log_runtime_trace_snapshot as log
    return log(mm, worker_pid, reason)


def _load_session_safety_from_env():
    from rom_list_policy import load_session_safety
    return load_session_safety(os.environ, SESSION_QUARANTINE_ENV, SESSION_DISABLED_SYSTEMS_ENV)


def _empty_persistent_rom_state():
    from rom_state_store import _empty_persistent_rom_state as operation
    return operation()


def _load_persistent_rom_state(path):
    from rom_state_store import _load_persistent_rom_state as operation
    return operation(path)


def _save_persistent_rom_state(path, state):
    from rom_state_store import _save_persistent_rom_state as operation
    return operation(path, state)


def _persistent_entry_for_rom(state, system_name, rom_name, create=False):
    from rom_list_policy import _persistent_entry_for_rom as lookup
    return lookup(state, system_name, rom_name, create)


def _persistent_blacklisted_roms(state):
    from rom_list_policy import _persistent_blacklisted_roms as lookup
    return lookup(state)


def _empty_persistent_rom_whitelist():
    from rom_state_store import _empty_persistent_rom_whitelist as operation
    return operation()


def _load_persistent_rom_whitelist(path, seed_path=None):
    from rom_state_store import _load_persistent_rom_whitelist as operation
    return operation(path, seed_path)


def _persistent_whitelisted_roms(state):
    from rom_list_policy import _persistent_whitelisted_roms as lookup
    return lookup(state)


def _rom_in_name_map(name_map, system_name, rom_name):
    from rom_list_policy import _rom_in_name_map as lookup
    return lookup(name_map, system_name, rom_name)


def _apply_persistent_whitelist(blacklisted, whitelisted):
    from rom_list_policy import _apply_persistent_whitelist as lookup
    return lookup(blacklisted, whitelisted)


def _record_persistent_rom_failure(
    state,
    path,
    session_id,
    threshold_sessions,
    system_name,
    rom_name,
    phase,
    failure_kind,
):
    from rom_state_store import _record_persistent_rom_failure as record
    return record(state, path, session_id, threshold_sessions, system_name, rom_name, phase, failure_kind)


def _is_session_runtime_crash(snapshot, unsigned_code, native_crash_codes):
    from runtime_policy import _is_session_runtime_crash as classify
    return classify(snapshot, unsigned_code, native_crash_codes)


def is_native_access_violation(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "access violation" in msg:
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror is None:
        return False
    return (int(winerror) & 0xFFFFFFFF) == 0xC0000005



def hard_exit_process(exit_code: int):
    """
    Force-terminate the current Windows worker process without running
    Python finalizers, CRT exit handlers, or DLL_PROCESS_DETACH teardown.

    This is intentional for old Dolphin libretro builds whose unload/DLL
    teardown path aborts even though gameplay itself is stable.
    """
    code = int(exit_code) & 0xFFFFFFFF
    try:
        print(f"[process-exit] forced code={code}", flush=True)
    except Exception:
        pass
    try:
        # Best effort: make already-written diagnostic output visible.
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        handle = kernel32.GetCurrentProcess()
        if handle:
            kernel32.TerminateProcess(handle, code)
    finally:
        # Should be unreachable when TerminateProcess succeeds. Keep os._exit
        # only as an emergency fallback.
        os._exit(code)


try:
    # Use the real file handle rather than the tee wrapper so fatal native
    # diagnostics have a valid OS file descriptor even in --windowed builds.
    faulthandler.enable(file=_LOG_HANDLE, all_threads=True)
except (RuntimeError, OSError, ValueError):
    # Diagnostics must never prevent a windowed screen saver from starting.
    pass

# ---------------- libretro ABI ----------------
from libretro_abi import (
    RETRO_API_VERSION,
    RETRO_ENVIRONMENT_GET_CAN_DUPE,
    RETRO_ENVIRONMENT_SET_ROTATION,
    RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE,
    RETRO_ENVIRONMENT_SET_CONTROLLER_INFO,
    RETRO_ENVIRONMENT_GET_FASTFORWARDING,
    RETRO_ENVIRONMENT_GET_INPUT_BITMASKS,
    RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY,
    RETRO_ENVIRONMENT_SET_PIXEL_FORMAT,
    RETRO_ENVIRONMENT_GET_VARIABLE,
    RETRO_ENVIRONMENT_SET_VARIABLES,
    RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE,
    RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY,
    RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY,
    RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO,
    RETRO_ENVIRONMENT_SET_GEOMETRY,
    RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION,
    RETRO_ENVIRONMENT_SET_HW_RENDER,
    RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER,
    RETRO_HW_CONTEXT_NONE,
    RETRO_HW_CONTEXT_OPENGL,
    RETRO_HW_CONTEXT_OPENGL_CORE,
    RETRO_HW_FRAME_BUFFER_VALID,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY,
    RETRO_ENVIRONMENT_GET_LOG_INTERFACE,
    RETRO_ENVIRONMENT_GET_PERF_INTERFACE,
    RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK,
    RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE,
    RETRO_ENVIRONMENT_GET_DISK_CONTROL_INTERFACE_VERSION,
    RETRO_ENVIRONMENT_SET_DISK_CONTROL_EXT_INTERFACE,
    RETRO_ENVIRONMENT_SET_SAVE_STATE_IN_BACKGROUND,
    RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT,
    RETRO_PIXEL_FORMAT_0RGB1555,
    RETRO_PIXEL_FORMAT_XRGB8888,
    RETRO_PIXEL_FORMAT_RGB565,
    RetroGameInfo,
    RetroSystemInfo,
    RetroGameGeometry,
    RetroSystemTiming,
    RetroSystemAVInfo,
    RetroVariable,
    EnvironmentCallback,
    VideoRefreshCallback,
    AudioSampleCallback,
    AudioSampleBatchCallback,
    InputPollCallback,
    InputStateCallback,
    RetroHWContextResetCallback,
    RetroLogPrintfCallback,
    RetroPerfGetTimeUsecCallback,
    RetroPerfGetCpuFeaturesCallback,
    RetroPerfGetCounterCallback,
    RetroLogCallback,
    RetroPerfCounter,
    RetroPerfRegisterCallback,
    RetroPerfStartCallback,
    RetroPerfStopCallback,
    RetroPerfLogCallback,
    RetroPerfCallback,
    RetroKeyboardCallback,
    RetroDiskControlCallback,
    RetroDiskControlExtCallback,
    RetroHWGetCurrentFramebufferCallback,
    RetroHWGetProcAddressCallback,
    RetroHWRenderCallback,
)

# ---------------- Win32 GDI / WGL ----------------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
msimg32 = ctypes.windll.msimg32
opengl32 = ctypes.windll.opengl32
try:
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmFlush.argtypes = []
    dwmapi.DwmFlush.restype = c_long
except Exception:
    dwmapi = None
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = c_void_p
kernel32.TerminateProcess.argtypes = [c_void_p, c_uint]
kernel32.TerminateProcess.restype = c_bool

kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = c_ulong
kernel32.TerminateJobObject.argtypes = [c_void_p, c_uint]
kernel32.TerminateJobObject.restype = c_bool
kernel32.CloseHandle.argtypes = [c_void_p]
kernel32.CloseHandle.restype = c_bool
kernel32.CreateJobObjectW.argtypes = [c_void_p, c_wchar_p]
kernel32.CreateJobObjectW.restype = c_void_p
kernel32.SetInformationJobObject.argtypes = [c_void_p, c_int, c_void_p, c_ulong]
kernel32.SetInformationJobObject.restype = c_bool
kernel32.AssignProcessToJobObject.argtypes = [c_void_p, c_void_p]
kernel32.AssignProcessToJobObject.restype = c_bool

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


class JOBOBJECT_BASIC_LIMIT_INFORMATION(Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", c_int64),
        ("PerJobUserTimeLimit", c_int64),
        ("LimitFlags", c_ulong),
        ("MinimumWorkingSetSize", c_size_t),
        ("MaximumWorkingSetSize", c_size_t),
        ("ActiveProcessLimit", c_ulong),
        ("Affinity", c_size_t),
        ("PriorityClass", c_ulong),
        ("SchedulingClass", c_ulong),
    ]


class IO_COUNTERS(Structure):
    _fields_ = [
        ("ReadOperationCount", c_uint64),
        ("WriteOperationCount", c_uint64),
        ("OtherOperationCount", c_uint64),
        ("ReadTransferCount", c_uint64),
        ("WriteTransferCount", c_uint64),
        ("OtherTransferCount", c_uint64),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", c_size_t),
        ("JobMemoryLimit", c_size_t),
        ("PeakProcessMemoryUsed", c_size_t),
        ("PeakJobMemoryUsed", c_size_t),
    ]


def _create_worker_job_object():
    """
    Create a Windows Job Object whose members are killed automatically when
    the supervisor's last job handle closes.

    This prevents a worker from becoming orphaned if the .scr/supervisor is
    terminated externally or crashes before it can explicitly stop the child.
    """
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        print(
            f"[supervisor] CreateJobObjectW failed error={kernel32.GetLastError()}",
            flush=True,
        )
        return None

    transferred = False
    try:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = kernel32.GetLastError()
            print(
                f"[supervisor] SetInformationJobObject failed error={err}",
                flush=True,
            )
            return None

        print("[supervisor] worker Job Object created (KILL_ON_JOB_CLOSE)", flush=True)
        transferred = True
        return job
    finally:
        if not transferred:
            from process_cleanup import close_job, retain
            try:
                close_job(kernel32, job)
            except BaseException:
                retain(job)
                raise



def _assign_worker_to_job(job, proc):
    if not job:
        return False
    process_handle = c_void_p(int(proc._handle))
    ok = kernel32.AssignProcessToJobObject(job, process_handle)
    if not ok:
        print(
            f"[supervisor] AssignProcessToJobObject pid={proc.pid} "
            f"failed error={kernel32.GetLastError()}",
            flush=True,
        )
        return False
    print(
        f"[supervisor] worker pid={proc.pid} assigned to Job Object",
        flush=True,
    )
    return True

# Pointer-sized Win32 integer types.  Using c_void_p for WPARAM/LPARAM or
# leaving ctypes to infer function signatures can truncate/overflow values on
# 64-bit Windows (notably mouse/system messages passed to DefWindowProcW).
LONG_PTR = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
LRESULT = LONG_PTR
WPARAM = ULONG_PTR
LPARAM = LONG_PTR
HWND = c_void_p
HDC = c_void_p
HBITMAP = c_void_p
HGDIOBJ = c_void_p
HINSTANCE = c_void_p
HCURSOR = c_void_p
HBRUSH = c_void_p
HFONT = c_void_p
COLORREF = c_ulong
HGLRC = c_void_p

PFD_TYPE_RGBA = 0
PFD_MAIN_PLANE = 0
PFD_DOUBLEBUFFER = 0x00000001
PFD_DRAW_TO_WINDOW = 0x00000004
PFD_SUPPORT_OPENGL = 0x00000020
WGL_CONTEXT_MAJOR_VERSION_ARB = 0x2091
WGL_CONTEXT_MINOR_VERSION_ARB = 0x2092
WGL_CONTEXT_FLAGS_ARB = 0x2094
WGL_CONTEXT_PROFILE_MASK_ARB = 0x9126
WGL_CONTEXT_CORE_PROFILE_BIT_ARB = 0x00000001
WGL_CONTEXT_COMPATIBILITY_PROFILE_BIT_ARB = 0x00000002

GL_BACK = 0x0405
GL_BGRA = 0x80E1
GL_UNSIGNED_BYTE = 0x1401
GL_PACK_ALIGNMENT = 0x0D05
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_RGBA8 = 0x8058
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_LINEAR = 0x2601
GL_FRAMEBUFFER = 0x8D40
GL_READ_FRAMEBUFFER = 0x8CA8
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_RENDERBUFFER = 0x8D41
GL_DEPTH24_STENCIL8 = 0x88F0
GL_DEPTH_STENCIL_ATTACHMENT = 0x821A
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_READ_FRAMEBUFFER_BINDING = 0x8CAA
GL_READ_BUFFER = 0x0C02
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_DISPLAYCHANGE = 0x007E
WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
SW_SHOW = 5
SW_HIDE = 0
CW_USEDEFAULT = 0x80000000
PM_REMOVE = 0x0001
IDC_ARROW = 32512
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020
HALFTONE = 4
COLORONCOLOR = 3
BI_RGB = 0
BI_BITFIELDS = 3
BLACK_BRUSH = 4
WS_EX_TOPMOST = 0x00000008
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
TRANSPARENT = 1
FW_NORMAL = 400
DEFAULT_CHARSET = 1
OUT_DEFAULT_PRECIS = 0
CLIP_DEFAULT_PRECIS = 0
DEFAULT_QUALITY = 0
DEFAULT_PITCH = 0
FF_DONTCARE = 0
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

class WNDCLASSW(Structure):
    _fields_ = [
        ("style", c_uint), ("lpfnWndProc", c_void_p), ("cbClsExtra", c_int), ("cbWndExtra", c_int),
        ("hInstance", c_void_p), ("hIcon", c_void_p), ("hCursor", c_void_p), ("hbrBackground", c_void_p),
        ("lpszMenuName", c_wchar_p), ("lpszClassName", c_wchar_p)
    ]

class RECT(Structure):
    _fields_ = [("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long)]

class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]

class SIZE(Structure):
    _fields_ = [("cx", c_long), ("cy", c_long)]

class MSG(Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", c_uint),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", c_ulong),
        ("pt", POINT),
    ]

class PIXELFORMATDESCRIPTOR(Structure):
    _fields_ = [
        ("nSize", c_ushort),
        ("nVersion", c_ushort),
        ("dwFlags", c_ulong),
        ("iPixelType", ctypes.c_ubyte),
        ("cColorBits", ctypes.c_ubyte),
        ("cRedBits", ctypes.c_ubyte),
        ("cRedShift", ctypes.c_ubyte),
        ("cGreenBits", ctypes.c_ubyte),
        ("cGreenShift", ctypes.c_ubyte),
        ("cBlueBits", ctypes.c_ubyte),
        ("cBlueShift", ctypes.c_ubyte),
        ("cAlphaBits", ctypes.c_ubyte),
        ("cAlphaShift", ctypes.c_ubyte),
        ("cAccumBits", ctypes.c_ubyte),
        ("cAccumRedBits", ctypes.c_ubyte),
        ("cAccumGreenBits", ctypes.c_ubyte),
        ("cAccumBlueBits", ctypes.c_ubyte),
        ("cAccumAlphaBits", ctypes.c_ubyte),
        ("cDepthBits", ctypes.c_ubyte),
        ("cStencilBits", ctypes.c_ubyte),
        ("cAuxBuffers", ctypes.c_ubyte),
        ("iLayerType", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte),
        ("dwLayerMask", c_ulong),
        ("dwVisibleMask", c_ulong),
        ("dwDamageMask", c_ulong),
    ]

class BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize", c_ulong), ("biWidth", c_long), ("biHeight", c_long), ("biPlanes", c_ushort),
        ("biBitCount", c_ushort), ("biCompression", c_ulong), ("biSizeImage", c_ulong),
        ("biXPelsPerMeter", c_long), ("biYPelsPerMeter", c_long), ("biClrUsed", c_ulong), ("biClrImportant", c_ulong)
    ]

class RGBQUAD(Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte), ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]

class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]

class BITMAPINFO_MASKS(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("masks", c_ulong * 3)]

class MONITORINFO(Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", c_ulong),
    ]

class BLENDFUNCTION(Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]

HMONITOR = c_void_p
MONITORENUMPROC = ctypes.WINFUNCTYPE(c_bool, HMONITOR, HDC, POINTER(RECT), LPARAM)

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, c_uint, WPARAM, LPARAM)

# Explicit Win32 signatures are important on 64-bit Windows. Without these,
# ctypes assumes c_int for return values/arguments it cannot infer, which may
# truncate HWND/HDC/HBITMAP and overflow pointer-sized LPARAM values.
kernel32.GetModuleHandleW.argtypes = [c_wchar_p]
kernel32.GetModuleHandleW.restype = HINSTANCE
kernel32.FreeLibrary.argtypes = [c_void_p]
kernel32.FreeLibrary.restype = c_bool
kernel32.GetProcAddress.argtypes = [c_void_p, c_char_p]
kernel32.GetProcAddress.restype = c_void_p

user32.GetCursorPos.argtypes = [POINTER(POINT)]
user32.GetCursorPos.restype = c_int

user32.DefWindowProcW.argtypes = [HWND, c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.PostMessageW.argtypes = [HWND, c_uint, WPARAM, LPARAM]
user32.PostMessageW.restype = c_bool
user32.DestroyWindow.argtypes = [HWND]
user32.DestroyWindow.restype = c_bool
user32.PostQuitMessage.argtypes = [c_int]
user32.PostQuitMessage.restype = None

user32.LoadCursorW.argtypes = [HINSTANCE, c_void_p]
user32.LoadCursorW.restype = HCURSOR
user32.RegisterClassW.argtypes = [POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = c_ushort
user32.CreateWindowExW.argtypes = [
    c_ulong, c_wchar_p, c_wchar_p, c_ulong,
    c_int, c_int, c_int, c_int,
    HWND, c_void_p, HINSTANCE, c_void_p,
]
user32.CreateWindowExW.restype = HWND
user32.ShowWindow.argtypes = [HWND, c_int]
user32.ShowWindow.restype = c_bool
user32.UpdateWindow.argtypes = [HWND]
user32.UpdateWindow.restype = c_bool
user32.GetClientRect.argtypes = [HWND, POINTER(RECT)]
user32.GetClientRect.restype = c_bool
user32.IsWindow.argtypes = [HWND]
user32.IsWindow.restype = c_bool
user32.GetDC.argtypes = [HWND]
user32.GetDC.restype = HDC
user32.ReleaseDC.argtypes = [HWND, HDC]
user32.ReleaseDC.restype = c_int
user32.FillRect.argtypes = [HDC, POINTER(RECT), HBRUSH]
user32.FillRect.restype = c_int
gdi32.SetDCBrushColor.argtypes = [HDC, ctypes.c_uint32]
gdi32.SetDCBrushColor.restype = ctypes.c_uint32
user32.GetSystemMetrics.argtypes = [c_int]
user32.GetSystemMetrics.restype = c_int
user32.PeekMessageW.argtypes = [POINTER(MSG), HWND, c_uint, c_uint, c_uint]
user32.PeekMessageW.restype = c_bool
user32.TranslateMessage.argtypes = [POINTER(MSG)]
user32.TranslateMessage.restype = c_bool
user32.DispatchMessageW.argtypes = [POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.ShowCursor.argtypes = [c_bool]
user32.ShowCursor.restype = c_int
user32.MessageBoxW.argtypes = [HWND, c_wchar_p, c_wchar_p, c_uint]
user32.MessageBoxW.restype = c_int

user32.GetDesktopWindow.argtypes = []
user32.GetDesktopWindow.restype = HWND
user32.GetShellWindow.argtypes = []
user32.GetShellWindow.restype = HWND
user32.InvalidateRect.argtypes = [HWND, POINTER(RECT), c_bool]
user32.InvalidateRect.restype = c_bool
user32.RedrawWindow.argtypes = [HWND, POINTER(RECT), c_void_p, c_uint]
user32.RedrawWindow.restype = c_bool
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetForegroundWindow.restype = c_bool

# Interactive-session display power notifications (Windows 8+).
class PowerBroadcastSetting(Structure):
    _fields_ = [("guid", ctypes.c_ubyte * 16),
                ("length", ctypes.c_uint32), ("state", ctypes.c_uint32)]


SESSION_DISPLAY_GUID = uuid.UUID("2b84c20e-ad23-4ddf-93db-05ffbd7efca5").bytes_le
user32.RegisterPowerSettingNotification.argtypes = [HWND, c_void_p, c_ulong]
user32.RegisterPowerSettingNotification.restype = c_void_p
user32.UnregisterPowerSettingNotification.argtypes = [c_void_p]
user32.UnregisterPowerSettingNotification.restype = c_bool

user32.EnumDisplayMonitors.argtypes = [HDC, POINTER(RECT), MONITORENUMPROC, LPARAM]
user32.EnumDisplayMonitors.restype = c_bool
user32.GetMonitorInfoW.argtypes = [HMONITOR, POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = c_bool

# Desktop-redraw flags used when the persistent black backdrop disappears.
RDW_INVALIDATE = 0x0001
RDW_INTERNALPAINT = 0x0002
RDW_ERASE = 0x0004
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100


def restore_windows_desktop(backdrop=None):
    """
    Best-effort desktop recovery after the full-screen black supervisor
    backdrop is removed.

    A production run showed a rare Windows 11 state where Retro Native Saver
    exited normally (no process remained) but the monitors stayed black. Hide
    the backdrop before destroying it, then force the desktop/shell surfaces
    through an invalidate/redraw/update cycle and flush DWM.
    """

    # Hide the topmost black window before destruction so the compositor has a
    # visible transition target even if DestroyWindow itself does not trigger
    # an immediate repaint.
    if backdrop is not None:
        try:
            hwnd = getattr(backdrop, "hwnd", None)
            if hwnd and user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, SW_HIDE)
                user32.UpdateWindow(hwnd)
        except Exception as exc:
            print(
                f"[desktop-restore] hide warning: {exc}",
                flush=True,
            )

        try:
            backdrop.close()
        except Exception as exc:
            print(
                f"[desktop-restore] backdrop close warning: {exc}",
                flush=True,
            )

    if backdrop is not None and (
        getattr(backdrop, "display_was_off", False) is True
        or getattr(backdrop, "display_was_dimmed", False) is True
    ):
        # The supervisor has already closed the worker Job Object. Leave the
        # sleeping output alone: do not redraw, steal focus or flush DWM.
        return

    redraw_flags = (
        RDW_INVALIDATE
        | RDW_INTERNALPAINT
        | RDW_ERASE
        | RDW_ALLCHILDREN
        | RDW_UPDATENOW
    )

    desktop = None
    shell = None

    try:
        desktop = user32.GetDesktopWindow()
        if desktop:
            user32.InvalidateRect(desktop, None, True)
            user32.RedrawWindow(
                desktop,
                None,
                None,
                redraw_flags,
            )
            user32.UpdateWindow(desktop)
    except Exception as exc:
        print(
            f"[desktop-restore] desktop redraw warning: {exc}",
            flush=True,
        )

    try:
        shell = user32.GetShellWindow()
        if shell:
            user32.InvalidateRect(shell, None, True)
            user32.RedrawWindow(
                shell,
                None,
                None,
                redraw_flags,
            )
            user32.UpdateWindow(shell)
    except Exception as exc:
        print(
            f"[desktop-restore] shell redraw warning: {exc}",
            flush=True,
        )

    # Let Explorer become the foreground target again. Windows may reject this
    # call depending on focus policy; that is harmless.
    try:
        if shell:
            user32.SetForegroundWindow(shell)
    except Exception as exc:
        print(
            f"[desktop-restore] foreground warning: {exc}",
            flush=True,
        )

    # Ensure all queued Desktop Window Manager composition work is committed
    # before the supervisor exits, without changing the display mode.
    try:
        if dwmapi is not None:
            dwmapi.DwmFlush()
    except Exception as exc:
        print(
            f"[desktop-restore] DWM flush warning: {exc}",
            flush=True,
        )

    # This saver never changes display modes. Reapplying registry settings
    # here can interfere with Windows display-power transitions.



gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateCompatibleDC.restype = HDC
gdi32.CreateCompatibleBitmap.argtypes = [HDC, c_int, c_int]
gdi32.CreateCompatibleBitmap.restype = HBITMAP
gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.DeleteObject.restype = c_bool
gdi32.DeleteDC.argtypes = [HDC]
gdi32.DeleteDC.restype = c_bool
gdi32.GetStockObject.argtypes = [c_int]
gdi32.GetStockObject.restype = HGDIOBJ
gdi32.SetStretchBltMode.argtypes = [HDC, c_int]
gdi32.SetStretchBltMode.restype = c_int
gdi32.StretchDIBits.argtypes = [
    HDC,
    c_int, c_int, c_int, c_int,
    c_int, c_int, c_int, c_int,
    c_void_p, c_void_p, c_uint, c_ulong,
]
gdi32.StretchDIBits.restype = c_int
gdi32.BitBlt.argtypes = [
    HDC, c_int, c_int, c_int, c_int,
    HDC, c_int, c_int, c_ulong,
]
gdi32.BitBlt.restype = c_bool
gdi32.CreateFontW.argtypes = [
    c_int, c_int, c_int, c_int, c_int,
    c_ulong, c_ulong, c_ulong,
    c_ulong, c_ulong, c_ulong, c_ulong,
    c_ulong, c_wchar_p,
]
gdi32.CreateFontW.restype = HFONT
gdi32.SetTextColor.argtypes = [HDC, COLORREF]
gdi32.SetTextColor.restype = COLORREF
gdi32.SetBkMode.argtypes = [HDC, c_int]
gdi32.SetBkMode.restype = c_int
gdi32.GetTextExtentPoint32W.argtypes = [HDC, c_wchar_p, c_int, POINTER(SIZE)]
gdi32.GetTextExtentPoint32W.restype = c_bool
gdi32.TextOutW.argtypes = [HDC, c_int, c_int, c_wchar_p, c_int]
gdi32.TextOutW.restype = c_bool
gdi32.SaveDC.argtypes = [HDC]
gdi32.SaveDC.restype = c_int
gdi32.RestoreDC.argtypes = [HDC, c_int]
gdi32.RestoreDC.restype = c_bool
gdi32.IntersectClipRect.argtypes = [HDC, c_int, c_int, c_int, c_int]
gdi32.IntersectClipRect.restype = c_int
gdi32.ChoosePixelFormat.argtypes = [HDC, POINTER(PIXELFORMATDESCRIPTOR)]
gdi32.ChoosePixelFormat.restype = c_int
gdi32.SetPixelFormat.argtypes = [HDC, c_int, POINTER(PIXELFORMATDESCRIPTOR)]
gdi32.SetPixelFormat.restype = c_bool
gdi32.SwapBuffers.argtypes = [HDC]
gdi32.SwapBuffers.restype = c_bool

opengl32.glGetError.argtypes = []
opengl32.glGetError.restype = c_uint

opengl32.wglCreateContext.argtypes = [HDC]
opengl32.wglCreateContext.restype = HGLRC
opengl32.wglDeleteContext.argtypes = [HGLRC]
opengl32.wglDeleteContext.restype = c_bool
opengl32.wglMakeCurrent.argtypes = [HDC, HGLRC]
opengl32.wglMakeCurrent.restype = c_bool
opengl32.wglShareLists.argtypes = [HGLRC, HGLRC]
opengl32.wglShareLists.restype = c_bool
opengl32.wglGetProcAddress.argtypes = [c_char_p]
opengl32.wglGetProcAddress.restype = c_void_p
opengl32.glReadPixels.argtypes = [
    c_int, c_int, c_int, c_int, c_uint, c_uint, c_void_p
]
opengl32.glReadPixels.restype = None
opengl32.glFinish.argtypes = []
opengl32.glFinish.restype = None
opengl32.glPixelStorei.argtypes = [c_uint, c_int]
opengl32.glPixelStorei.restype = None
opengl32.glReadBuffer.argtypes = [c_uint]
opengl32.glReadBuffer.restype = None
opengl32.glGetIntegerv.argtypes = [c_uint, POINTER(c_int)]
opengl32.glGetIntegerv.restype = None
opengl32.glGetString.argtypes = [c_uint]
opengl32.glGetString.restype = c_char_p

msimg32.AlphaBlend.argtypes = [
    HDC, c_int, c_int, c_int, c_int,
    HDC, c_int, c_int, c_int, c_int,
    BLENDFUNCTION,
]
msimg32.AlphaBlend.restype = c_bool


ENV_NAMES = {
    17: "GET_VARIABLE_UPDATE",
    11: "SET_INPUT_DESCRIPTORS",
    24: "GET_SENSOR_INTERFACE",
    36: "SET_MEMORY_MAPS",
    45: "GET_VFS_INTERFACE",
    1: "SET_ROTATION",
    35: "SET_CONTROLLER_INFO",
    65580: "SET_HW_SHARED_CONTEXT",
    65585: "GET_FASTFORWARDING",
    65587: "GET_INPUT_BITMASKS",
    9: "GET_SYSTEM_DIRECTORY",
    12: "SET_KEYBOARD_CALLBACK",
    13: "SET_DISK_CONTROL_INTERFACE",
    14: "SET_HW_RENDER",
    15: "GET_VARIABLE",
    23: "GET_RUMBLE_INTERFACE",
    27: "GET_LOG_INTERFACE",
    28: "GET_PERF_INTERFACE",
    30: "GET_CORE_ASSETS_DIRECTORY",
    31: "GET_SAVE_DIRECTORY",
    52: "GET_CORE_OPTIONS_VERSION",
    53: "SET_CORE_OPTIONS",
    54: "SET_CORE_OPTIONS_INTL",
    55: "SET_CORE_OPTIONS_DISPLAY",
    56: "GET_PREFERRED_HW_RENDER",
    57: "GET_DISK_CONTROL_INTERFACE_VERSION",
    58: "SET_DISK_CONTROL_EXT_INTERFACE",
    69: "SET_SAVE_STATE_IN_BACKGROUND",
    67: "SET_CORE_OPTIONS_V2",
    68: "SET_CORE_OPTIONS_V2_INTL",
}

def decode_cstr(v):
    return v.decode("utf-8", errors="replace") if v else ""


def load_system_configs(systems_dir: Path):
    from system_config import load_system_configs as load
    return load(systems_dir)



def _title_key(value) -> str:
    from title_metadata import _title_key as lookup
    return lookup(value)


def _load_title_json(path: Path) -> dict[str, str]:
    from title_metadata import _load_title_json as load
    return load(path)


def _load_retroarch_playlist_titles(patterns, core_name_filters=None, path_roots=None) -> dict[str, str]:
    from title_metadata import _load_retroarch_playlist_titles as load
    return load(patterns, core_name_filters, path_roots)


def build_title_maps(systems) -> dict[str, dict[str, str]]:
    from title_metadata import build_title_maps as build
    return build(systems, APP_DIR)


def resolve_display_title(system: dict, rom_path: Path, title_maps) -> str:
    from title_metadata import resolve_display_title as resolve
    return resolve(system, rom_path, title_maps)

def should_exclude_rom(system: dict, path: Path):
    from rom_catalog import should_exclude_rom as scan
    return scan(system, path)


def scan_roms(system: dict, progress=None):
    from rom_catalog import scan_roms as scan
    return scan(system, progress)


def prepare_rom(system: dict, rom_path: Path, temp_root: Path) -> Path:
    from startup_preparation import prepare_rom as prepare
    return prepare(system, rom_path, temp_root)


def _resource_group_limit(cfg, group_name):
    from resource_policy import _resource_group_limit as policy
    return policy(cfg, group_name)


def _resource_group_info(system):
    from resource_policy import _resource_group_info as policy
    return policy(system)


def _resource_group_can_add(system, group_usage, cfg, replacing_system=None):
    from resource_policy import _resource_group_can_add as policy
    return policy(system, group_usage, cfg, replacing_system)


def _resource_group_add_usage(system, group_usage):
    from resource_policy import _resource_group_add_usage as policy
    return policy(system, group_usage)


def _resource_group_usage_from_picks(picks):
    from resource_policy import _resource_group_usage_from_picks as policy
    return policy(picks)


def choose_slots(systems, catalogs, cfg, count=4, favorites=None):
    from slot_selection import choose_slots as choose
    return choose(systems, catalogs, cfg, count, favorites)


def get_monitor_rects():
    rects = []

    @MONITORENUMPROC
    def callback(hmonitor, hdc, rect_ptr, lparam):
        r = rect_ptr.contents
        rects.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
        return True

    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise ctypes.WinError()

    # Keep a deterministic left-to-right order for logs/layout construction.
    rects.sort(key=lambda r: (r[0], r[1]))
    return rects


def auto_grid_for_monitor(width: int, height: int):
    from screen_layout import auto_grid_for_monitor as layout
    return layout(width, height)


def build_monitor_slots(monitor_rects, virtual_left, virtual_top, gap_pixels=0, max_slots_per_monitor=16):
    from screen_layout import build_monitor_slots as layout
    return layout(monitor_rects, virtual_left, virtual_top, gap_pixels, max_slots_per_monitor)


def build_windowed_slots(width: int, height: int, count: int, gap_pixels=0):
    from screen_layout import build_windowed_slots as layout
    return layout(width, height, count, gap_pixels)



class WGLHardwareContext:
    """
    Hidden WGL context + libretro-compatible offscreen FBO.

    Supports both:
      - legacy/compat OpenGL contexts (Flycast)
      - OpenGL Core Profile via WGL_ARB_create_context (Dolphin/glcore)
    """

    def __init__(
        self,
        width=640,
        height=480,
        context_type=RETRO_HW_CONTEXT_OPENGL,
        version_major=0,
        version_minor=0,
        debug_context=False,
    ):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.context_type = int(context_type)
        self.version_major = int(version_major or 0)
        self.version_minor = int(version_minor or 0)
        self.debug_context = bool(debug_context)
        self.created_version = None

        self.hwnd = None
        self.hdc = None

        self.core_hglrc = None
        self.frontend_hglrc = None
        self.shared_context_enabled = False
        self._wgl_create_context_attribs = None

        self.fbo = 0
        self.color_tex = 0
        self.depth_stencil_rb = 0
        self.frontend_read_fbo = 0

        self._gl = {}
        self._bootstrap_hglrc = None
        self._ready = False

    @property
    def hglrc(self):
        return self.core_hglrc

    def _create_window_and_pixel_format(self):
        hinst = kernel32.GetModuleHandleW(None)
        self.hwnd = user32.CreateWindowExW(
            0,
            "STATIC",
            "Retro Native Saver HW",
            WS_POPUP,
            0, 0, self.width, self.height,
            None, None, hinst, None,
        )
        if not self.hwnd:
            raise ctypes.WinError()

        self.hdc = user32.GetDC(self.hwnd)
        if not self.hdc:
            raise ctypes.WinError()

        pfd = PIXELFORMATDESCRIPTOR()
        pfd.nSize = ctypes.sizeof(PIXELFORMATDESCRIPTOR)
        pfd.nVersion = 1
        pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER
        pfd.iPixelType = PFD_TYPE_RGBA
        pfd.cColorBits = 32
        pfd.cAlphaBits = 8
        pfd.cDepthBits = 24
        pfd.cStencilBits = 8
        pfd.iLayerType = PFD_MAIN_PLANE

        pf = gdi32.ChoosePixelFormat(self.hdc, byref(pfd))
        if not pf:
            raise RuntimeError("ChoosePixelFormat() failed for WGL context")
        if not gdi32.SetPixelFormat(self.hdc, pf, byref(pfd)):
            raise RuntimeError("SetPixelFormat() failed for WGL context")

    def _load_wgl_create_context_attribs(self):
        addr = opengl32.wglGetProcAddress(b"wglCreateContextAttribsARB")
        value = int(ctypes.cast(addr, c_void_p).value or 0) if addr else 0
        if value in (0, 1, 2, 3, ctypes.c_void_p(-1).value):
            return None

        fn_type = ctypes.WINFUNCTYPE(
            HGLRC,
            HDC,
            HGLRC,
            POINTER(c_int),
        )
        self._wgl_create_context_attribs = fn_type(value)
        return self._wgl_create_context_attribs

    def _create_attrib_context(self, share_context=None):
        creator = self._wgl_create_context_attribs
        if creator is None:
            raise RuntimeError(
                "wglCreateContextAttribsARB unavailable; "
                "cannot create OpenGL Core Profile context"
            )

        requested = (
            self.version_major or 3,
            self.version_minor or 3,
        )

        # RetroArch's glcore driver tries to use the highest desktop
        # Core Profile available even when the core only requests a
        # minimum version (Dolphin asks for 3.3; Intel returns 4.6).
        candidates = [
            (4, 6), (4, 5), (4, 4), (4, 3),
            (4, 2), (4, 1), (4, 0), (3, 3),
        ]

        # Never fall below the core's requested minimum.
        req_num = requested[0] * 100 + requested[1]
        candidates = [
            v for v in candidates
            if v[0] * 100 + v[1] >= req_num
        ]
        if requested not in candidates:
            candidates.append(requested)

        last_error = None
        for major, minor in candidates:
            attrs = [
                WGL_CONTEXT_MAJOR_VERSION_ARB, major,
                WGL_CONTEXT_MINOR_VERSION_ARB, minor,
            ]

            if self.context_type == RETRO_HW_CONTEXT_OPENGL_CORE:
                attrs += [
                    WGL_CONTEXT_PROFILE_MASK_ARB,
                    WGL_CONTEXT_CORE_PROFILE_BIT_ARB,
                ]

            attrs += [0]
            arr = (c_int * len(attrs))(*attrs)

            ctx = creator(
                self.hdc,
                share_context if share_context else None,
                arr,
            )
            if ctx:
                self.created_version = (major, minor)
                return ctx

            last_error = f"{major}.{minor}"

        raise RuntimeError(
            "wglCreateContextAttribsARB() failed for all "
            f"Core Profile candidates >= {requested[0]}.{requested[1]} "
            f"(last={last_error})"
        )

    def create(self):
        if self._ready:
            return
        if self.hwnd or self.hdc or self.core_hglrc or self.frontend_hglrc or self._bootstrap_hglrc:
            raise RuntimeError('WGL resources from an incomplete creation must be closed first')
        try:
            self._create_window_and_pixel_format()
            self._create_core_context()
            self._init_gl_functions()
            self._create_offscreen_fbo()
            self._log_context_created()
            self._ready = True
        except Exception:
            self.close()
            raise

    def make_current(self):
        if not self.hdc or not self.core_hglrc:
            return False
        return bool(opengl32.wglMakeCurrent(self.hdc, self.core_hglrc))

    def make_frontend_current(self):
        if (
            self.shared_context_enabled
            and self.hdc
            and self.frontend_hglrc
        ):
            return bool(
                opengl32.wglMakeCurrent(self.hdc, self.frontend_hglrc)
            )
        return self.make_current()

    def enable_shared_context(self):
        from wgl_safety import checked
        if self.shared_context_enabled:
            return True
        if not self.hdc or not self.core_hglrc:
            return False
        try:
            self.frontend_hglrc = self._create_shared_frontend_context()
            self.shared_context_enabled = True
            checked('activate shared frontend', self.make_frontend_current())
            self._create_frontend_read_fbo()
            checked('restore core context', self.make_current())
            print(f"[hw] shared WGL context enabled coreFBO={self.fbo} readFBO={self.frontend_read_fbo}")
            return True
        except Exception:
            self.close()
            raise

    def _create_shared_frontend_context(self):
        from wgl_safety import checked
        if self.context_type == RETRO_HW_CONTEXT_OPENGL_CORE:
            self.frontend_hglrc = self._create_attrib_context(share_context=self.core_hglrc)
        else:
            self.frontend_hglrc = checked('wglCreateContext shared frontend', opengl32.wglCreateContext(self.hdc))
            checked('wglShareLists', opengl32.wglShareLists(self.core_hglrc, self.frontend_hglrc))
        return self.frontend_hglrc

    def _create_frontend_read_fbo(self):
        fbo = c_uint(0)
        self.glGenFramebuffers(1, byref(fbo))
        self.frontend_read_fbo = int(fbo.value)
        from wgl_safety import checked
        checked("allocate frontend_read_fbo", self.frontend_read_fbo)

        self.glBindFramebuffer(GL_FRAMEBUFFER, self.frontend_read_fbo)
        self.glFramebufferTexture2D(
            GL_FRAMEBUFFER,
            GL_COLOR_ATTACHMENT0,
            GL_TEXTURE_2D,
            self.color_tex,
            0,
        )

        status = int(self.glCheckFramebufferStatus(GL_FRAMEBUFFER))
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(
                f"Shared frontend FBO incomplete: 0x{status:04X}"
            )
        from wgl_safety import gl_checked
        gl_checked(opengl32, "_create_frontend_read_fbo")

    def proc_address(self, name: bytes):
        if not name:
            return 0

        addr = opengl32.wglGetProcAddress(name)
        value = int(ctypes.cast(addr, c_void_p).value or 0) if addr else 0

        invalid = {
            0,
            1,
            2,
            3,
            ctypes.c_void_p(-1).value,
        }
        if value in invalid:
            addr = kernel32.GetProcAddress(c_void_p(opengl32._handle), name)
            value = int(ctypes.cast(addr, c_void_p).value or 0) if addr else 0

        return value

    def _load_gl(self, name, restype, *argtypes):
        key = name.decode("ascii") if isinstance(name, bytes) else str(name)
        bname = key.encode("ascii")
        addr = self.proc_address(bname)
        if not addr:
            raise RuntimeError(f"OpenGL function unavailable: {key}")
        fn = CFUNCTYPE(restype, *argtypes)(addr)
        self._gl[key] = fn
        return fn

    def _init_gl_functions(self):
        from wgl_bindings import bind_gl_functions
        bind_gl_functions(self)

    def _create_core_context(self):
        from wgl_safety import checked
        self._bootstrap_hglrc = checked('wglCreateContext bootstrap', opengl32.wglCreateContext(self.hdc))
        checked('wglMakeCurrent bootstrap', opengl32.wglMakeCurrent(self.hdc, self._bootstrap_hglrc))
        if self.context_type == RETRO_HW_CONTEXT_OPENGL_CORE:
            if not self._load_wgl_create_context_attribs():
                raise RuntimeError('WGL_ARB_create_context not available')
            self.core_hglrc = self._create_attrib_context()
            checked('wglMakeCurrent detach bootstrap', opengl32.wglMakeCurrent(None, None))
            checked('wglDeleteContext bootstrap', opengl32.wglDeleteContext(self._bootstrap_hglrc))
            self._bootstrap_hglrc = None
            checked('activate OpenGL Core context', self.make_current())
        else:
            self.core_hglrc = self._bootstrap_hglrc
            self._bootstrap_hglrc = None


    def _log_context_created(self):
        version = decode_cstr(opengl32.glGetString(GL_VERSION))
        vendor = decode_cstr(opengl32.glGetString(GL_VENDOR))
        renderer = decode_cstr(opengl32.glGetString(GL_RENDERER))

        profile_name = (
            "OpenGL Core"
            if self.context_type == RETRO_HW_CONTEXT_OPENGL_CORE
            else "OpenGL"
        )
        actual = (
            f"{self.created_version[0]}.{self.created_version[1]}"
            if self.created_version
            else "legacy"
        )
        print(
            f"[hw] WGL {profile_name} context created "
            f"{self.width}x{self.height} FBO={self.fbo} "
            f"requested={self.version_major}.{self.version_minor} "
            f"created={actual}"
        )
        print(
            f"[hw] GL version={version} vendor={vendor} renderer={renderer}"
        )

    def _create_color_texture(self):
        tex = c_uint(0)
        self.glGenTextures(1, byref(tex))
        self.color_tex = int(tex.value)
        from wgl_safety import checked
        checked("allocate color_tex", self.color_tex)
        self.glBindTexture(GL_TEXTURE_2D, self.color_tex)
        self.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        self.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        self.glTexImage2D(
            GL_TEXTURE_2D,
            0,
            GL_RGBA8,
            self.width,
            self.height,
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            None,
        )
        from wgl_safety import gl_checked
        gl_checked(opengl32, "_create_color_texture")

    def _create_depth_stencil(self):
        rb = c_uint(0)
        self.glGenRenderbuffers(1, byref(rb))
        self.depth_stencil_rb = int(rb.value)
        from wgl_safety import checked
        checked("allocate depth_stencil_rb", self.depth_stencil_rb)
        self.glBindRenderbuffer(GL_RENDERBUFFER, self.depth_stencil_rb)
        self.glRenderbufferStorage(
            GL_RENDERBUFFER,
            GL_DEPTH24_STENCIL8,
            self.width,
            self.height,
        )
        from wgl_safety import gl_checked
        gl_checked(opengl32, "_create_depth_stencil")

    def _create_core_framebuffer(self):
        fbo = c_uint(0)
        self.glGenFramebuffers(1, byref(fbo))
        self.fbo = int(fbo.value)
        from wgl_safety import checked
        checked("allocate fbo", self.fbo)
        self.glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        self.glFramebufferTexture2D(
            GL_FRAMEBUFFER,
            GL_COLOR_ATTACHMENT0,
            GL_TEXTURE_2D,
            self.color_tex,
            0,
        )
        self.glFramebufferRenderbuffer(
            GL_FRAMEBUFFER,
            GL_DEPTH_STENCIL_ATTACHMENT,
            GL_RENDERBUFFER,
            self.depth_stencil_rb,
        )

        status = int(self.glCheckFramebufferStatus(GL_FRAMEBUFFER))
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(
                f"OpenGL FBO incomplete: 0x{status:04X}"
            )

        self.glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        from wgl_safety import gl_checked
        gl_checked(opengl32, "_create_core_framebuffer")

    def _create_offscreen_fbo(self):
        from wgl_safety import checked
        checked("activate core for FBO allocation", self.make_current())

        self._create_color_texture()

        self._create_depth_stencil()

        self._create_core_framebuffer()

    def framebuffer_id(self):
        return int(self.fbo)

    def capture_bgra(self, width: int, height: int):
        w = max(1, min(int(width), self.width))
        h = max(1, min(int(height), self.height))
        if self.shared_context_enabled:
            return self._capture_shared_bgra(w, h)
        return self._capture_single_bgra(w, h)

    def _read_bgra_buffer(self, w, h):
        buf = (ctypes.c_ubyte * (w * h * 4))()
        opengl32.glReadPixels(
            0, 0, w, h,
            GL_BGRA, GL_UNSIGNED_BYTE,
            ctypes.cast(buf, c_void_p),
        )
        return buf

    def _capture_shared_bgra(self, w, h):
        from wgl_safety import checked
        checked('activate core for capture', self.make_current())
        opengl32.glFinish()
        try:
            checked('activate frontend for capture', self.make_frontend_current())
            self.glBindFramebuffer(GL_READ_FRAMEBUFFER, self.frontend_read_fbo)
            opengl32.glPixelStorei(GL_PACK_ALIGNMENT, 4)
            opengl32.glReadBuffer(GL_COLOR_ATTACHMENT0)
            buf = self._read_bgra_buffer(w, h)
        finally:
            checked('restore core after capture', self.make_current())
        return bytes(buf), w, h

    def _capture_single_bgra(self, w, h):
        from wgl_safety import checked
        checked('activate core for capture', self.make_current())
        prev_fbo = c_int(0)
        prev_read_buffer = c_int(0)
        opengl32.glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, byref(prev_fbo))
        opengl32.glGetIntegerv(GL_READ_BUFFER, byref(prev_read_buffer))
        try:
            self.glBindFramebuffer(GL_READ_FRAMEBUFFER, self.fbo)
            opengl32.glFinish()
            opengl32.glPixelStorei(GL_PACK_ALIGNMENT, 4)
            opengl32.glReadBuffer(GL_COLOR_ATTACHMENT0)
            buf = self._read_bgra_buffer(w, h)
        finally:
            try:
                self.glBindFramebuffer(GL_READ_FRAMEBUFFER, c_uint(prev_fbo.value).value)
            finally:
                opengl32.glReadBuffer(c_uint(prev_read_buffer.value).value)
        return bytes(buf), w, h


    def close(self):
        from wgl_safety import close_resources
        return close_resources(self, opengl32, user32)


class GDIDrawingSurface:
    """Drawing methods for GDIWindow; all handles stay on the same instance.

    The window supplies hwnd and client_size(), initializes the two drawing
    state groups, and controls cleanup ordering. This class owns no separate
    window, callback, timer, or lifetime.
    """
    def _init_backbuffer_state(self):
        self.mem_dc = None
        self.mem_bitmap = None
        self.mem_old_bitmap = None
        self.mem_w = 0
        self.mem_h = 0

    def _init_overlay_state(self):
        self.overlay_system_font = None
        self.overlay_game_font = None
        self.overlay_bg_dc = None
        self.overlay_bg_bitmap = None
        self.overlay_bg_old_bitmap = None

    def _dispose_backbuffer(self):
        from gdi_safety import dispose_bitmap
        return dispose_bitmap(self, gdi32, 'mem_dc', 'mem_bitmap', 'mem_old_bitmap')

    def _create_backbuffer(self, width, height):
        from gdi_safety import checked, selected, release_dc, GDIError, require_released_window_dcs
        require_released_window_dcs(self, user32)
        if self.mem_dc or self.mem_bitmap:
            raise GDIError('Cannot overwrite an unresolved backbuffer')
        hdc = checked('GetDC', user32.GetDC, self.hwnd)
        try:
            self.mem_dc = checked('CreateCompatibleDC', gdi32.CreateCompatibleDC, hdc)
            self.mem_bitmap = checked('CreateCompatibleBitmap', gdi32.CreateCompatibleBitmap, hdc, width, height)
            self.mem_old_bitmap = selected(gdi32.SelectObject, self.mem_dc, self.mem_bitmap)
            self.mem_w, self.mem_h = width, height
        except Exception:
            self._dispose_backbuffer()
            raise
        finally:
            release_dc(user32, self.hwnd, hdc, self)

    def _dispose_overlay_fonts(self):
        from gdi_safety import dispose_fonts
        dispose_fonts(self, gdi32)

    def _ensure_backbuffer(self, width: int, height: int):
        if width == self.mem_w and height == self.mem_h and self.mem_dc and self.mem_bitmap:
            return

        # Dispose old backing bitmap/DC first.
        from gdi_safety import GDIError
        if not self._dispose_overlay_bg_resources():
            raise GDIError('Overlay resources could not be released before resize')
        if not self._dispose_backbuffer():
            raise GDIError('Backbuffer could not be released before resize')
        self._create_backbuffer(width, height)

    def begin_composite(self):
        from gdi_safety import checked, selected, release_dc
        if not self.hwnd:
            return
        dst_w, dst_h = self.client_size()
        self._ensure_backbuffer(dst_w, dst_h)
        rect = RECT(0, 0, dst_w, dst_h)
        brush = checked('GetStockObject', gdi32.GetStockObject, BLACK_BRUSH)
        checked('FillRect', user32.FillRect, self.mem_dc, byref(rect), brush)

    def _fit_inside(self, src_w: int, src_h: int, display_aspect: float,
                    x: int, y: int, w: int, h: int):
        from screen_layout import fit_inside
        return fit_inside(src_w, src_h, display_aspect, x, y, w, h)

    def _pack_dib_rows(self, frame_bytes: bytes, src_w: int, src_h: int,
                       src_pitch: int, bytes_per_pixel: int):
        from frame_format import pack_dib_rows
        return pack_dib_rows(frame_bytes, src_w, src_h, src_pitch, bytes_per_pixel)

    def _make_bitmap_info(self, src_w, src_h, dib_stride, pixel_format, bottom_up):
        is_xrgb = pixel_format == RETRO_PIXEL_FORMAT_XRGB8888
        bmi = BITMAPINFO() if is_xrgb else BITMAPINFO_MASKS()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = src_w
        bmi.bmiHeader.biHeight = src_h if bottom_up else -src_h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32 if is_xrgb else 16
        bmi.bmiHeader.biCompression = BI_RGB if is_xrgb else BI_BITFIELDS
        bmi.bmiHeader.biSizeImage = dib_stride * src_h
        if not is_xrgb:
            if pixel_format == RETRO_PIXEL_FORMAT_RGB565:
                bmi.masks[0] = 0xF800
                bmi.masks[1] = 0x07E0
                bmi.masks[2] = 0x001F
            else:  # 0RGB1555, including the existing unknown-format fallback.
                bmi.masks[0] = 0x7C00
                bmi.masks[1] = 0x03E0
                bmi.masks[2] = 0x001F
        return bmi

    def draw_frame_to_rect(self, frame_bytes: bytes, src_w: int, src_h: int,
                           src_pitch: int, pixel_format: int, display_aspect: float,
                           x: int, y: int, w: int, h: int, bottom_up: bool = False):
        from gdi_safety import checked, selected, release_dc
        if not self.hwnd or not frame_bytes:
            return

        dx, dy, dw, dh = self._fit_inside(
            src_w, src_h, display_aspect, x, y, w, h
        )
        checked('SetStretchBltMode', gdi32.SetStretchBltMode, self.mem_dc,
                getattr(self, 'stretch_blt_mode', HALFTONE))

        bytes_per_pixel = 4 if pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 else 2
        dib_bytes, dib_stride = self._pack_dib_rows(
            frame_bytes, src_w, src_h, src_pitch, bytes_per_pixel
        )
        buf = ctypes.create_string_buffer(dib_bytes)

        bmi = self._make_bitmap_info(src_w, src_h, dib_stride, pixel_format, bottom_up)
        bmi_ptr = byref(bmi)

        checked('StretchDIBits', gdi32.StretchDIBits, 
            self.mem_dc,
            dx, dy, dw, dh,
            0, 0, src_w, src_h,
            buf, bmi_ptr, DIB_RGB_COLORS, SRCCOPY
        )

    def _dispose_overlay_bg_resources(self):
        self._overlay_bg_ready = False
        from gdi_safety import dispose_bitmap
        return dispose_bitmap(self, gdi32, 'overlay_bg_dc', 'overlay_bg_bitmap', 'overlay_bg_old_bitmap')

    def _ensure_overlay_bg_resources(self):
        from gdi_safety import checked, selected
        if self.overlay_bg_dc and self.overlay_bg_bitmap and self.overlay_bg_old_bitmap and getattr(self, '_overlay_bg_ready', True):
            return
        if not self.mem_dc:
            return
        if not self._dispose_overlay_bg_resources():
            return
        try:
            self.overlay_bg_dc = checked('CreateCompatibleDC', gdi32.CreateCompatibleDC, self.mem_dc)
            self.overlay_bg_bitmap = checked('CreateCompatibleBitmap', gdi32.CreateCompatibleBitmap, self.mem_dc, 1, 1)
            self.overlay_bg_old_bitmap = selected(gdi32.SelectObject, self.overlay_bg_dc, self.overlay_bg_bitmap)
            black = RECT(0, 0, 1, 1)
            brush = checked('GetStockObject', gdi32.GetStockObject, BLACK_BRUSH)
            checked('FillRect', user32.FillRect, self.overlay_bg_dc, byref(black), brush)
            self._overlay_bg_ready = True
        except Exception as exc:
            print(f'[gdi] overlay background unavailable: {exc}', flush=True)
            self._dispose_overlay_bg_resources()

    def _draw_overlay_background(self, x: int, y: int, w: int, h: int, alpha: int):
        if w <= 0 or h <= 0:
            return

        alpha = max(0, min(255, int(alpha)))
        if alpha <= 0:
            return

        box = RECT(x, y, x + w, y + h)

        if alpha >= 255:
            self._fill_overlay_black(box)
            return

        self._ensure_overlay_bg_resources()
        if not (self.overlay_bg_dc and self.overlay_bg_bitmap and self.overlay_bg_old_bitmap and getattr(self, '_overlay_bg_ready', True)):
            self._fill_overlay_black(box)
            return

        self._blend_overlay_background(x, y, w, h, alpha, box)

    def _fill_overlay_black(self, box):
        from gdi_safety import checked, selected, release_dc
        brush = checked('GetStockObject', gdi32.GetStockObject, BLACK_BRUSH)
        checked('FillRect', user32.FillRect, self.mem_dc, byref(box), brush)

    def _blend_overlay_background(self, x, y, w, h, alpha, box):
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, alpha, 0)
        ok = msimg32.AlphaBlend(
            self.mem_dc, x, y, w, h,
            self.overlay_bg_dc, 0, 0, 1, 1,
            blend,
        )
        if not ok:
            self._fill_overlay_black(box)

    @staticmethod
    def _colorref_from_hex(value: str, default="#B8B8B8"):
        from frame_format import colorref_from_hex
        return colorref_from_hex(value, default)

    def _create_overlay_font(self, pixel_size, minimum):
        from gdi_safety import checked
        return checked('CreateFontW', gdi32.CreateFontW,
            -max(minimum, int(pixel_size)), 0, 0, 0, FW_NORMAL,
            False, False, False,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE,
            "Segoe UI",
        )

    def _ensure_overlay_fonts(self, system_px: int, game_px: int):
        if not self.overlay_system_font:
            self.overlay_system_font = self._create_overlay_font(system_px, 8)
        if not self.overlay_game_font:
            self.overlay_game_font = self._create_overlay_font(game_px, 9)

    def _draw_overlay_line(self, text_value: str, font: HFONT, color: int,
                           x: int, y: int, padding: int, background_alpha: int,
                           *, top_padding=None, bottom_padding=None):
        from gdi_safety import checked, selected, release_dc
        if not text_value or not font:
            return 0

        old_font = selected(gdi32.SelectObject, self.mem_dc, font)
        try:
            size = SIZE()
            if not gdi32.GetTextExtentPoint32W(
                self.mem_dc, text_value, len(text_value), byref(size)
            ):
                return 0

            top_padding = padding if top_padding is None else top_padding
            bottom_padding = padding if bottom_padding is None else bottom_padding
            box_w = int(size.cx) + padding * 2
            box_h = int(size.cy) + top_padding + bottom_padding
            self._draw_overlay_background(
                x,
                y,
                box_w,
                box_h,
                background_alpha,
            )

            self._paint_overlay_text(text_value, color, x, y, padding, top_padding=top_padding)
            return box_h
        finally:
            selected(gdi32.SelectObject, self.mem_dc, old_font)

    def _paint_overlay_text(self, text_value, color, x, y, padding, *, top_padding=None):
        from gdi_safety import checked, selected, release_dc
        checked('SetBkMode', gdi32.SetBkMode, self.mem_dc, TRANSPARENT)
        checked('SetTextColor', gdi32.SetTextColor, self.mem_dc, color, invalid=(None, -1, 0xFFFFFFFF))
        checked('TextOutW', gdi32.TextOutW, 
            self.mem_dc,
            x + padding,
            y + (padding if top_padding is None else top_padding),
            text_value,
            len(text_value),
        )

    def draw_fade_black(self, alpha: int):
        """Blend black over the complete client area for cycle fades."""
        if not self.hwnd or not self.mem_dc:
            return
        dst_w, dst_h = self.client_size()
        self._draw_overlay_background(
            0,
            0,
            dst_w,
            dst_h,
            max(0, min(255, int(alpha))),
        )

    def draw_overlay(self, system_name: str, game_name: str,
                     x: int, y: int, w: int, h: int, overlay_cfg: dict):
        if not overlay_cfg.get("enabled", True):
            return

        from title_metadata import display_system_name
        system_name = display_system_name(system_name)

        if overlay_cfg.get("scroll_enabled", True):
            from overlay_scroll import draw
            draw(self, gdi32, SIZE, system_name, game_name, x, y, w, h, overlay_cfg)
            return

        margin = max(0, int(overlay_cfg.get("margin", 6)))
        padding = max(0, int(overlay_cfg.get("padding", 4)))
        system_px = int(overlay_cfg.get("system_font_size", 12))
        game_px = int(overlay_cfg.get("game_font_size", 16))
        line_gap = max(0, int(overlay_cfg.get("line_gap", 0)))
        background_alpha = max(0, min(255, int(overlay_cfg.get("background_alpha", 112))))

        self._ensure_overlay_fonts(system_px, game_px)

        system_color = self._colorref_from_hex(
            overlay_cfg.get("system_color", "#909090")
        )
        game_color = self._colorref_from_hex(
            overlay_cfg.get("game_color", "#B8B8B8")
        )

        ox = x + margin
        oy = y + margin

        used = self._draw_overlay_line(
            system_name,
            self.overlay_system_font,
            system_color,
            ox,
            oy,
            padding,
            background_alpha,
            # Keep padding around the pair, not between its two lines.
            bottom_padding=0 if game_name else padding,
        )
        oy += used + line_gap

        self._draw_overlay_line(
            game_name,
            self.overlay_game_font,
            game_color,
            ox,
            oy,
            padding,
            background_alpha,
            top_padding=0 if used else padding,
        )

    def present(self):
        from startup_timing import presented
        pending = getattr(self, "_startup_pending_present", ())
        self._startup_pending_present = []
        from gdi_safety import checked, release_dc, require_released_window_dcs
        if not self.hwnd or not self.mem_dc:
            return
        require_released_window_dcs(self, user32)
        dst_w, dst_h = self.client_size()
        hdc = checked('GetDC', user32.GetDC, self.hwnd)
        try:
            checked('BitBlt', gdi32.BitBlt, 
                hdc,
                0, 0, dst_w, dst_h,
                self.mem_dc,
                0, 0,
                SRCCOPY
            )
            presented(self, pending)
        finally:
            release_dc(user32, self.hwnd, hdc, self)


class GDIWindow(GDIDrawingSurface):
    def __init__(
        self,
        width=1280,
        height=720,
        fullscreen=False,
        mouse_exit_threshold=12,
        parent_hwnd=None,
        preview_mode=False,
        hide_cursor=True,
        embedded_rect=None,
    ):
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.mouse_exit_threshold = mouse_exit_threshold
        self.parent_hwnd = HWND(parent_hwnd) if parent_hwnd else None
        self.preview_mode = bool(preview_mode)
        self.hide_cursor = bool(hide_cursor)
        self.embedded_rect = embedded_rect
        self.cursor_hidden = False
        self.should_close = False
        self.first_mouse = None
        self.power_notification = None
        self.display_was_off = False
        self.display_was_dimmed = False
        self.exit_on_display_off = False
        self.hold_on_display_power = False
        self.power_idle = False
        self.exit_reason = "input"
        self.hwnd = None
        self._init_backbuffer_state()
        self.virtual_left = 0
        self.virtual_top = 0
        self.virtual_width = width
        self.virtual_height = height
        self._init_overlay_state()
        self._class_name = "RetroNativeSaverWindow"
        self._wndproc = WNDPROC(self._proc)

    def _note_exit(self, hwnd, reason, details=""):
        # Keep the first exit reason through WM_CLOSE/WM_DESTROY/WM_QUIT.
        if not self.should_close:
            self.exit_reason = reason
            print(f"[exit] reason={reason}", flush=True)

    def _request_display_exit(self, hwnd, reason):
        if not self.should_close:
            self._note_exit(hwnd, reason)
            self.should_close = True
            print(f"[display-power] {reason}; closing saver", flush=True)
            # Hide immediately; the supervisor's existing Job Object cleanup
            # terminates even a worker blocked inside a graphics driver call.
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def _unregister_power_notification(self):
        from gdi_safety import release
        if self.power_notification and release('UnregisterPowerSettingNotification', user32.UnregisterPowerSettingNotification, self.power_notification):
            self.power_notification = None

    def _handle_power_message(self, hwnd, wparam, lparam):
        if wparam == PBT_POWERSETTINGCHANGE and lparam:
            event = ctypes.cast(lparam, POINTER(PowerBroadcastSetting)).contents
            if bytes(event.guid) == SESSION_DISPLAY_GUID and event.length == 4:
                state = int(event.state)
                print(f"[display-power] session display state={state}", flush=True)
                if state in (0, 2) and getattr(self, "hold_on_display_power", False):
                    self.display_was_dimmed = state == 2
                    self.display_was_off = state == 0
                    if not self.power_idle:
                        self.power_idle = True
                        print("[display-power] standby requested; stopping emulators, keeping saver alive", flush=True)
                    return 1
                if state == 1 and getattr(self, "power_idle", False):
                    self.display_was_dimmed = False
                    self.display_was_off = False
                    self._request_display_exit(hwnd, "display-resumed-from-standby")
                    return 1
                if state == 2:
                    self.display_was_dimmed = True
                    if self.exit_on_display_off:
                        self._request_display_exit(hwnd, "display-dimmed")
                elif state == 0:
                    self.display_was_off = True
                    if self.exit_on_display_off:
                        self._request_display_exit(hwnd, "display-off")
                elif state == 1:
                    self.display_was_dimmed = False
                    if self.display_was_off:
                        self.display_was_off = False
                        self._request_display_exit(hwnd, "display-resumed")
        elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
            self._request_display_exit(hwnd, "system-resumed")
        return 1

    def _handle_mouse_move(self, hwnd, lparam):
        # Tile replacement can deliver a synthetic/local-coordinate jump.
        # Confirm movement using the cursor in the shared screen coordinate space.
        point = POINT()
        if not user32.GetCursorPos(byref(point)):
            if not getattr(self, "cursor_read_failed", False):
                print(f"[input] GetCursorPos failed; mouse notification ignored", flush=True)
            self.cursor_read_failed = True
            return 0
        self.cursor_read_failed = False
        x, y = int(point.x), int(point.y)
        if self.first_mouse is None:
            self.first_mouse = (x, y)
        else:
            sx, sy = self.first_mouse
            if abs(x - sx) + abs(y - sy) >= self.mouse_exit_threshold:
                self._note_exit(hwnd, "mouse-move")
                self.should_close = True
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return 0

    def _proc(self, hwnd, msg, wparam, lparam):
        if self.fullscreen and not self.preview_mode:
            if msg == WM_DISPLAYCHANGE and not getattr(self, "power_idle", False):
                self._request_display_exit(hwnd, "display-configuration-changed")
                return 0
            if msg == WM_POWERBROADCAST:
                return self._handle_power_message(hwnd, wparam, lparam)
        if not self.preview_mode and not self.should_close and not self.power_idle:
            from saver_controls import handle_message
            if handle_message(getattr(self, 'saver_controls', None), msg, wparam, lparam):
                return 0
        if not self.preview_mode and msg in (
            WM_KEYDOWN, WM_SYSKEYDOWN, WM_LBUTTONDOWN,
            WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_MOUSEWHEEL
        ):
            names = {WM_KEYDOWN: "key-down", WM_SYSKEYDOWN: "system-key-down",
                     WM_LBUTTONDOWN: "left-button", WM_RBUTTONDOWN: "right-button",
                     WM_MBUTTONDOWN: "middle-button", WM_MOUSEWHEEL: "mouse-wheel"}
            self._note_exit(hwnd, names[msg], f"message=0x{msg:04X}")
            self.should_close = True
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0
        if not self.preview_mode and msg == WM_MOUSEMOVE:
            return self._handle_mouse_move(hwnd, lparam)
        if msg == WM_ERASEBKGND:
            # v0.3: suppress visible background erase. Frames are presented
            # from an off-screen buffer in one BitBlt operation.
            return 1
        if msg == WM_CLOSE:
            self._note_exit(hwnd, "WM_CLOSE")
            self.should_close = True
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self._note_exit(hwnd, "WM_DESTROY")
            self._unregister_power_notification()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _register_window_class(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = ctypes.cast(self._wndproc, c_void_p).value
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, c_void_p(IDC_ARROW))
        wc.hbrBackground = 0
        wc.lpszClassName = self._class_name
        atom = user32.RegisterClassW(byref(wc))
        if not atom and ctypes.get_last_error() != 1410:  # already exists
            raise ctypes.WinError()

        return hinst

    def _prepare_window_geometry(self):
        parent = None

        if self.parent_hwnd:
            # The Windows Settings preview host can disappear between process
            # startup and child-window creation. Treat that as a normal exit.
            if not user32.IsWindow(self.parent_hwnd):
                self.should_close = True
                print("[preview] parent window disappeared before create()", flush=True)
                return None

            r = RECT()
            if not user32.GetClientRect(self.parent_hwnd, byref(r)):
                if not user32.IsWindow(self.parent_hwnd):
                    self.should_close = True
                    print(
                        "[preview] parent window disappeared before GetClientRect()",
                        flush=True,
                    )
                    return None
                raise ctypes.WinError()

            self.virtual_left = 0
            self.virtual_top = 0
            self.virtual_width = max(1, int(r.right - r.left))
            self.virtual_height = max(1, int(r.bottom - r.top))

            x = 0
            y = 0
            w = self.virtual_width
            h = self.virtual_height
            style = WS_CHILD | WS_VISIBLE
            ex_style = 0
            parent = self.parent_hwnd
            if self.embedded_rect is not None:
                x, y, w, h = map(int, self.embedded_rect)
                self.virtual_width, self.virtual_height = w, h

        elif self.fullscreen:
            self.virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            self.virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            self.virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            self.virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            x = self.virtual_left
            y = self.virtual_top
            w = self.virtual_width
            h = self.virtual_height
            style = WS_POPUP
            ex_style = WS_EX_TOPMOST

        else:
            self.virtual_left = 0
            self.virtual_top = 0
            self.virtual_width = self.width
            self.virtual_height = self.height

            x = y = CW_USEDEFAULT
            w, h = self.width, self.height
            style = WS_OVERLAPPEDWINDOW
            ex_style = 0

        return x, y, w, h, style, ex_style, parent

    def _show_created_window(self):
        if self.fullscreen and not self.preview_mode:
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(SESSION_DISPLAY_GUID)
            self.power_notification = user32.RegisterPowerSettingNotification(
                self.hwnd, byref(guid), 0)
            if self.power_notification:
                print("[display-power] session notifications registered", flush=True)
            else:
                print("[display-power] notification registration failed", flush=True)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        if not self.preview_mode and self.hide_cursor:
            user32.ShowCursor(False)
            self.cursor_hidden = True

    def create(self):
        hinst = self._register_window_class()

        geometry = self._prepare_window_geometry()
        if geometry is None:
            return False
        x, y, w, h, style, ex_style, parent = geometry

        self.hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, f"Retro Native Saver {APP_VERSION}", style | 0x02000000,
            x, y, w, h, parent, None, hinst, None
        )
        if not self.hwnd:
            raise ctypes.WinError()
        self._show_created_window()

        return True

    def pump(self):
        guard = getattr(self, "supervisor_guard", None)
        if guard is not None:
            guard.beat()
        msg = MSG()
        while user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == 0x0012:  # WM_QUIT
                self._note_exit(getattr(self, "hwnd", None), "WM_QUIT")
                self.should_close = True
                return
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))

    def client_size(self):
        from gdi_safety import checked
        r = RECT()
        checked('GetClientRect', user32.GetClientRect, self.hwnd, byref(r))
        return max(1, r.right - r.left), max(1, r.bottom - r.top)

    def close(self):
        from gdi_safety import release_pending_dcs, release
        release_pending_dcs(self, user32)
        self._unregister_power_notification()
        self._dispose_overlay_bg_resources()

        self._dispose_overlay_fonts()

        self._dispose_backbuffer()
        if self.overlay_system_font or self.overlay_game_font:
            self._dispose_overlay_fonts()

        if self.cursor_hidden:
            try:
                user32.ShowCursor(True)
            except Exception as exc:
                print(f'[gdi-cleanup] ShowCursor: {exc}', flush=True)
            else:
                self.cursor_hidden = False
        if self.hwnd:
            # WM_CLOSE may already have destroyed it. Do not keep a stale HWND.
            try:
                alive = bool(user32.IsWindow(self.hwnd))
            except Exception as exc:
                print(f'[gdi-cleanup] IsWindow: {exc}', flush=True)
                alive = True
            if not alive or release('DestroyWindow', user32.DestroyWindow, self.hwnd):
                self.hwnd = None


class LibretroCore:
    def __init__(
        self,
        core_path: Path,
        system_dir: Path,
        save_dir: Path,
        assets_dir: Path | None = None,
        core_options=None,
        render_backend="software",
        hw_context_width=640,
        hw_context_height=480,
        hw_readback=True,
        env_trace_frames=0,
        provide_log_interface=True,
        provide_perf_interface=True,
        frame_rebind_context=True,
        trace_core_vars=False,
        destroy_hw_before_unload=False,
    ):
        self.core_path = core_path.resolve()
        self.system_dir = system_dir.resolve()
        self.save_dir = save_dir.resolve()
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir = (
            assets_dir.resolve()
            if assets_dir is not None
            else self.system_dir
        )
        self._system_dir_bytes = str(self.system_dir).encode("utf-8")
        self._save_dir_bytes = str(self.save_dir).encode("utf-8")
        self._assets_dir_bytes = str(self.assets_dir).encode("utf-8")
        self._system_dir_cstr = c_char_p(self._system_dir_bytes)
        self._save_dir_cstr = c_char_p(self._save_dir_bytes)
        self._assets_dir_cstr = c_char_p(self._assets_dir_bytes)
        self.pixel_format = RETRO_PIXEL_FORMAT_0RGB1555
        self.frame_bytes = None
        self.frame_w = self.frame_h = self.frame_pitch = 0
        self.frame_bottom_up = False
        self._software_rotation = 0
        self._pending_hw_frame = None
        self.display_aspect = 0.0
        self.render_backend = str(render_backend or "software").lower()
        self.hw_context_width = max(1, int(hw_context_width))
        self.hw_context_height = max(1, int(hw_context_height))
        self.hw_readback = bool(hw_readback)
        self.env_trace_frames = max(0, int(env_trace_frames))
        self.provide_log_interface = bool(provide_log_interface)
        self.provide_perf_interface = bool(provide_perf_interface)
        self.frame_rebind_context = bool(frame_rebind_context)
        self.trace_core_vars = bool(trace_core_vars)
        self.destroy_hw_before_unload = bool(destroy_hw_before_unload)
        self._native_fault_during_close = False
        self._cleanup_requires_recycle = False
        self._callback_error = None
        self._run_frame_index = 0
        self._startup_input = None
        self._keyboard_event = None
        self.hw_context = None
        self._pending_hw_request = None
        self._hw_shared_requested = False
        self.hw_context_reset_addr = 0
        self.hw_context_destroy_addr = 0
        self.hw_context_reset_done = False
        self._hw_get_fb_cb = None
        self._hw_get_proc_cb = None
        self._log_cb = None
        self._perf_get_time_usec_cb = None
        self._perf_get_cpu_features_cb = None
        self._perf_get_counter_cb = None
        self._perf_register_cb = None
        self._perf_start_cb = None
        self._perf_stop_cb = None
        self._perf_log_cb = None
        self._frame_layout_logged = False
        self.variables = {}
        self.core_option_overrides = {
            str(k): str(v).encode("utf-8")
            for k, v in (core_options or {}).items()
        }
        self.system_info = None
        self._game_data_buffer = None
        self.debug_hw = False
        self._in_load_game = False
        self._initialized = False
        self._game_loaded = False
        self._cleanup_uncertain = False
        self.dll = ctypes.CDLL(str(self.core_path))
        try:
            self._bind_api()
            self._install_callbacks()
            from core_callbacks import raise_pending
            raise_pending(self)
        except Exception:
            self.close()
            raise

    def _bind_api(self):
        from libretro_abi import bind_api
        bind_api(self.dll)

    def _register_perf_interface(self, data):
        from core_callbacks import protect
        if not self.provide_perf_interface or not data:
            return False

        import time as _time

        @RetroPerfGetTimeUsecCallback
        @protect(self, 'get_time_usec', 0)
        def get_time_usec():
            return int(_time.perf_counter_ns() // 1000)

        @RetroPerfGetCpuFeaturesCallback
        @protect(self, 'get_cpu_features', 0)
        def get_cpu_features():
            # Diagnostic frontend: report no optional SIMD feature bits.
            return 0

        @RetroPerfGetCounterCallback
        @protect(self, 'get_perf_counter', 0)
        def get_perf_counter():
            return int(_time.perf_counter_ns())

        @RetroPerfRegisterCallback
        @protect(self, 'perf_register', None)
        def perf_register(counter):
            if counter:
                counter[0].registered = True

        @RetroPerfStartCallback
        @protect(self, 'perf_start', None)
        def perf_start(counter):
            if counter:
                counter[0].start = int(_time.perf_counter_ns())

        @RetroPerfStopCallback
        @protect(self, 'perf_stop', None)
        def perf_stop(counter):
            if counter:
                now = int(_time.perf_counter_ns())
                start = int(counter[0].start)
                if start:
                    counter[0].total += max(0, now - start)
                    counter[0].call_cnt += 1

        @RetroPerfLogCallback
        @protect(self, 'perf_log', None)
        def perf_log():
            return None

        self._perf_get_time_usec_cb = get_time_usec
        self._perf_get_cpu_features_cb = get_cpu_features
        self._perf_get_counter_cb = get_perf_counter
        self._perf_register_cb = perf_register
        self._perf_start_cb = perf_start
        self._perf_stop_cb = perf_stop
        self._perf_log_cb = perf_log

        cb = ctypes.cast(data, POINTER(RetroPerfCallback))
        cb[0].get_time_usec = ctypes.cast(self._perf_get_time_usec_cb, c_void_p).value
        cb[0].get_cpu_features = ctypes.cast(self._perf_get_cpu_features_cb, c_void_p).value
        cb[0].get_perf_counter = ctypes.cast(self._perf_get_counter_cb, c_void_p).value
        cb[0].perf_register = ctypes.cast(self._perf_register_cb, c_void_p).value
        cb[0].perf_start = ctypes.cast(self._perf_start_cb, c_void_p).value
        cb[0].perf_stop = ctypes.cast(self._perf_stop_cb, c_void_p).value
        cb[0].perf_log = ctypes.cast(self._perf_log_cb, c_void_p).value
        return True

    def _register_hw_render(self, data):
        from core_callbacks import protect
        if self.render_backend not in ("opengl", "glcore") or not data:
            return False

        hw = ctypes.cast(data, POINTER(RetroHWRenderCallback))[0]
        requested = int(hw.context_type)
        if requested not in (
            RETRO_HW_CONTEXT_OPENGL,
            RETRO_HW_CONTEXT_OPENGL_CORE,
        ):
            print(f"[hw] unsupported context request={requested}")
            return False

        # IMPORTANT: SET_HW_RENDER is called by the core during
        # retro_load_game(). A libretro frontend should accept/register
        # the request here, then create the actual graphics context
        # after retro_load_game() has returned and before context_reset().
        self.hw_context_reset_addr = int(hw.context_reset or 0)
        self.hw_context_destroy_addr = int(hw.context_destroy or 0)
        self._pending_hw_request = {
            "context_type": requested,
            "version_major": int(hw.version_major),
            "version_minor": int(hw.version_minor),
            "debug_context": bool(hw.debug_context),
        }

        @RetroHWGetCurrentFramebufferCallback
        @protect(self, 'get_current_framebuffer', 0)
        def get_current_framebuffer():
            if not self.hw_context:
                return 0
            return self.hw_context.framebuffer_id()

        @RetroHWGetProcAddressCallback
        @protect(self, 'get_proc_address', 0)
        def get_proc_address(sym):
            if not self.hw_context:
                return 0
            return self.hw_context.proc_address(sym)

        self._hw_get_fb_cb = get_current_framebuffer
        self._hw_get_proc_cb = get_proc_address

        hw.get_current_framebuffer = ctypes.cast(
            self._hw_get_fb_cb, c_void_p
        ).value
        hw.get_proc_address = ctypes.cast(
            self._hw_get_proc_cb, c_void_p
        ).value

        self.frame_bottom_up = True
        print(
            f"[hw] SET_HW_RENDER accepted/deferred context={requested} "
            f"version={int(hw.version_major)}.{int(hw.version_minor)}"
        )
        return True

    def _receive_video(self, data, width, height, pitch):
        w, h = int(width), int(height)

        data_value = int(data or 0)
        if (
            self.hw_context is not None
            and data_value == RETRO_HW_FRAME_BUFFER_VALID
        ):
            # IMPORTANT:
            # Do not touch shared OpenGL state from inside the libretro
            # video callback. Hardware cores such as Dolphin can still be
            # finishing GL work here. Just latch the requested frame size;
            # readback happens after retro_run() has completely returned.
            self._pending_hw_frame = (w, h)
            return

        if not data:
            return

        p = int(pitch)
        self.frame_bottom_up = False

        # v0.4: keep the libretro framebuffer in its native pixel format.
        # For common SNES software formats (0RGB1555/RGB565/XRGB8888),
        # GDI can consume it directly via StretchDIBits + BI_BITFIELDS.
        frame = ctypes.string_at(data, p * h)
        rotation = getattr(self, '_software_rotation', 0)
        if rotation:
            from frame_format import rotate_frame
            frame, w, h, p = rotate_frame(frame, w, h, p,
                4 if self.pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 else 2, rotation)
        self.frame_bytes = frame
        self.frame_w = w
        self.frame_h = h
        self.frame_pitch = p

        if not self._frame_layout_logged:
            bpp = 4 if self.pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 else 2
            row_bytes = w * bpp
            dib_stride = (row_bytes + 3) & ~3
            print(
                f"[frame] {w}x{h} pixel_format={self.pixel_format} "
                f"libretro_pitch={p} row_bytes={row_bytes} "
                f"gdi_stride={dib_stride}"
            )
            self._frame_layout_logged = True

    def _prepare_game_info(self, rom: Path):
        if self.system_info is not None and "WonderSwan" in decode_cstr(self.system_info.library_name):
            if "wswan_rotate_display" not in self.core_option_overrides:
                from wonderswan_rotation import orientation_from_rom
                orientation = orientation_from_rom(rom)
                self.core_option_overrides["wswan_rotate_display"] = orientation.encode('ascii')
                print(f"[video-rotation] WonderSwan ROM orientation={orientation}; core software rotation", flush=True)
        self._rom_path_bytes = str(rom.resolve()).encode("utf-8")

        need_fullpath = True
        if self.system_info is not None:
            need_fullpath = bool(self.system_info.need_fullpath)

        if need_fullpath:
            gi = RetroGameInfo(c_char_p(self._rom_path_bytes), None, 0, None)
        else:
            data = rom.read_bytes()
            self._game_data_buffer = ctypes.create_string_buffer(data)
            gi = RetroGameInfo(
                c_char_p(self._rom_path_bytes),
                ctypes.cast(self._game_data_buffer, c_void_p),
                len(data),
                None,
            )

        return gi

    def _read_pending_hw_frame(self):
        # Diagnostic mode can deliberately avoid *all* frontend GL work after
        # retro_run(). If Dolphin survives frame 2+ only in this mode, the
        # readback/state handoff is conclusively implicated.
        if (
            self.hw_context
            and self._pending_hw_frame
            and self.hw_readback
        ):
            w, h = self._pending_hw_frame
            self._pending_hw_frame = None

            from wgl_safety import checked
            checked("activate core HW context", self.hw_context.make_current())
            frame, cw, ch = self.hw_context.capture_bgra(w, h)
            self.frame_bytes = frame
            self.frame_w = cw
            self.frame_h = ch
            self.frame_pitch = cw * 4
            self.pixel_format = RETRO_PIXEL_FORMAT_XRGB8888
            self.frame_bottom_up = True

            if not self._frame_layout_logged:
                print(
                    f"[frame-hw] {cw}x{ch} OpenGL BGRA "
                    f"pitch={self.frame_pitch} deferred"
                )
                self._frame_layout_logged = True

        elif self.hw_context and self._pending_hw_frame:
            if not self._frame_layout_logged:
                w, h = self._pending_hw_frame
                print(
                    f"[frame-hw] {w}x{h} readback DISABLED "
                    f"(diagnostic)",
                    flush=True,
                )
                self._frame_layout_logged = True
            self._pending_hw_frame = None

    def _register_log_interface(self, data):
        # retro_log_printf_t is a C variadic printf-style callback.
        # ctypes cannot safely implement a true variadic callback.
        # Diagnostic builds can reject the interface entirely, which
        # is explicitly allowed by libretro.
        from core_callbacks import protect
        if not self.provide_log_interface or not data:
            return False

        @RetroLogPrintfCallback
        @protect(self, 'retro_log', None)
        def retro_log(level, msg):
            # Release frontend: keep Flycast's log interface valid,
            # but do not spam the screen saver console.
            return None

        self._log_cb = retro_log
        cb = ctypes.cast(data, POINTER(RetroLogCallback))
        cb[0].log = ctypes.cast(self._log_cb, c_void_p).value
        return True

    def _set_variables(self, data):
        ptr = ctypes.cast(data, POINTER(RetroVariable)); i = 0
        if self.trace_core_vars:
            print("[corevar] SET_VARIABLES begin", flush=True)
        while ptr[i].key:
            key = decode_cstr(ptr[i].key)
            raw = decode_cstr(ptr[i].value)

            from core_options import register_variable
            register_variable(key, raw, self.variables, self.core_option_overrides, self.trace_core_vars)

            i += 1

        if self.trace_core_vars:
            for k, v in sorted(self.core_option_overrides.items()):
                vv = v.decode("utf-8", errors="replace")
                present = k in self.variables
                print(
                    f"[corevar] override-summary key={k} "
                    f"value={vv!r} registered={present}",
                    flush=True,
                )
            print("[corevar] SET_VARIABLES end", flush=True)
        return True

    def _get_variable(self, data):
        if not data:
            return True

        var_ptr = ctypes.cast(data, POINTER(RetroVariable))
        key = decode_cstr(var_ptr[0].key)

        from core_options import lookup_variable
        val = lookup_variable(key, self.variables, self.core_option_overrides, self.trace_core_vars)

        if val is not None:
            var_ptr[0].value = val
        else:
            var_ptr[0].value = None

        return True

    def _handle_environment(self, cmd, data):
        if (
            self.env_trace_frames > 0
            and 0 < self._run_frame_index <= self.env_trace_frames
        ):
            print(
                f"[env-frame {self._run_frame_index}] "
                f"cmd={int(cmd)} {ENV_NAMES.get(int(cmd), '?')} "
                f"data=0x{int(data or 0):X}",
                flush=True,
            )
        if cmd == RETRO_ENVIRONMENT_GET_CAN_DUPE:
            ctypes.cast(data, POINTER(c_bool))[0] = True; return True
        if cmd == RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
            ctypes.cast(data, POINTER(c_char_p))[0] = self._system_dir_cstr; return True
        if cmd == RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
            ctypes.cast(data, POINTER(c_char_p))[0] = self._save_dir_cstr; return True
        if cmd == RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY:
            ctypes.cast(data, POINTER(c_char_p))[0] = self._assets_dir_cstr; return True

        if cmd == RETRO_ENVIRONMENT_SET_ROTATION:
            # Beetle WonderSwan rotates pixels and updates geometry itself
            # when frontend rotation is unavailable. Do not claim support.
            if self.system_info is not None and "WonderSwan" in decode_cstr(self.system_info.library_name):
                return False
            if self.system_info is not None and decode_cstr(self.system_info.library_name) == 'FinalBurn Neo':
                if not data:
                    return False
                rotation = ctypes.cast(data, POINTER(ctypes.c_uint))[0]
                if rotation > 3:
                    return False
                if rotation != getattr(self, '_software_rotation', 0):
                    print(f'[video-rotation] FBNeo software rotation={rotation * 90} degrees counter-clockwise', flush=True)
                self._software_rotation = rotation
                # FBNeo already reports its intended display aspect ratio.
                # Only its software pixels/dimensions/pitch need rotation.
                return True
            # Dreamcast content used here is horizontal; accept the request.
            return True

        if cmd == RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
            # No gameplay input UI is exposed by the screen saver.
            return True

        if cmd == RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE:
            # Rumble is irrelevant for a non-interactive screen saver.
            return False

        if cmd == RETRO_ENVIRONMENT_GET_FASTFORWARDING:
            if data:
                ctypes.cast(data, POINTER(c_bool))[0] = False
                return True
            return False

        if cmd == RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:
            # We do not expose libretro joypad bitmask input.
            return False

        if cmd == RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
            return self._register_log_interface(data)

        if cmd == RETRO_ENVIRONMENT_GET_PERF_INTERFACE:
            return self._register_perf_interface(data)

        if cmd == RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK:
            from favorite_input import register_keyboard_callback
            return register_keyboard_callback(self, data)

        if cmd == RETRO_ENVIRONMENT_GET_DISK_CONTROL_INTERFACE_VERSION:
            if data:
                ctypes.cast(data, POINTER(c_uint))[0] = 1
                return True
            return False

        if cmd in (
            RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE,
            RETRO_ENVIRONMENT_SET_DISK_CONTROL_EXT_INTERFACE,
        ):
            # Single-disc playback does not need frontend-driven disc swaps.
            # Accept registration so Flycast can continue its normal init path.
            return True

        if cmd == RETRO_ENVIRONMENT_SET_SAVE_STATE_IN_BACKGROUND:
            return True

        if cmd == RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT:
            # This request is normally made during retro_load_game(),
            # before the frontend creates the actual HW context.
            # Record it now and honor it after retro_load_game returns.
            self._hw_shared_requested = True
            print("[hw] shared HW context requested (deferred)", flush=True)
            return True

        if cmd == RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER:
            if self.render_backend == "glcore":
                ctypes.cast(data, POINTER(c_uint))[0] = RETRO_HW_CONTEXT_OPENGL_CORE
                print("[hw] preferred libretro HW context=OpenGL Core", flush=True)
                return True
            if self.render_backend == "opengl":
                ctypes.cast(data, POINTER(c_uint))[0] = RETRO_HW_CONTEXT_OPENGL
                print("[hw] preferred libretro HW context=OpenGL", flush=True)
                return True
            ctypes.cast(data, POINTER(c_uint))[0] = RETRO_HW_CONTEXT_NONE
            return False

        if cmd == RETRO_ENVIRONMENT_SET_HW_RENDER:
            return self._register_hw_render(data)

        if cmd == RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
            fmt = int(ctypes.cast(data, POINTER(c_uint))[0])
            if fmt in (RETRO_PIXEL_FORMAT_0RGB1555, RETRO_PIXEL_FORMAT_XRGB8888, RETRO_PIXEL_FORMAT_RGB565):
                self.pixel_format = fmt
                print(f"[libretro] pixel format={fmt}")
                return True
            return False
        if cmd == RETRO_ENVIRONMENT_SET_VARIABLES:
            return self._set_variables(data)
        if cmd == RETRO_ENVIRONMENT_GET_VARIABLE:
            return self._get_variable(data)
        if cmd == RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
            ctypes.cast(data, POINTER(c_bool))[0] = False; return True
        if cmd == RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
            ctypes.cast(data, POINTER(c_uint))[0] = 0; return True
        if cmd in (
            RETRO_ENVIRONMENT_SET_CORE_OPTIONS,
            RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL,
        ):
            return False
        if cmd == RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY:
            # UI-only hint. Native Saver has no options UI, so accept as no-op.
            return True
        if cmd == RETRO_ENVIRONMENT_SET_GEOMETRY:
            try:
                geo = ctypes.cast(data, POINTER(RetroGameGeometry))[0]
                if float(geo.aspect_ratio) > 0:
                    self.display_aspect = float(geo.aspect_ratio)
            except Exception:
                pass
            return True

        if cmd == RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:
            try:
                av = ctypes.cast(data, POINTER(RetroSystemAVInfo))[0]
                if float(av.geometry.aspect_ratio) > 0:
                    self.display_aspect = float(av.geometry.aspect_ratio)
            except Exception:
                pass
            return True

        return False

    def _install_callbacks(self):
        from core_callbacks import protect
        @EnvironmentCallback
        @protect(self, 'env', False)
        def env(cmd, data):
            return self._handle_environment(cmd, data)

        @VideoRefreshCallback
        @protect(self, 'video', None)
        def video(data, width, height, pitch):
            return self._receive_video(data, width, height, pitch)

        @AudioSampleCallback
        def audio_sample(l, r):
            return
        @AudioSampleBatchCallback
        def audio_batch(data, frames):
            return frames
        @InputPollCallback
        def input_poll():
            return
        @InputStateCallback
        @protect(self, 'input_state', 0)
        def input_state(port, device, index, ident):
            if self._startup_input is not None:
                return self._startup_input.state(port, device, index, ident)
            return 0

        self._env = env; self._video = video; self._audio = audio_sample; self._audio_batch = audio_batch
        self._poll = input_poll; self._state = input_state
        self.dll.retro_set_environment(env)
        self.dll.retro_set_video_refresh(video)
        self.dll.retro_set_audio_sample(audio_sample)
        self.dll.retro_set_audio_sample_batch(audio_batch)
        self.dll.retro_set_input_poll(input_poll)
        self.dll.retro_set_input_state(input_state)

    def initialize(self):
        import startup_timing as startup
        from core_callbacks import raise_pending
        raise_pending(self)
        v = int(self.dll.retro_api_version())
        if v != RETRO_API_VERSION:
            raise RuntimeError(f"Unsupported libretro API version: {v}")
        try:
            startup.measure("retro_init", self.dll.retro_init)
            raise_pending(self)
        except Exception as exc:
            from core_lifecycle import retain_uncertain
            retain_uncertain(self, str(exc))
            raise
        self._initialized = True
        info = RetroSystemInfo()
        self.dll.retro_get_system_info(byref(info))
        raise_pending(self)
        self.system_info = info
        print(
            f"[core] {decode_cstr(info.library_name)} {decode_cstr(info.library_version)} "
            f"extensions={decode_cstr(info.valid_extensions)} "
            f"need_fullpath={bool(info.need_fullpath)} block_extract={bool(info.block_extract)}"
        )

    def _create_deferred_hw_context(self):
        if self.hw_context is not None:
            return
        if not self._pending_hw_request:
            return

        req = self._pending_hw_request
        self.hw_context = WGLHardwareContext(
            self.hw_context_width,
            self.hw_context_height,
            context_type=int(req["context_type"]),
            version_major=int(req["version_major"]),
            version_minor=int(req["version_minor"]),
            debug_context=bool(req["debug_context"]),
        )
        from startup_timing import measure
        measure("wgl_create", self.hw_context.create)

        if self._hw_shared_requested:
            try:
                self.hw_context.enable_shared_context()
            except Exception:
                if self.hw_context.close():
                    self.hw_context = None
                raise

        print("[hw] deferred HW context creation completed", flush=True)

    def load_game(self, rom: Path):
        import startup_timing as startup
        from core_callbacks import raise_pending
        raise_pending(self)
        gi = startup.measure("game_info_prepare", self._prepare_game_info, rom)

        # No graphics context is made current here. SET_HW_RENDER during
        # retro_load_game() only registers the core's request.
        self._in_load_game = True
        try:
            loaded = bool(startup.measure("retro_load_game", self.dll.retro_load_game, byref(gi)))
            raise_pending(self)
        except Exception as exc:
            from core_lifecycle import retain_uncertain
            retain_uncertain(self, str(exc))
            raise
        finally:
            self._in_load_game = False

        if not loaded:
            raise RuntimeError(f"retro_load_game() failed: {rom}")

        self._game_loaded = True

        # Query geometry before frontend HW context creation, matching the
        # RetroArch lifecycle seen in the normal Dolphin/glcore log.
        av = RetroSystemAVInfo()
        self.dll.retro_get_system_av_info(byref(av))
        raise_pending(self)

        # Only now create WGL/FBO resources requested by SET_HW_RENDER.
        self._create_deferred_hw_context()

        if (
            self.hw_context
            and not self.hw_context_reset_done
            and self.hw_context_reset_addr
        ):
            from wgl_safety import checked
            checked("activate core HW context", self.hw_context.make_current())
            reset_cb = RetroHWContextResetCallback(self.hw_context_reset_addr)
            try:
                startup.measure("context_reset", reset_cb)
                raise_pending(self)
            except Exception as exc:
                from core_lifecycle import retain_uncertain
                retain_uncertain(self, str(exc))
                raise
            self.hw_context_reset_done = True
            print("[hw] libretro context_reset completed", flush=True)
        aspect = float(av.geometry.aspect_ratio)
        if aspect <= 0 and av.geometry.base_height:
            aspect = float(av.geometry.base_width) / float(av.geometry.base_height)
        self.display_aspect = aspect

        print(
            f"[video] base={av.geometry.base_width}x{av.geometry.base_height} "
            f"max={av.geometry.max_width}x{av.geometry.max_height} "
            f"aspect={self.display_aspect:.3f} fps={av.timing.fps:.3f}"
        )
        return av

    def run_frame(self):
        from startup_timing import point
        from core_callbacks import raise_pending
        raise_pending(self)
        self._run_frame_index += 1
        if self._startup_input is not None and self._startup_input.advance(time.monotonic()):
            if getattr(self._startup_input, 'favorite', False):
                from favorite_input import input_summary
                print(f"[favorite-input] {self._startup_input_label} {input_summary(self._startup_input.config)} pressed", flush=True)
            else:
                print(f"[startup-input] {self._startup_input_label} START {self._startup_input.count}/2", flush=True)

        if self.hw_context and self.frame_rebind_context:
            from wgl_safety import checked
            checked("activate core HW context", self.hw_context.make_current())

        if getattr(self._startup_input, 'favorite', False):
            self._startup_input.dispatch_keyboard(getattr(self, '_keyboard_event', None))
            raise_pending(self)
        self._pending_hw_frame = None

        if self.env_trace_frames > 0 and self._run_frame_index <= self.env_trace_frames:
            print(
                f"[run] frame={self._run_frame_index} retro_run ENTER "
                f"readback={self.hw_readback} "
                f"rebind={self.frame_rebind_context} "
                f"logif={self.provide_log_interface} "
                f"perfif={self.provide_perf_interface}",
                flush=True,
            )

        if self._run_frame_index == 1:
            point("first_retro_run_begin")
        self.dll.retro_run()
        if self._run_frame_index == 1:
            point("first_retro_run_return")
        raise_pending(self)

        if self.env_trace_frames > 0 and self._run_frame_index <= self.env_trace_frames:
            print(
                f"[run] frame={self._run_frame_index} retro_run RETURN "
                f"pending_hw={self._pending_hw_frame}",
                flush=True,
            )

        self._read_pending_hw_frame()
        if self.frame_bytes and not getattr(self, "_startup_frame_recorded", False):
            self._startup_frame_recorded = True
            point("first_frame_ready", width=self.frame_w, height=self.frame_h,
                  **getattr(self, "_startup_identity", {}))

    def close(self):
        from core_lifecycle import close_core
        close_core(self, kernel32, RetroHWContextResetCallback)



def prepare_dolphin_user_config(save_dir: Path, core_values: dict):
    from startup_preparation import prepare_dolphin_user_config as prepare
    return prepare(save_dir, core_values)

def start_slot_with_retry(slot_index, initial_system, initial_rom,
                          systems, catalogs, cfg, temp_root,
                          failed_roms, max_attempts=5, worker_mode=False,
                          cycle_number=0, cycle_group_usage=None, favorite_retries=None, favorite_inputs=None):
    """
    Start one slot. If a selected ROM/core fails to load, mark that ROM as failed
    for this run and retry with another candidate. The whole saver continues.
    """
    import startup_timing as startup
    from slot_selection import initial_retry_candidates
    candidates, enabled_supported = initial_retry_candidates(initial_system, initial_rom, systems, catalogs, failed_roms, favorite_retries)
    favorite_fallback_logged = False
    preferred_system = initial_system

    attempt = 0
    while attempt < max_attempts:
        attempt += 1

        if candidates:
            system, rom = candidates.pop(0)
        else:
            if favorite_retries is not None and not favorite_fallback_logged:
                print("[favorites] favorite startup candidates exhausted; trying normal ROMs", flush=True)
                favorite_fallback_logged = True
            from slot_selection import normal_retry_candidate
            selected = normal_retry_candidate(preferred_system, enabled_supported, catalogs, failed_roms, cycle_group_usage, cfg)
            if selected is None:
                continue
            system, rom = selected

        if favorite_inputs is not None:
            from favorite_input import system_for_favorite_rom
            system = system_for_favorite_rom(system, rom, favorite_inputs)
        sid = system["id"]
        rom_key = str(rom)

        if rom_key in failed_roms:
            continue

        from startup_preparation import prepare_core_paths
        prepared_paths = prepare_core_paths(system, APP_DIR, temp_root, slot_index, attempt, failed_roms, rom_key)
        if prepared_paths is None:
            continue
        source_core, slot_core, slot_dir = prepared_paths

        core = None
        try:
            write_runtime_trace(
                "START_ENTER",
                cycle=cycle_number,
                slot=slot_index + 1,
                system=system.get("name", sid),
                rom=rom.name,
            )

            startup.point("core_preparation", slot=slot_index + 1, system=sid, rom=str(rom), cycle=cycle_number, attempt=attempt)
            startup.measure("core_copy", shutil.copy2, source_core, slot_core)
            actual_rom = startup.measure("rom_prepare", prepare_rom, system, rom, slot_dir)

            from startup_preparation import prepare_environment
            system_dir, save_dir, assets_dir, core_options = startup.measure("environment_prepare", prepare_environment,
                system, cfg, slot_dir, slot_index, sid, resolve_app_relative_path,
            )

            from startup_preparation import create_configured_core
            core = startup.measure("core_construct", create_configured_core,
                LibretroCore, slot_core, system_dir, save_dir, assets_dir, core_options, system,
            )
            core._startup_identity = dict(slot=slot_index + 1, system=sid, rom=str(rom), cycle=cycle_number)
            startup.measure("core_initialize", core.initialize)
            av = startup.measure("core_load", core.load_game, actual_rom)
            from startup_preparation import apply_loaded_core_settings
            apply_loaded_core_settings(core, system, sid)

            write_runtime_trace(
                "START_RETURN",
                cycle=cycle_number,
                slot=slot_index + 1,
                system=system.get("name", sid),
                rom=rom.name,
            )

            print(
                f"[slot {slot_index + 1}] READY "
                f"[{system['name']}] {rom.name}"
            )
            if favorite_retries is not None and cycle_group_usage is not None:
                from favorites import record_favorite_startup
                record_favorite_startup(initial_system, system, rom, favorite_retries, cycle_group_usage)

            return core, av, system, rom

        except Exception as exc:
            startup_phase = (
                "START_NATIVE_FAULT"
                if is_native_access_violation(exc)
                else "START_FAILED"
            )
            write_runtime_trace(
                startup_phase,
                cycle=cycle_number,
                slot=slot_index + 1,
                system=system.get("name", sid),
                rom=rom.name,
            )

            print(
                f"[slot {slot_index + 1}] START FAILED "
                f"[{system['name']}] {rom.name}: {exc}"
            )
            failed_roms.add(rom_key)

            if core is not None:
                if bool(system.get("process_recycle_required", False)):
                    print(
                        "[shutdown] process-isolated core failed during startup; "
                        "skipping unsafe in-process close",
                        flush=True,
                    )
                    if worker_mode:
                        print(
                            "[worker] startup failure in process-isolated core; "
                            "terminating worker cleanly",
                            flush=True,
                        )
                        hard_exit_process(WORKER_RESTART_EXIT_CODE)
                else:
                    try:
                        core.close()
                        if worker_mode and (getattr(core, '_cleanup_requires_recycle', False) or getattr(core, '_native_fault_during_close', False)):
                            hard_exit_process(WORKER_RESTART_EXIT_CODE)
                    except Exception:
                        pass
            from core_lifecycle import ensure_no_retained_resources
            ensure_no_retained_resources()

    raise RuntimeError(
        f"slot {slot_index + 1}: failed to start a game after {max_attempts} attempts"
    )



def parse_screensaver_args(argv):
    from launch_options import parse_screensaver_args as parse_args
    return parse_args(argv)


def show_config_dialog():
    config_path = APP_DIR / "config.json"
    message = (
        "Retro Native Saver の設定は config.json で変更できます。\\n\\n"
        f"{config_path}\\n\\n"
        "ゲーム切り替え時間、オーバーレイ、systems設定などを編集してください。"
    )
    user32.MessageBoxW(
        None,
        message,
        "Retro Native Saver",
        0x00000040,  # MB_ICONINFORMATION
    )


def main():
    import startup_timing as startup
    launch_mode, preview_parent, cli_args = parse_screensaver_args(sys.argv[1:])

    if "--rom-lists" in cli_args:
        from rom_list_editor import show_rom_list_editor
        from launch_options import parse_rom_list_args
        options = parse_rom_list_args(cli_args, APP_DIR)

        try:
            show_rom_list_editor(APP_DIR, options.config)
        except Exception as exc:
            user32.MessageBoxW(None, f"ROMリスト画面を開けませんでした。\n{exc}",
                               "Retro Native Saver", 0x10)
            return 1
        return 0

    if launch_mode == "config":
        show_config_dialog()
        return 0

    # Windows Settings may destroy/recreate its preview host very quickly.
    # A stale /p HWND is normal during that transition; exit quietly instead
    # of raising WinError 1400 from GetClientRect().
    if launch_mode == "preview":
        if not preview_parent:
            return 0
        if not user32.IsWindow(HWND(preview_parent)):
            print(
                f"[preview] parent HWND is no longer valid: {preview_parent}",
                flush=True,
            )
            return 0

    from launch_options import parse_main_args
    args = parse_main_args(cli_args, APP_DIR)

    worker_mode = bool(args.worker)

    if worker_mode:
        init_runtime_trace_from_env()

    write_runtime_trace("CONFIG_LOAD")
    from launch_options import load_config
    from config_snapshot import load_worker_config
    try:
        with startup.span("worker_config_load"):
            cfg = load_worker_config(args.config, os.environ) if worker_mode else load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"[config] cannot start saver: {args.config}: {exc}", flush=True)
        return 2
    systems_dir = APP_DIR / cfg.get("systems_dir", "systems")
    favorites_path = resolve_app_relative_path(cfg.get("favorites_file"), "favorites.json")
    if args.favorites:
        try:
            show_favorites_editor(APP_DIR, systems_dir, favorites_path)
        except Exception as exc:
            print(f"[favorites] editor could not open: {exc}", flush=True)
            user32.MessageBoxW(None,
                "お気に入り設定画面を開けませんでした。\n"
                "PythonのTcl/Tkを含めてビルドし直してください。\n"
                f"favorites.json を直接編集することもできます。\n\n{exc}",
                "Retro Native Saver — お気に入り設定", 0x10)
            return 1
        return 0
    from single_system_mode import prepare_session, selected_systems, monitor_slots, scheduler_inputs, scheduler_config
    cfg = prepare_session(cfg, APP_DIR, args, launch_mode, reuse=worker_mode)
    systems = startup.measure("system_config_load", load_system_configs, systems_dir)

    from system_config import apply_cli_system_overrides
    systems = apply_cli_system_overrides(systems, args)

    if launch_mode == "preview":
        from system_config import filter_preview_systems
        systems = filter_preview_systems(systems)

    session_quarantine = {}
    session_disabled_systems = set()
    if worker_mode:
        (
            session_quarantine,
            session_disabled_systems,
        ) = _load_session_safety_from_env()

        from system_config import apply_session_suspensions
        apply_session_suspensions(systems, session_quarantine, session_disabled_systems)

    write_runtime_trace("TITLE_CATALOG")
    print("[prepare] loading title catalogs", flush=True)
    title_maps = startup.measure("title_catalog", build_title_maps, systems)

    from rom_catalog import build_catalogs
    catalogs = startup.measure("rom_catalog_all", build_catalogs,
        systems, title_maps, worker_mode, session_quarantine, write_runtime_trace,
        catalog_path=APP_DIR / 'state/rom_catalog.json',
    )
    favorite_catalogs = catalogs
    if worker_mode and not cfg.get('independent_slots_enabled', False):
        # Persistent exclusions affect ordinary selection, while the input
        # catalog still protects favorites from this session's failed ROMs.
        from runtime_catalogs import load_state
        _, _, _, catalogs = startup.measure('cycle_safety', load_state,
            sys.modules[__name__], systems, catalogs, cfg, whitelist_seed=True)

    from system_config import display_mode
    preview_mode, fullscreen = display_mode(launch_mode, cfg, args)
    single_system = selected_systems(cfg, systems, catalogs) if not preview_mode else None

    win = GDIWindow(
        int(cfg.get("window_width", 1280)),
        int(cfg.get("window_height", 720)),
        fullscreen=fullscreen,
        mouse_exit_threshold=int(cfg.get("mouse_exit_threshold", 12)),
        parent_hwnd=preview_parent if preview_mode else None,
        preview_mode=preview_mode,
    )
    win.hold_on_display_power = bool(fullscreen and not preview_mode and cfg.get("independent_slots_enabled", False))
    from saver_controls import enabled as controls_enabled, ForwardKeys
    if controls_enabled(cfg) and not preview_mode:
        win.saver_controls = ForwardKeys(user32)  # consume reserved keys until scheduler is ready
    if startup.measure("worker_window_create", win.create) is False:
        return 0

    if fullscreen and bool(cfg.get("multi_monitor", True)):
        monitor_rects = get_monitor_rects()
        slot_rects = monitor_slots(monitor_rects, win.virtual_left, win.virtual_top,
                                  int(cfg.get('gap_pixels', 0)), systems=single_system) if single_system is not None else None
        if slot_rects is None:
            single_system = None
            slot_rects = build_monitor_slots(
                monitor_rects,
                win.virtual_left,
                win.virtual_top,
                gap_pixels=int(cfg.get("gap_pixels", 0)),
                max_slots_per_monitor=int(cfg.get("max_slots_per_monitor", 16)),
            )
    else:
        dst_w, dst_h = win.client_size()
        from system_config import requested_slot_count
        requested_slots = requested_slot_count(cfg, args, preview_mode)

        slot_rects = monitor_slots([(0, 0, dst_w, dst_h)], 0, 0,
                                  int(cfg.get('gap_pixels', 0)), systems=single_system) if single_system is not None and fullscreen else None
        if slot_rects is None:
            slot_rects = build_windowed_slots(
                dst_w,
                dst_h,
                requested_slots,
                gap_pixels=int(cfg.get("gap_pixels", 0)),
            )
        kind = "preview" if preview_mode else "windowed"
        print(f"[display] {kind} slots={len(slot_rects)}")

    slot_count = len(slot_rects)
    startup.point("layout", slots=slot_count, independent=bool(cfg.get("independent_slots_enabled", False) and not preview_mode), rects=slot_rects)
    if slot_count <= 0:
        raise RuntimeError("No display slots were created.")

    if cfg.get("independent_slots_enabled", False) and not preview_mode:
        from independent_slots import run_scheduler
        if args.cycle_seconds is not None:
            cfg = dict(cfg, cycle_seconds=args.cycle_seconds,
                       _cycle_seconds_override=True)
        try:
            if single_system is not None:
                systems, catalogs = scheduler_inputs(single_system, catalogs, slot_count)
                cfg = scheduler_config(cfg)
                print(f"[presentation] active=single-system group={','.join(s['id'] for s in single_system)} slots={slot_count}", flush=True)
            return run_scheduler(sys.modules[__name__], win, slot_rects,
                                 systems, catalogs, cfg, favorites_path, title_maps)
        finally:
            win.close()

    from system_config import cycle_settings
    cycle_enabled, cycle_seconds, retry_attempts, overlay_cfg, fade_enabled, fade_duration, runtime_heartbeat_seconds = cycle_settings(cfg, args, preview_mode)

    temp = tempfile.TemporaryDirectory(
        prefix="retro_native_multi_",
        ignore_cleanup_errors=True,
    )
    temp_root = Path(temp.name)

    failed_roms = set()
    cycle_number = 0

    try:
        while not win.should_close:
            cycle_number += 1
            print(f"[cycle] === CYCLE {cycle_number} ===")

            write_runtime_trace(
                "CYCLE_START",
                cycle=cycle_number,
            )

            from favorites import load_cycle_favorites
            favorites = startup.measure("favorites_match", load_cycle_favorites, favorites_path, systems, favorite_catalogs, failed_roms)
            picks = choose_slots(systems, catalogs, cfg, slot_count, favorites=favorites)

            print("[selector] selected:")
            for i, (system, rom) in enumerate(picks, 1):
                print(f"  slot {i}: [{system['name']}] {rom.name}")

            cycle_group_usage = _resource_group_usage_from_picks(
                picks
            )

            # Clear the entire virtual desktop while the next cycle is loading.
            win.begin_composite()
            win.present()

            cycle_dir = temp_root / f"cycle_{cycle_number}"
            cycle_dir.mkdir(parents=True, exist_ok=True)

            cores = []
            av_infos = []
            slot_overlays = []
            slot_runtime_contexts = []
            cycle_requires_process_recycle = False

            try:
                for i, (system, rom) in enumerate(picks):
                    win.pump()
                    if win.should_close:
                        if worker_mode and cycle_requires_process_recycle:
                            print(
                                "[worker] user exit; terminating process without core unload",
                                flush=True,
                            )
                            hard_exit_process(0)
                        break

                    from favorites import cycle_favorite_retries
                    favorite_retries = cycle_favorite_retries(i, system, rom, favorites, picks, slot_count, cfg)
                    core, av, actual_system, actual_rom = start_slot_with_retry(
                        i,
                        system,
                        rom,
                        systems,
                        catalogs,
                        cfg,
                        cycle_dir,
                        failed_roms,
                        max_attempts=max(retry_attempts, len(favorite_retries or []) + 1),
                        worker_mode=worker_mode,
                        cycle_number=cycle_number,
                        cycle_group_usage=cycle_group_usage,
                        favorite_retries=favorite_retries,
                        favorite_inputs=favorites,
                    )
                    cores.append(core)
                    av_infos.append(av)

                    if bool(actual_system.get("process_recycle_required", False)):
                        cycle_requires_process_recycle = True
                        setattr(core, "_skip_inprocess_close", True)

                    from title_metadata import append_slot_metadata
                    append_slot_metadata(actual_system, actual_rom, title_maps, slot_overlays, slot_runtime_contexts)

                if win.should_close:
                    if worker_mode and cycle_requires_process_recycle:
                        print(
                            "[worker] user exit; terminating process without core unload",
                            flush=True,
                        )
                        hard_exit_process(0)
                    break

                # In the unlikely event fewer cores were created than display
                # slots, the remaining slots simply stay black.
                from runtime_policy import cycle_frame_timing, cycle_fade_alpha
                fps, step = cycle_frame_timing(av_infos)
                next_t = time.perf_counter()
                cycle_started = time.monotonic()
                next_heartbeat = cycle_started + runtime_heartbeat_seconds
                render_loop_count = 0
                run_frame_call_count = 0

                while not win.should_close:
                    win.pump()
                    if win.should_close:
                        if worker_mode and cycle_requires_process_recycle:
                            print(
                                "[worker] user exit; terminating process without core unload",
                                flush=True,
                            )
                            hard_exit_process(0)
                        break

                    render_loop_count += 1

                    for slot_index, core in enumerate(cores):
                        if slot_index < len(slot_runtime_contexts):
                            runtime_system, runtime_rom = (
                                slot_runtime_contexts[slot_index]
                            )
                        else:
                            runtime_system, runtime_rom = ("?", "?")

                        run_frame_call_count += 1
                        write_runtime_trace(
                            "RUN_ENTER",
                            cycle=cycle_number,
                            slot=slot_index + 1,
                            system=runtime_system,
                            rom=runtime_rom,
                            loop_count=render_loop_count,
                            call_count=run_frame_call_count,
                        )

                        try:
                            core.run_frame()
                        except OSError as exc:
                            print(
                                f"[runtime] slot {slot_index + 1} "
                                f"[{runtime_system}] {runtime_rom} "
                                f"run_frame failed: {exc}",
                                flush=True,
                            )

                            write_runtime_trace(
                                "RUN_EXCEPTION",
                                cycle=cycle_number,
                                slot=slot_index + 1,
                                system=runtime_system,
                                rom=runtime_rom,
                                loop_count=render_loop_count,
                                call_count=run_frame_call_count,
                            )

                            if worker_mode and is_native_access_violation(exc):
                                print(
                                    "[worker] native access violation in "
                                    "run_frame; recycling worker without cleanup",
                                    flush=True,
                                )
                                hard_exit_process(WORKER_RESTART_EXIT_CODE)
                            raise

                        write_runtime_trace(
                            "RUN_RETURN",
                            cycle=cycle_number,
                            slot=slot_index + 1,
                            system=runtime_system,
                            rom=runtime_rom,
                            loop_count=render_loop_count,
                            call_count=run_frame_call_count,
                        )

                    win.begin_composite()
                    for core, rect in zip(cores, slot_rects):
                        if core.frame_bytes:
                            win.draw_frame_to_rect(
                                core.frame_bytes,
                                core.frame_w,
                                core.frame_h,
                                core.frame_pitch,
                                core.pixel_format,
                                core.display_aspect,
                                *rect,
                                bottom_up=core.frame_bottom_up,
                            )

                    if overlay_cfg.get("enabled", True):
                        for (system_name, game_name), rect in zip(
                            slot_overlays, slot_rects
                        ):
                            win.draw_overlay(
                                system_name,
                                game_name,
                                *rect,
                                overlay_cfg=overlay_cfg,
                            )

                    # Nintendo-Saver-style fade through black.
                    #
                    # Start of cycle:
                    #     black -> current game image
                    #
                    # End of cycle:
                    #     current game image -> black
                    #
                    # This deliberately fades the final compositor output
                    # instead of individual cores. It therefore also works
                    # safely with process-isolated Dolphin/LRPS2/MAME workers.
                    now_mono = time.monotonic()
                    elapsed = now_mono - cycle_started
                    fade_alpha = cycle_fade_alpha(elapsed, fade_enabled, fade_duration, cycle_enabled, cycle_seconds)
                    if fade_alpha > 0:
                        win.draw_fade_black(fade_alpha)

                    if cycle_number == 1 and len(getattr(win, "_startup_unfaded_slots", ())) < len(cores):
                        startup.arm_presentation(win, [i + 1 for i, c in enumerate(cores) if c.frame_bytes], fade_alpha)
                    win.present()

                    if now_mono >= next_heartbeat:
                        if slot_runtime_contexts:
                            hb_system, hb_rom = slot_runtime_contexts[-1]
                        else:
                            hb_system, hb_rom = ("?", "?")

                        print(
                            f"[heartbeat] cycle={cycle_number} "
                            f"elapsed={elapsed:.1f}s "
                            f"render_loops={render_loop_count} "
                            f"run_frame_calls={run_frame_call_count} "
                            f"active_slots={len(cores)} "
                            f"last_slot={len(cores)} "
                            f"[{hb_system}] {hb_rom}",
                            flush=True,
                        )
                        next_heartbeat = now_mono + runtime_heartbeat_seconds

                    if cycle_enabled and elapsed >= cycle_seconds:
                        print(
                            f"[cycle] switching after {elapsed:.1f}s"
                        )
                        write_runtime_trace(
                            "CYCLE_SWITCH",
                            cycle=cycle_number,
                            loop_count=render_loop_count,
                            call_count=run_frame_call_count,
                        )
                        if worker_mode and cycle_requires_process_recycle:
                            print(
                                "[worker] process recycle requested; "
                                "skipping buggy Dolphin unload",
                                flush=True,
                            )
                            hard_exit_process(WORKER_RESTART_EXIT_CODE)
                        break

                    next_t += step
                    delay = next_t - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                    elif delay < -0.25:
                        next_t = time.perf_counter()

            finally:
                for reverse_index in range(len(cores) - 1, -1, -1):
                    core = cores[reverse_index]
                    slot_number = reverse_index + 1
                    if reverse_index < len(slot_runtime_contexts):
                        close_system, close_rom = (
                            slot_runtime_contexts[reverse_index]
                        )
                    else:
                        close_system, close_rom = ("?", "?")

                    write_runtime_trace(
                        "CLOSE_ENTER",
                        cycle=cycle_number,
                        slot=slot_number,
                        system=close_system,
                        rom=close_rom,
                    )

                    if (
                        worker_mode
                        and bool(getattr(core, "_skip_inprocess_close", False))
                    ):
                        print(
                            "[shutdown] skipping in-process close for "
                            f"process-isolated core slot={slot_number} "
                            f"[{close_system}] {close_rom}",
                            flush=True,
                        )
                        write_runtime_trace(
                            "CLOSE_SKIPPED",
                            cycle=cycle_number,
                            slot=slot_number,
                            system=close_system,
                            rom=close_rom,
                        )
                        continue

                    try:
                        core.close()
                    except Exception as exc:
                        print(
                            f"[shutdown] core close warning "
                            f"slot={slot_number} [{close_system}] "
                            f"{close_rom}: {exc}",
                            flush=True,
                        )
                        write_runtime_trace(
                            "CLOSE_EXCEPTION",
                            cycle=cycle_number,
                            slot=slot_number,
                            system=close_system,
                            rom=close_rom,
                        )

                    if worker_mode and getattr(core, '_cleanup_requires_recycle', False):
                        print(f"[worker] incomplete core cleanup; recycling worker slot={slot_number}", flush=True)
                        write_runtime_trace('CLOSE_INCOMPLETE', cycle=cycle_number, slot=slot_number,
                                            system=close_system, rom=close_rom)
                        hard_exit_process(WORKER_RESTART_EXIT_CODE)

                    if (
                        worker_mode
                        and bool(
                            getattr(
                                core,
                                "_native_fault_during_close",
                                False,
                            )
                        )
                    ):
                        print(
                            "[worker] native fault during core shutdown; "
                            f"slot={slot_number} [{close_system}] "
                            f"{close_rom}; recycling poisoned worker",
                            flush=True,
                        )
                        write_runtime_trace(
                            "CLOSE_NATIVE_FAULT",
                            cycle=cycle_number,
                            slot=slot_number,
                            system=close_system,
                            rom=close_rom,
                        )
                        hard_exit_process(WORKER_RESTART_EXIT_CODE)

                    write_runtime_trace(
                        "CLOSE_RETURN",
                        cycle=cycle_number,
                        slot=slot_number,
                        system=close_system,
                        rom=close_rom,
                    )

                from core_lifecycle import ensure_no_retained_resources
                ensure_no_retained_resources()

                # Show black immediately between cycles.
                if win and not win.should_close:
                    try:
                        win.begin_composite()
                        win.present()
                    except Exception:
                        pass

                shutil.rmtree(cycle_dir, ignore_errors=True)

            if not cycle_enabled:
                break

        return 0

    finally:
        if win:
            win.close()
        temp.cleanup()


def wait_for_scheduler_standby(backdrop, job, proc, trace):
    """Keep the existing scheduler window alive; fall back if it cannot stop tiles."""
    deadline = time.monotonic() + 5.0
    acknowledged = False
    print("[power-standby] preserving scheduler parent; waiting for tile-stop acknowledgement", flush=True)
    while not backdrop.should_close:
        backdrop.pump()
        if backdrop.should_close or proc.poll() is not None:
            return 0
        state = read_runtime_trace(trace) if trace is not None else None
        if state and state.get("phase") == "SLOT_POWER_IDLE" and not acknowledged:
            acknowledged = True
            print("[power-standby] scheduler acknowledged; parent window retained", flush=True)
        if not acknowledged and time.monotonic() >= deadline:
            print("[power-standby] scheduler acknowledgement timeout; terminating worker group", flush=True)
            if not kernel32.TerminateJobObject(job, 0):
                raise RuntimeError("Could not stop unresponsive scheduler group")
            return wait_for_display_resume(backdrop, None)
        time.sleep(0.05)
    return 0


def wait_for_display_resume(backdrop, job):
    """Release every emulator, keep the saver window/message loop alive until input/on."""
    if job:
        print("[power-standby] closing worker Job Object; no worker restart", flush=True)
        if not kernel32.CloseHandle(job):
            raise RuntimeError("Could not close worker Job Object for power standby")
    print("[power-standby] waiting with black backdrop; emulators stopped", flush=True)
    while not backdrop.should_close:
        backdrop.pump()
        if not backdrop.should_close:
            time.sleep(0.05)
    print(f"[power-standby] finished reason={backdrop.exit_reason}", flush=True)
    return 0


def create_supervisor_backdrop(cfg: dict):
    """
    Create a persistent black full-virtual-desktop window owned by the
    supervisor.

    Worker windows are created later with the same TOPMOST status and therefore
    sit above this backdrop. If a worker exits/recycles/crashes, the black
    supervisor window remains visible instead of exposing the desktop.
    """
    if not bool(cfg.get("supervisor_black_backdrop", True)):
        print("[supervisor] black backdrop disabled by config", flush=True)
        return None

    backdrop = GDIWindow(
        int(cfg.get("window_width", 1280)),
        int(cfg.get("window_height", 720)),
        fullscreen=True,
        mouse_exit_threshold=int(cfg.get("mouse_exit_threshold", 12)),
        parent_hwnd=None,
        preview_mode=False,
        hide_cursor=False,
    )
    # Separate window class/title for easier diagnosis in Win32 tools.
    backdrop._class_name = "RetroNativeSaverBackdrop"
    # Stop GPU work as soon as Windows turns the displays off. The supervisor
    # remains responsive even when a core is blocked in a graphics call.
    backdrop.hold_on_display_power = True
    from saver_controls import enabled as controls_enabled, ForwardKeys
    if controls_enabled(cfg):
        backdrop.saver_controls = ForwardKeys(user32)
    try:
        if backdrop.create() is False:
            return None
        backdrop.begin_composite()
        backdrop.present()
    except Exception:
        # The caller has not received the window yet, so cleanup belongs here.
        backdrop.close()
        raise
    print(
        "[supervisor] persistent black backdrop ready "
        f"rect=({backdrop.virtual_left},{backdrop.virtual_top},"
        f"{backdrop.virtual_width},{backdrop.virtual_height})",
        flush=True,
    )
    return backdrop


def supervisor_main():
    """
    Keep the Windows screensaver host alive while emulation runs in a worker.

    Full-screen mode also owns a persistent black backdrop window. The worker
    draws above it; worker restarts therefore reveal black instead of the
    desktop.

    Workers are attached to a Windows Job Object with KILL_ON_JOB_CLOSE so an
    unexpected supervisor/.scr termination cannot leave a worker orphaned.
    """
    import startup_timing as startup
    raw_args = list(sys.argv[1:])

    if "--supervisor-guard" in raw_args:
        from supervisor_guard import watch
        index = raw_args.index("--supervisor-guard")
        watch(int(raw_args[index+1]), int(raw_args[index+2]), raw_args[index+3], raw_args[index+4])
        return 0


    if "--slot-worker" in raw_args:
        from independent_slots import run_slot
        run_slot(sys.modules[__name__], raw_args[raw_args.index("--slot-worker") + 1])
        return 0

    if "--worker" in raw_args:
        print(
            f"[worker] entering main pid={os.getpid()} ppid={os.getppid()}",
            flush=True,
        )
        return main()

    launch_mode, _preview_parent, remaining = parse_screensaver_args(raw_args)

    # Configuration is trivial and does not load a libretro core.
    if "--update-rom-catalog" in remaining:
        from fixed_rom_catalog import run_update_command
        return run_update_command(APP_DIR, remaining)

    if launch_mode == "config" or "--favorites" in remaining or "--rom-lists" in remaining:
        return main()

    # Windows passes /p HWND for its tiny preview host. Do not add a second
    # process hop or supervisor backdrop in preview mode.
    if launch_mode == "preview":
        return main()

    # Resolve the same config path main() would use. This is intentionally
    # lightweight: supervisor only needs backdrop-related values.
    from launch_options import load_supervisor_config
    try:
        with startup.span("supervisor_config_load"):
            supervisor_cfg = load_supervisor_config(remaining, APP_DIR)
    except (OSError, ValueError):
        return 2

    from single_system_mode import prepare_session
    from launch_options import parse_main_args
    supervisor_cfg = prepare_session(supervisor_cfg, APP_DIR,
                                     parse_main_args(remaining, APP_DIR), launch_mode)

    backdrop = None
    guard = None
    job = None
    runtime_trace_mm = None
    runtime_trace_tag = None
    config_snapshot = None
    proc = None
    worker_assigned = False
    launch_channel = None
    launch_pick = None

    from supervisor_safety import SupervisorSafety
    from supervisor_watchdog import WorkerWatchdog, terminate_hung_worker
    safety = SupervisorSafety(supervisor_cfg, resolve_app_relative_path)
    startup.measure("supervisor_safety", safety.load)

    def prepare_worker_launch():
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--worker", *raw_args]
        else:
            cmd = [
                sys.executable,
                "-u",
                str(Path(__file__).resolve()),
                "--worker",
                *raw_args,
            ]

        print(
            f"[supervisor] starting worker parent_pid={os.getpid()} "
            f"cmd={cmd}",
            flush=True,
        )
        child_env = os.environ.copy()
        child_env['RNS_SLOT_SESSION_ID'] = safety.persistent_session_id
        config_snapshot.apply(child_env)
        if launch_channel is not None:
            launch_channel.apply(child_env)
        if runtime_trace_tag:
            child_env[RUNTIME_TRACE_ENV] = runtime_trace_tag

        quarantine_payload = {
            system_name: sorted(rom_names)
            for system_name, rom_names in safety.session_quarantine.items()
            if rom_names
        }
        child_env[SESSION_QUARANTINE_ENV] = json.dumps(
            quarantine_payload,
            ensure_ascii=False,
        )
        child_env[SESSION_DISABLED_SYSTEMS_ENV] = json.dumps(
            sorted(safety.session_disabled_systems),
            ensure_ascii=False,
        )

        quarantine_total = sum(
            len(names)
            for names in safety.session_quarantine.values()
        )
        if quarantine_total or safety.session_disabled_systems:
            print(
                f"[session-safety] passing state to worker: "
                f"quarantined_roms={quarantine_total} "
                f"suspended_systems={len(safety.session_disabled_systems)}",
                flush=True,
            )

        return cmd, child_env

    try:
        # Shared memory survives a worker crash because the supervisor owns
        # the mapping. The worker only updates its latest native-call position.
        if os.name == "nt":
            runtime_trace_tag = (
                f"RetroNativeSaverRuntimeTrace_{os.getpid()}"
            )
            try:
                runtime_trace_mm = mmap.mmap(
                    -1,
                    RUNTIME_TRACE_SIZE,
                    tagname=runtime_trace_tag,
                )
                runtime_trace_mm.seek(0)
                runtime_trace_mm.write(b"SUPERVISOR_READY\0")
                print(
                    "[runtime-trace] supervisor shared trace ready "
                    f"tag={runtime_trace_tag}",
                    flush=True,
                )
            except Exception as exc:
                if runtime_trace_mm is not None:
                    from process_cleanup import close_trace
                    close_trace(runtime_trace_mm)
                runtime_trace_mm = None
                runtime_trace_tag = None
                print(
                    "[runtime-trace] supervisor could not create "
                    f"shared trace: {exc}",
                    flush=True,
                )

        # Create black coverage before the first worker starts. This window
        # remains alive through normal cycle recycle and crash recovery.
        from config_snapshot import ConfigSnapshot
        config_snapshot = ConfigSnapshot(supervisor_cfg)
        from saver_controls import enabled as controls_enabled
        if controls_enabled(supervisor_cfg):
            from retroarch_launch import LaunchChannel
            launch_channel = LaunchChannel()
        with startup.span("backdrop_create"):
            backdrop = create_supervisor_backdrop(supervisor_cfg)
        from saver_controls import enabled as controls_enabled, ForwardKeys, window_for_process
        if backdrop is not None and controls_enabled(supervisor_cfg):
            backdrop.saver_controls = ForwardKeys(user32,
                lambda: window_for_process(user32, proc.pid if proc is not None and proc.poll() is None else None))

        if backdrop is not None and supervisor_cfg.get("supervisor_watchdog_enabled", True):
            try:
                from supervisor_guard import Guard
                guard = Guard(APP_DIR, _LOG_DIR)
                backdrop.supervisor_guard = guard
            except Exception as exc:
                print(f"[supervisor-guard] unavailable: {exc}", flush=True)

        # Drain the initial power-status notification before launching GPU work.
        if backdrop is not None:
            startup.point("initial_power_wait_begin")
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline and not backdrop.should_close and not backdrop.power_idle:
                backdrop.pump()
                time.sleep(0.01)
            startup.point("initial_power_wait_end")

        job = _create_worker_job_object()
        if not job:
            raise RuntimeError("Cannot start saver without a kill-on-close Job Object")

        while True:
            if backdrop is not None:
                backdrop.pump()
                if backdrop.power_idle:
                    standby_job, job = job, None
                    return wait_for_display_resume(backdrop, standby_job)
                if backdrop.should_close:
                    return 0
            if controls_enabled(supervisor_cfg) and proc is not None:
                from saver_actions import refresh_safety
                refresh_safety(safety)
            cmd, child_env = prepare_worker_launch()

            # Reset the last-location record before every worker start.
            if runtime_trace_mm is not None:
                try:
                    runtime_trace_mm.seek(0)
                    runtime_trace_mm.write(b"WORKER_STARTING\0")
                except Exception:
                    pass

            worker_assigned = False
            proc = startup.measure("worker_spawn", subprocess.Popen, cmd, env=child_env)
            startup.point("worker_spawned", target_pid=proc.pid)
            print(
                f"[supervisor] worker started pid={proc.pid}",
                flush=True,
            )
            if not _assign_worker_to_job(job, proc):
                proc.kill()
                proc.wait(timeout=5)
                raise RuntimeError("Cannot safely contain scheduler in Job Object")
            worker_assigned = True

            # Do not block in proc.wait(). Keep the backdrop's Win32 message
            # queue alive so Windows never ghosts/replaces it during long runs.
            #
            # Also watch shared-memory RUN_ENTER / START_ENTER records. If the
            # exact same native call remains active past the configured timeout,
            # the core is hung rather than crashed. Terminate the worker from
            # the supervisor so normal crash containment can continue.
            watchdog = WorkerWatchdog(
                supervisor_cfg, safety.worker_watchdog_poll_seconds,
                read_runtime_trace,
                lambda child: terminate_hung_worker(child, kernel32, WORKER_RESTART_EXIT_CODE),
            )

            while proc.poll() is None:
                if backdrop is not None:
                    backdrop.pump()
                    if backdrop.power_idle:
                        if supervisor_cfg.get("independent_slots_enabled", False):
                            return wait_for_scheduler_standby(backdrop, job, proc, runtime_trace_mm)
                        standby_job, job = job, None
                        return wait_for_display_resume(backdrop, standby_job)
                    if backdrop.should_close:
                        print(
                            f"[supervisor] backdrop exit reason={backdrop.exit_reason}; "
                            "closing screen saver",
                            flush=True,
                        )
                        # Capture the latest shared trace even for a manual exit.
                        # This is useful when the user closes a visually frozen
                        # saver before the watchdog timeout has elapsed.
                        log_runtime_trace_snapshot(
                            runtime_trace_mm,
                            proc.pid,
                            f"supervisor-{backdrop.exit_reason}",
                        )
                        # Closing the Job Object in finally kills the worker.
                        return 0

                now_watchdog = time.monotonic()
                if watchdog.check(proc, now_watchdog, runtime_trace_mm) == 1:
                    return 1

                time.sleep(0.025)

            if backdrop is not None:
                backdrop.pump()
                if backdrop.power_idle:
                    standby_job, job = job, None
                    return wait_for_display_resume(backdrop, standby_job)
                if backdrop.should_close:
                    return 0
            code = int(proc.returncode)
            unsigned_code = code & 0xFFFFFFFF
            print(
                f"[supervisor] worker pid={proc.pid} exited "
                f"code={code} hex=0x{unsigned_code:08X}",
                flush=True,
            )

            snapshot = log_runtime_trace_snapshot(
                runtime_trace_mm,
                proc.pid,
                f"exit=0x{unsigned_code:08X}",
            )
            if watchdog.watchdog_triggered and watchdog.watchdog_snapshot:
                # The supervisor captured this record before TerminateProcess.
                # Prefer it if the final mapping read is unavailable.
                if not snapshot:
                    snapshot = watchdog.watchdog_snapshot

            native_crash_codes = NATIVE_CRASH_CODES

            from runtime_policy import worker_runtime_failure
            runtime_failure = worker_runtime_failure(
                snapshot, unsigned_code, watchdog.watchdog_triggered, native_crash_codes)

            if runtime_failure:
                if controls_enabled(supervisor_cfg):
                    from saver_actions import record_failure_with_fresh_lists
                    record_failure_with_fresh_lists(safety, snapshot, watchdog.watchdog_triggered)
                else:
                    safety.record_runtime_failure(snapshot, watchdog.watchdog_triggered)

            # Repaint the persistent black layer immediately after a child
            # disappears. Normally it is already intact, but this also repairs
            # any invalidated/covered region before the replacement starts.
            if backdrop is not None and not backdrop.should_close:
                try:
                    backdrop.begin_composite()
                    backdrop.present()
                    backdrop.pump()
                except Exception as exc:
                    print(
                        f"[supervisor] backdrop repaint warning: {exc}",
                        flush=True,
                    )

            if code == WORKER_RESTART_EXIT_CODE:
                print("[supervisor] worker recycle -> next cycle", flush=True)
                continue

            # Native libretro cores can terminate the worker with a Windows
            # structured-exception status instead of returning a Python exception.
            if unsigned_code in native_crash_codes:
                print(
                    f"[supervisor] native worker crash "
                    f"0x{unsigned_code:08X}; restarting worker",
                    flush=True,
                )
                continue

            print(f"[supervisor] worker exit code={code}", flush=True)
            if code == 0 and not watchdog.watchdog_triggered and launch_channel is not None:
                launch_pick = launch_channel.read(proc.pid)
            return code
    finally:
        from process_cleanup import cleanup_supervisor
        try:
            cleanup_supervisor(kernel32, job, backdrop, guard, runtime_trace_mm,
                               config_snapshot, restore_windows_desktop,
                               unassigned=proc if not worker_assigned else None)
        finally:
            if launch_channel is not None:
                launch_channel.close()
        # Reached only when all saver cleanup succeeded. RetroArch is never
        # placed in the worker Job or run on a screen-saver desktop.
        if launch_pick is not None:
            from retroarch_launch import launch
            try:
                launch(launch_pick, supervisor_cfg, APP_DIR)
            except Exception as exc:
                print(f'[retroarch] launch failed: {exc}', flush=True)
                user32.MessageBoxW(None, f'RetroArchを起動できませんでした。\n{exc}', 'Retro Native Saver', 0x10)


if __name__ == "__main__":
    _exit_code = 1
    try:
        _exit_code = int(supervisor_main())
    except BaseException:
        print(
            "[process] unhandled Python exception",
            file=sys.stderr,
            flush=True,
        )

        # Preserve the traceback in the persistent log before forcing the
        # worker down. Normal Python shutdown is unsafe here because native
        # libretro cores may leave threads/DLL teardown paths alive and the
        # process can remain half-dead after its window has disappeared.
        import traceback as _traceback
        _traceback.print_exc(file=sys.stderr)
        if "--slot-worker" in sys.argv[1:]:
            hard_exit_process(76)
        try:
            sys.stderr.flush()
            sys.stdout.flush()
        except Exception:
            pass

        if "--worker" in sys.argv[1:]:
            print(
                "[worker] unhandled exception; force-recycling worker "
                "to avoid native shutdown hang",
                file=sys.stderr,
                flush=True,
            )
            hard_exit_process(WORKER_RESTART_EXIT_CODE)

        from core_lifecycle import has_retained_resources
        from process_cleanup import has_retained_resources as has_process_resources
        if has_retained_resources() or has_process_resources():
            hard_exit_process(76)
        raise
    finally:
        from core_lifecycle import has_retained_resources
        from process_cleanup import has_retained_resources as has_process_resources
        if has_retained_resources() or has_process_resources():
            hard_exit_process(76)
        print(
            f"=== Retro Native Saver process end pid={os.getpid()} "
            f"exit_code={_exit_code} ===",
            flush=True,
        )
    raise SystemExit(_exit_code)
