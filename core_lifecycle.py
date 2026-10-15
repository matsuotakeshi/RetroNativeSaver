"""Host-side ownership of a libretro DLL and its callbacks (not core internals)."""
from ctypes import c_void_p

# A failed unload must not leave native threads holding collected Python callbacks.
# These objects live until a successful retry or process recycle.
_retained = {}


class IncompleteCleanup(RuntimeError):
    pass


def has_retained_resources():
    return bool(_retained)


def ensure_no_retained_resources():
    if _retained:
        raise IncompleteCleanup('Native resources remain; stop this process before loading another core')


def _retain_for_recycle(core, uncertain=False):
    """Retain callbacks and DLL together; uncertainty forbids further native calls.

    A plain OS/WGL release failure remains retryable. A callback/native lifecycle
    failure is sticky: closing again must not call the possibly broken DLL.
    """
    if uncertain:
        core._cleanup_uncertain = True
    core._cleanup_requires_recycle = True
    _retained[id(core)] = core


def close_core(core, kernel, callback_type):
    def retain(reason, uncertain=False):
        _retain_for_recycle(core, uncertain=uncertain)
        print(f'[shutdown] retaining core resources until process recycle: {reason}', flush=True)

    if getattr(core, '_cleanup_uncertain', False):
        retain('previous native cleanup failed')
        return
    if not core.dll and not core.hw_context:
        _retained.pop(id(core), None)
        return

    from core_callbacks import raise_pending

    def destroy_hw():
        if core.hw_context and core.hw_context_destroy_addr and core.hw_context_reset_done:
            if not core.hw_context.make_current():
                raise RuntimeError('Cannot activate HW context for context_destroy')
            callback_type(core.hw_context_destroy_addr)()
            raise_pending(core)
            core.hw_context_destroy_addr = 0
            core.hw_context_reset_done = False

    try:
        if core.dll:
            # Preserve the core-specific Dolphin before-unload ordering.
            if core.destroy_hw_before_unload:
                destroy_hw()
            if getattr(core, '_game_loaded', False):
                if core.hw_context and not core.hw_context.make_current():
                    raise RuntimeError('Cannot activate HW context for retro_unload_game')
                core.dll.retro_unload_game()
                raise_pending(core)
                core._game_loaded = False
            if not core.destroy_hw_before_unload:
                destroy_hw()
            if getattr(core, '_initialized', False):
                core.dll.retro_deinit()
                raise_pending(core)
                core._initialized = False
    except Exception as exc:
        retain(str(exc), uncertain=True)
        return

    if core.hw_context:
        try:
            if not core.hw_context.close():
                retain('WGL cleanup incomplete')
                return
            core.hw_context = None
        except Exception as exc:
            retain(f'WGL cleanup: {exc}')
            return
    if core.dll:
        try:
            if not kernel.FreeLibrary(c_void_p(core.dll._handle)):
                retain('FreeLibrary failed')
                return
            core.dll = None
        except Exception as exc:
            retain(f'FreeLibrary: {exc}')
            return
    core._keyboard_event = None
    core._game_data_buffer = None
    core.frame_bytes = None
    core._pending_hw_frame = None
    core._cleanup_requires_recycle = False
    _retained.pop(id(core), None)


def retain_uncertain(core, reason):
    _retain_for_recycle(core, uncertain=True)
    print(f'[shutdown] incomplete native initialization; retaining until recycle: {reason}', flush=True)
