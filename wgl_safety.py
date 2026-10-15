"""Small checks for frontend-owned WGL/GL resources."""
from ctypes import byref, c_uint


def checked(operation, result):
    if not result:
        raise RuntimeError(f'{operation} failed')
    return result


def gl_checked(gl, operation):
    error = int(gl.glGetError())
    if error:
        raise RuntimeError(f'{operation}: OpenGL error 0x{error:04X}')


def attempt(operation, call, *args):
    try:
        checked(operation, call(*args))
        return True
    except Exception as exc:
        print(f'[wgl-cleanup] {operation}: {exc}', flush=True)
        return False


def close_resources(owner, gl, user):
    """Retain failed handles and their DC/window dependencies for a later close."""
    def delete_objects(fields):
        # Only inspect GL errors while disposing resources in our own context.
        for _ in range(32):
            if not gl.glGetError():
                break
        else:
            print('[wgl-cleanup] persistent GL errors; deferring object deletion', flush=True)
            return
        for field, function in fields:
            value = getattr(owner, field, 0)
            if not value:
                continue
            try:
                getattr(owner, function)(1, byref(c_uint(value)))
                gl_checked(gl, function)
                setattr(owner, field, 0)
            except Exception as exc:
                print(f'[wgl-cleanup] {function}: {exc}', flush=True)

    def context(field, objects):
        handle = getattr(owner, field, None)
        if not handle:
            return
        if objects and attempt('wglMakeCurrent', gl.wglMakeCurrent, owner.hdc, handle):
            try:
                delete_objects(objects)
            except Exception as exc:
                print(f'[wgl-cleanup] GL cleanup: {exc}', flush=True)
        # DeleteContext also detaches a context current on this thread. Even if
        # explicit detach fails, try deletion; never clear a failed handle.
        attempt('wglMakeCurrent(detach)', gl.wglMakeCurrent, None, None)
        if attempt('wglDeleteContext', gl.wglDeleteContext, handle):
            setattr(owner, field, None)
            for name, _ in objects:
                setattr(owner, name, 0)

    context('frontend_hglrc', [('frontend_read_fbo', 'glDeleteFramebuffers')])
    # Keep the core context while a shared frontend survives: shared textures
    # otherwise have no tracked context through which to retry deletion.
    if not getattr(owner, 'frontend_hglrc', None):
        context('core_hglrc', [('fbo', 'glDeleteFramebuffers'),
                             ('depth_stencil_rb', 'glDeleteRenderbuffers'),
                             ('color_tex', 'glDeleteTextures')])
    context('_bootstrap_hglrc', [])
    live = any(getattr(owner, name, None) for name in
               ('frontend_hglrc', 'core_hglrc', '_bootstrap_hglrc'))
    if not getattr(owner, 'frontend_hglrc', None):
        owner.shared_context_enabled = False
    if not live:
        if owner.hdc and attempt('ReleaseDC', user.ReleaseDC, owner.hwnd, owner.hdc):
            owner.hdc = None
        if not owner.hdc and owner.hwnd and attempt('DestroyWindow', user.DestroyWindow, owner.hwnd):
            owner.hwnd = None
    owner._ready = False
    return not live and not owner.hdc and not owner.hwnd
