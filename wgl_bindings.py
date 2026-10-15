"""OpenGL function signatures; the context retains function ownership."""
from ctypes import POINTER, c_int, c_uint, c_void_p


def bind_gl_functions(self):
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

