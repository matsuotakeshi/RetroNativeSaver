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









    def enable_shared_context(self):
        if self.shared_context_enabled:
            return True
        if not self.hdc or not self.core_hglrc:
            return False

        if self.context_type == RETRO_HW_CONTEXT_OPENGL_CORE:
            # Core-profile shared contexts should be created with the same
            # WGL_ARB_create_context attributes/profile.
            frontend = self._create_attrib_context(
                share_context=self.core_hglrc
            )
        else:
            frontend = opengl32.wglCreateContext(self.hdc)
            if not frontend:
                raise RuntimeError(
                    "wglCreateContext() failed for shared frontend context"
                )
            if not opengl32.wglShareLists(self.core_hglrc, frontend):
                try:
                    opengl32.wglDeleteContext(frontend)
                except Exception:
                    pass
                raise RuntimeError("wglShareLists() failed")

        self.frontend_hglrc = frontend
        self.shared_context_enabled = True

        self.make_frontend_current()

        fbo = c_uint(0)
        self.glGenFramebuffers(1, byref(fbo))
        self.frontend_read_fbo = int(fbo.value)

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

        self.make_current()
        print(
            f"[hw] shared WGL context enabled "
            f"coreFBO={self.fbo} readFBO={self.frontend_read_fbo}"
        )
        return True



    def _init_gl_functions(self):
        self.glGenFramebuffers = self._load_gl(
            b"glGenFramebuffers", None, c_int, POINTER(c_uint)
        )
        self.glBindFramebuffer = self._load_gl(
            b"glBindFramebuffer", None, c_uint, c_uint
        )
        self.glFramebufferTexture2D = self._load_gl(
            b"glFramebufferTexture2D",
            None, c_uint, c_uint, c_uint, c_uint, c_int
        )
        self.glCheckFramebufferStatus = self._load_gl(
            b"glCheckFramebufferStatus", c_uint, c_uint
        )
        self.glDeleteFramebuffers = self._load_gl(
            b"glDeleteFramebuffers", None, c_int, POINTER(c_uint)
        )

        self.glGenTextures = self._load_gl(
            b"glGenTextures", None, c_int, POINTER(c_uint)
        )
        self.glBindTexture = self._load_gl(
            b"glBindTexture", None, c_uint, c_uint
        )
        self.glTexImage2D = self._load_gl(
            b"glTexImage2D",
            None,
            c_uint, c_int, c_int, c_int, c_int, c_int,
            c_uint, c_uint, c_void_p,
        )
        self.glTexParameteri = self._load_gl(
            b"glTexParameteri", None, c_uint, c_uint, c_int
        )
        self.glDeleteTextures = self._load_gl(
            b"glDeleteTextures", None, c_int, POINTER(c_uint)
        )

        self.glGenRenderbuffers = self._load_gl(
            b"glGenRenderbuffers", None, c_int, POINTER(c_uint)
        )
        self.glBindRenderbuffer = self._load_gl(
            b"glBindRenderbuffer", None, c_uint, c_uint
        )
        self.glRenderbufferStorage = self._load_gl(
            b"glRenderbufferStorage", None, c_uint, c_uint, c_int, c_int
        )
        self.glFramebufferRenderbuffer = self._load_gl(
            b"glFramebufferRenderbuffer",
            None, c_uint, c_uint, c_uint, c_uint
        )
        self.glDeleteRenderbuffers = self._load_gl(
            b"glDeleteRenderbuffers", None, c_int, POINTER(c_uint)
        )















