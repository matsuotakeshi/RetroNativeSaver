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
        if self.core_hglrc:
            return

        self._create_window_and_pixel_format()

        # Bootstrap legacy context is required to resolve
        # wglCreateContextAttribsARB itself.
        bootstrap = opengl32.wglCreateContext(self.hdc)
        if not bootstrap:
            raise RuntimeError("wglCreateContext() bootstrap failed")
        if not opengl32.wglMakeCurrent(self.hdc, bootstrap):
            opengl32.wglDeleteContext(bootstrap)
            raise RuntimeError("wglMakeCurrent() bootstrap failed")

        if self.context_type == RETRO_HW_CONTEXT_OPENGL_CORE:
            if not self._load_wgl_create_context_attribs():
                opengl32.wglMakeCurrent(None, None)
                opengl32.wglDeleteContext(bootstrap)
                raise RuntimeError(
                    "WGL_ARB_create_context not available"
                )

            modern = self._create_attrib_context()
            opengl32.wglMakeCurrent(None, None)
            opengl32.wglDeleteContext(bootstrap)

            self.core_hglrc = modern
            if not self.make_current():
                raise RuntimeError("Failed to activate OpenGL Core context")
        else:
            self.core_hglrc = bootstrap

        self._init_gl_functions()
        self._create_offscreen_fbo()

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

    def make_current(self):
        if not self.hdc or not self.core_hglrc:
            return False
        return bool(opengl32.wglMakeCurrent(self.hdc, self.core_hglrc))






    def _create_offscreen_fbo(self):
        self.make_current()

        tex = c_uint(0)
        self.glGenTextures(1, byref(tex))
        self.color_tex = int(tex.value)
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

        rb = c_uint(0)
        self.glGenRenderbuffers(1, byref(rb))
        self.depth_stencil_rb = int(rb.value)
        self.glBindRenderbuffer(GL_RENDERBUFFER, self.depth_stencil_rb)
        self.glRenderbufferStorage(
            GL_RENDERBUFFER,
            GL_DEPTH24_STENCIL8,
            self.width,
            self.height,
        )

        fbo = c_uint(0)
        self.glGenFramebuffers(1, byref(fbo))
        self.fbo = int(fbo.value)
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








