"""Checked GDI calls and best-effort cleanup with retained failed handles."""
import ctypes

class GDIError(OSError):
    pass


def checked(name, function, *args, invalid=(None, 0)):
    result = function(*args)
    if result in invalid:
        # Many GDI APIs do not set last-error; do not report a stale error code.
        raise GDIError(f'{name} failed (result={result!r})')
    return result


def selected(function, dc, obj):
    return checked('SelectObject', function, dc, obj,
                   invalid=(None, 0, -1, ctypes.c_void_p(-1).value))


def release(name, function, *args):
    try:
        checked(name, function, *args)
        return True
    except Exception as exc:
        print(f'[gdi-cleanup] {name}: {exc}; retaining unresolved handles', flush=True)
        return False


def dispose_bitmap(owner, api, dc_name, bitmap_name, old_name):
    """Continue after each failure. Clear a reference only after success."""
    dc, bitmap, old = (getattr(owner, name) for name in (dc_name, bitmap_name, old_name))
    restored = not dc or not old
    if dc and old:
        try:
            selected(api.SelectObject, dc, old)
            setattr(owner, old_name, None)
            restored = True
        except Exception as exc:
            print(f'[gdi-cleanup] bitmap deselection: {exc}', flush=True)
    if bitmap and restored and release('DeleteObject', api.DeleteObject, bitmap):
        setattr(owner, bitmap_name, None)
        bitmap = None
    if dc and release('DeleteDC', api.DeleteDC, dc):
        setattr(owner, dc_name, None)
        setattr(owner, old_name, None)
        dc = None
    # A failed deselection no longer blocks deletion after its DC is gone.
    if bitmap and not dc and release('DeleteObject', api.DeleteObject, bitmap):
        setattr(owner, bitmap_name, None)
    if not dc:
        setattr(owner, old_name, None)
    return not getattr(owner, dc_name) and not getattr(owner, bitmap_name)


def dispose_fonts(owner, api):
    for name in ('overlay_system_font', 'overlay_game_font'):
        font = getattr(owner, name)
        if font and release('DeleteObject', api.DeleteObject, font):
            setattr(owner, name, None)


def release_dc(api, hwnd, dc, owner=None):
    if dc and not release('ReleaseDC', api.ReleaseDC, hwnd, dc):
        if not release('ReleaseDC', api.ReleaseDC, hwnd, dc):
            if owner is not None:
                pending = getattr(owner, '_pending_window_dcs', [])
                if (hwnd, dc) not in pending:
                    pending.append((hwnd, dc))
                owner._pending_window_dcs = pending
            return False
    return True


def release_pending_dcs(owner, api):
    pending = getattr(owner, '_pending_window_dcs', [])
    owner._pending_window_dcs = []
    for hwnd, dc in pending:
        release_dc(api, hwnd, dc, owner)


def require_released_window_dcs(owner, api):
    release_pending_dcs(owner, api)
    if getattr(owner, '_pending_window_dcs', []):
        raise GDIError('Previous window DC could not be released; refusing another allocation')
