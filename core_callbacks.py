"""Do not let Python exceptions escape through a ctypes callback into native code."""
from functools import wraps


class CoreCallbackError(RuntimeError):
    pass


def protect(owner, name, fallback=None):
    def decorate(function):
        @wraps(function)
        def guarded(*args):
            if getattr(owner, '_callback_error', None) is not None:
                return fallback
            try:
                return function(*args)
            except BaseException as exc:
                if getattr(owner, '_callback_error', None) is None:
                    # Store text only, not a traceback retaining arbitrary frames.
                    try:
                        detail = str(exc)
                    except BaseException:
                        detail = '<unprintable exception>'
                    owner._callback_error = f'{name}: {type(exc).__name__}: {detail}'
                    try:
                        from core_lifecycle import retain_uncertain
                        retain_uncertain(owner, owner._callback_error)
                    except BaseException:
                        # Failed logging must never turn a safe callback result
                        # back into an exception crossing the native boundary.
                        pass
                return fallback
        return guarded
    return decorate


def raise_pending(owner):
    error = getattr(owner, '_callback_error', None)
    if error:
        raise CoreCallbackError(error)
