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


class WGLHardwareContext:
    """
    Hidden WGL context + libretro-compatible offscreen FBO.

    Supports both:
      - legacy/compat OpenGL contexts (Flycast)
      - OpenGL Core Profile via WGL_ARB_create_context (Dolphin/glcore)
    """















    def capture_bgra(self, width: int, height: int):
        w = max(1, min(int(width), self.width))
        h = max(1, min(int(height), self.height))

        if self.shared_context_enabled:
            # Finish the core's writes before switching to the frontend
            # context which shares the color texture.
            self.make_current()
            opengl32.glFinish()

            self.make_frontend_current()
            self.glBindFramebuffer(
                GL_READ_FRAMEBUFFER,
                self.frontend_read_fbo,
            )
            opengl32.glPixelStorei(GL_PACK_ALIGNMENT, 4)
            opengl32.glReadBuffer(GL_COLOR_ATTACHMENT0)

            buf = (ctypes.c_ubyte * (w * h * 4))()
            opengl32.glReadPixels(
                0, 0, w, h,
                GL_BGRA, GL_UNSIGNED_BYTE,
                ctypes.cast(buf, c_void_p),
            )

            # Next retro_run() must begin with the core context current.
            self.make_current()
            return bytes(buf), w, h

        # Non-shared path used by Flycast and simpler HW cores.
        self.make_current()

        prev_fbo = c_int(0)
        prev_read_buffer = c_int(0)
        opengl32.glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, byref(prev_fbo))
        opengl32.glGetIntegerv(GL_READ_BUFFER, byref(prev_read_buffer))

        self.glBindFramebuffer(GL_READ_FRAMEBUFFER, self.fbo)
        opengl32.glFinish()
        opengl32.glPixelStorei(GL_PACK_ALIGNMENT, 4)
        opengl32.glReadBuffer(GL_COLOR_ATTACHMENT0)

        buf = (ctypes.c_ubyte * (w * h * 4))()
        opengl32.glReadPixels(
            0, 0, w, h,
            GL_BGRA, GL_UNSIGNED_BYTE,
            ctypes.cast(buf, c_void_p),
        )

        self.glBindFramebuffer(
            GL_READ_FRAMEBUFFER,
            c_uint(prev_fbo.value).value,
        )
        opengl32.glReadBuffer(c_uint(prev_read_buffer.value).value)

        return bytes(buf), w, h


