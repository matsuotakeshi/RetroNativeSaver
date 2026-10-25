"""Scope frontend readback state, including client-memory versus PBO writes."""
from contextlib import contextmanager
from ctypes import byref, c_int
from wgl_safety import gl_checked

READ_FRAMEBUFFER = 0x8CA8
READ_FRAMEBUFFER_BINDING = 0x8CAA
READ_BUFFER = 0x0C02
PIXEL_PACK_BUFFER = 0x88EB
PIXEL_PACK_BUFFER_BINDING = 0x88ED
PACK_VALUES = {0x0D05: 4, 0x0D02: 0, 0x0D03: 0, 0x0D04: 0}
# PACK_ALIGNMENT, PACK_ROW_LENGTH, PACK_SKIP_ROWS, PACK_SKIP_PIXELS.


@contextmanager
def readback_state(owner, gl):
    # Core errors predate this operation. OpenGL has no way to restore its
    # error queue; drain it before checking only our own frontend operations.
    for _ in range(32):
        if not gl.glGetError():
            break
    else:
        raise RuntimeError('OpenGL error queue did not clear before readback')
    saved = {}
    for key in (*PACK_VALUES, PIXEL_PACK_BUFFER_BINDING, READ_FRAMEBUFFER_BINDING, READ_BUFFER):
        value = c_int()
        gl.glGetIntegerv(key, byref(value))
        gl_checked(gl, 'save readback state')
        saved[key] = value.value
    try:
        owner.glBindBuffer(PIXEL_PACK_BUFFER, 0)
        for key, value in PACK_VALUES.items():
            gl.glPixelStorei(key, value)
        gl_checked(gl, 'prepare client-memory readback')
        yield
    finally:
        # Attempt every independent restoration even if one binding fails.
        errors = []
        restores = [(owner.glBindFramebuffer, (READ_FRAMEBUFFER, saved[READ_FRAMEBUFFER_BINDING])),
                    (gl.glReadBuffer, (saved[READ_BUFFER],)),
                    (owner.glBindBuffer, (PIXEL_PACK_BUFFER, saved[PIXEL_PACK_BUFFER_BINDING]))]
        restores.extend((gl.glPixelStorei, (key, saved[key])) for key in PACK_VALUES)
        for function, args in restores:
            try:
                function(*args)
                gl_checked(gl, 'restore readback state')
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError('Could not restore OpenGL readback state') from errors[0]
