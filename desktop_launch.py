"""Start an interactive application on the normal desktop, outside saver Jobs."""
import ctypes
from ctypes import wintypes as wt
import subprocess
import threading


class StartupInfo(ctypes.Structure):
    _fields_ = [('cb',wt.DWORD),('lpReserved',wt.LPWSTR),('lpDesktop',wt.LPWSTR),('lpTitle',wt.LPWSTR),
                ('dwX',wt.DWORD),('dwY',wt.DWORD),('dwXSize',wt.DWORD),('dwYSize',wt.DWORD),
                ('dwXCountChars',wt.DWORD),('dwYCountChars',wt.DWORD),('dwFillAttribute',wt.DWORD),
                ('dwFlags',wt.DWORD),('wShowWindow',wt.WORD),('cbReserved2',wt.WORD),
                ('lpReserved2',ctypes.c_void_p),('hStdInput',wt.HANDLE),('hStdOutput',wt.HANDLE),('hStdError',wt.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('hProcess',wt.HANDLE),('hThread',wt.HANDLE),('dwProcessId',wt.DWORD),('dwThreadId',wt.DWORD)]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [('StartupInfo', StartupInfo), ('lpAttributeList', ctypes.c_void_p)]


PROCESS_CREATE_PROCESS = 0x0080
PROC_THREAD_ATTRIBUTE_PARENT_PROCESS = 0x00020000
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
SPI_GETSCREENSAVESECURE = 0x0076


def _error(operation):
    code = ctypes.get_last_error()
    return OSError(code, f'{operation}: {ctypes.FormatError(code).strip()}', None, code)


def _shell_parent(kernel, user, hwnd):
    pid = wt.DWORD()
    if not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        raise _error('GetWindowThreadProcessId(desktop shell)')
    handle = kernel.OpenProcess(PROCESS_CREATE_PROCESS, False, pid.value)
    if not handle:
        raise _error('OpenProcess(desktop shell)')
    return handle, pid.value


def _object_name(user, handle):
    name = ctypes.create_unicode_buffer(256)
    required = wt.DWORD()
    if not handle or not user.GetUserObjectInformationW(
            handle, UOI_NAME, name, ctypes.sizeof(name), ctypes.byref(required)):
        raise _error('GetUserObjectInformationW(desktop/station name)')
    return name.value


def _check_input_desktop(user):
    """Read-only guard: never switch desktops or dismiss Windows authentication."""
    active = user.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not active:
        raise _error('OpenInputDesktop(RetroArch launch)')
    try:
        name = _object_name(user, active)
        if name.casefold() == 'default':
            return name
        if name.casefold() in ('screen-saver', 'screensaver'):
            secure = wt.BOOL(True)
            if not user.SystemParametersInfoW(SPI_GETSCREENSAVESECURE, 0, ctypes.byref(secure), 0):
                raise _error('SystemParametersInfoW(screen saver security)')
            if not secure.value:
                return name
        raise RuntimeError(f'RetroArch launch requires an unlocked desktop (input={name}); unlock Windows and retry')
    finally:
        if not user.CloseDesktop(active):
            print('[retroarch] input desktop handle close warning; host exit will release it', flush=True)


def _normal_desktop_parent(kernel, user):
    """Query Default on a fresh thread; the saver thread can own windows/hooks.

    OpenDesktop is relative to this process's window station. Never search for
    an arbitrary explorer.exe PID, change stations, or fall back to saver Jobs.
    The opened desktop is closed only after the querying thread has exited.
    """
    signatures = {
        'GetProcessWindowStation': ([], wt.HANDLE),
        'GetThreadDesktop': ([wt.DWORD], wt.HANDLE),
        'GetUserObjectInformationW': ([wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                       ctypes.POINTER(wt.DWORD)], wt.BOOL),
        'OpenInputDesktop': ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
        'OpenDesktopW': ([wt.LPCWSTR, wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
        'SetThreadDesktop': ([wt.HANDLE], wt.BOOL),
        'CloseDesktop': ([wt.HANDLE], wt.BOOL),
        'SystemParametersInfoW': ([wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT], wt.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(user, name).argtypes = args
        getattr(user, name).restype = result
    kernel.GetCurrentThreadId.argtypes = []
    kernel.GetCurrentThreadId.restype = wt.DWORD
    station = _object_name(user, user.GetProcessWindowStation())
    if station.casefold() != 'winsta0':
        raise RuntimeError(f'RetroArch launch requires the interactive window station (station={station})')
    source = _object_name(user, user.GetThreadDesktop(kernel.GetCurrentThreadId()))
    active = _check_input_desktop(user)
    print(f'[retroarch] shell unavailable on desktop={source}; input={active}; querying Default', flush=True)
    target = user.OpenDesktopW('Default', 0, False, DESKTOP_READOBJECTS)
    if not target:
        raise _error('OpenDesktopW(Default)')
    result, errors = [], []

    def query():
        try:
            if not user.SetThreadDesktop(target):
                raise _error('SetThreadDesktop(Default lookup)')
            hwnd = user.GetShellWindow()
            if not hwnd:
                raise RuntimeError('RetroArch launch requires the normal desktop shell; unlock Windows and retry')
            # Check again after changing this lookup thread's desktop in case
            # the input desktop changed while opening Default.
            _check_input_desktop(user)
            result.append(_shell_parent(kernel, user, hwnd))
        except BaseException as exc:
            errors.append(exc)

    thread = None
    try:
        thread = threading.Thread(target=query, name='RetroArchDesktopLookup')
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        return result.pop()
    finally:
        if thread is not None and thread.is_alive():
            thread.join()
        # If the caller was interrupted after the lookup, ownership never
        # reached start_process. Release the otherwise orphaned parent handle.
        if result and not kernel.CloseHandle(result[0][0]):
            print('[retroarch] parent handle close warning; host exit will release it', flush=True)
        if not user.CloseDesktop(target):
            print('[retroarch] lookup desktop handle close warning; host exit will release it', flush=True)


def _desktop_parent(kernel):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetShellWindow.argtypes = [];user.GetShellWindow.restype = wt.HWND
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user.GetWindowThreadProcessId.restype = wt.DWORD
    hwnd = user.GetShellWindow()
    if hwnd:
        return _shell_parent(kernel, user, hwnd)
    return _normal_desktop_parent(kernel, user)


def start_process(args, cwd):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateProcessW.argtypes = [wt.LPCWSTR,wt.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,wt.BOOL,
                                    wt.DWORD,ctypes.c_void_p,wt.LPCWSTR,ctypes.POINTER(StartupInfo),ctypes.POINTER(ProcessInfo)]
    kernel.CreateProcessW.restype = wt.BOOL
    kernel.CloseHandle.argtypes = [wt.HANDLE];kernel.CloseHandle.restype = wt.BOOL
    kernel.GetDllDirectoryW.argtypes = [wt.DWORD,wt.LPWSTR];kernel.GetDllDirectoryW.restype = wt.DWORD
    kernel.SetDllDirectoryW.argtypes = [wt.LPCWSTR];kernel.SetDllDirectoryW.restype = wt.BOOL
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD];kernel.OpenProcess.restype = wt.HANDLE
    kernel.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.InitializeProcThreadAttributeList.restype = wt.BOOL
    kernel.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                               ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel.UpdateProcThreadAttribute.restype = wt.BOOL
    kernel.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel.DeleteProcThreadAttributeList.restype = None
    info = ProcessInfo()
    parent = None
    attributes = None
    attributes_ready = False
    dll_changed = False
    try:
        parent, parent_pid = _desktop_parent(kernel)
        size = ctypes.c_size_t()
        # Sizing call must fail with ERROR_INSUFFICIENT_BUFFER and return a size.
        if (kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
                or ctypes.get_last_error() != 122 or not size.value):
            raise _error('InitializeProcThreadAttributeList(size)')
        attributes = ctypes.create_string_buffer(size.value)
        if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            raise _error('InitializeProcThreadAttributeList')
        attributes_ready = True
        parent_value = wt.HANDLE(parent)
        if not kernel.UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_PARENT_PROCESS,
                                                ctypes.byref(parent_value), ctypes.sizeof(parent_value), None, None):
            raise _error('UpdateProcThreadAttribute(desktop parent)')
        previous = ctypes.create_unicode_buffer(32768)
        length = kernel.GetDllDirectoryW(len(previous), previous)
        if length >= len(previous):
            raise OSError('DLL search path is too long')
        # PyInstaller's private DLL directory must not shadow RetroArch's DLLs.
        if not kernel.SetDllDirectoryW(None):
            raise _error('SetDllDirectoryW(clear)')
        dll_changed = True
        startup = StartupInfoEx(StartupInfo=StartupInfo(cb=ctypes.sizeof(StartupInfoEx), lpDesktop='winsta0\\default'),
                                lpAttributeList=ctypes.cast(attributes, ctypes.c_void_p))
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        # The documented parent attribute inherits the shell's Job/token instead
        # of the saver's. No BREAKAWAY request and no retry as a saver descendant.
        if not kernel.CreateProcessW(args[0], command, None, None, False,
                                     EXTENDED_STARTUPINFO_PRESENT | CREATE_NEW_PROCESS_GROUP, None, str(cwd),
                                     ctypes.byref(startup.StartupInfo), ctypes.byref(info)):
            raise _error('CreateProcessW(desktop parent)')
        print(f'[retroarch] desktop parent pid={parent_pid}; created pid={info.dwProcessId}', flush=True)
        return int(info.dwProcessId)
    finally:
        if attributes_ready:
            kernel.DeleteProcThreadAttributeList(attributes)
        for handle in (info.hThread, info.hProcess, parent):
            if handle and not kernel.CloseHandle(handle):
                print('[retroarch] process handle close warning; host exit will release it', flush=True)
        if dll_changed and not kernel.SetDllDirectoryW(previous.value if length else None):
            print('[retroarch] DLL search path restore warning', flush=True)
