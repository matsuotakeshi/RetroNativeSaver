"""Resource model tests: no window, driver or emulator is started."""
import ctypes as C
from types import SimpleNamespace
import unittest
import libretro_abi as abi
from test_wgl_creation import CODES


class Model:
    def __init__(self, fail=None):
        self.fail = fail
        self.events = []
        self.contexts = set()
        self.objects = set()
        self.current = None
        self.next = 100
        self.error = 0
        self.ns = dict(vars(C), ctypes=C, opengl32=self, user32=self,
                       decode_cstr=lambda text: text.decode())
        self.ns.update(vars(abi))
        exec(CODES[1], self.ns)
        self.owner = self.ns['WGLHardwareContext']()
        self.owner._create_window_and_pixel_format = self.window
        self.owner._init_gl_functions = self.functions

    def event(self, name):
        self.events.append(name)
        return name == self.fail

    def window(self):
        self.owner.hwnd = 10
        self.owner.hdc = 11
        if self.event('pixel_format'):
            raise OSError('pixel format failure')

    def functions(self):
        if self.event('load_gl'):
            raise OSError('load GL failure')
        for suffix in ('Textures', 'Renderbuffers', 'Framebuffers'):
            setattr(self.owner, 'glGen' + suffix, self.generator(suffix))
            setattr(self.owner, 'glDelete' + suffix, self.deleter(suffix))
        for name in ('glBindTexture', 'glTexParameteri', 'glTexImage2D', 'glBindRenderbuffer',
                     'glRenderbufferStorage', 'glBindFramebuffer', 'glFramebufferTexture2D',
                     'glFramebufferRenderbuffer'):
            setattr(self.owner, name, lambda *args: None)
        self.owner.glCheckFramebufferStatus = lambda target: 0 if self.event('fbo_status') else self.ns['GL_FRAMEBUFFER_COMPLETE']

    def generator(self, name):
        def call(count, pointer):
            if self.event('gen_' + name):
                return
            self.next += 1
            pointer._obj.value = self.next
            self.objects.add((self.current, self.next))
        return call

    def deleter(self, name):
        def call(count, pointer):
            if self.event('delete_' + name):
                self.error = 0x502
                return
            self.objects.discard((self.current, pointer._obj.value))
        return call

    def wglCreateContext(self, dc):
        if self.event('context_create'):
            return 0
        self.next += 1
        self.contexts.add(self.next)
        return self.next

    def wglMakeCurrent(self, dc, context):
        if self.event('activate' if context else 'detach'):
            self.current = None
            return False
        self.current = context
        return True

    def wglDeleteContext(self, context):
        if self.event('context_delete'):
            return False
        self.contexts.remove(context)
        self.objects = {item for item in self.objects if item[0] != context}
        if self.current == context:
            self.current = None
        return True

    def wglShareLists(self, core, frontend):
        return not self.event('share')

    def glGetError(self):
        result, self.error = self.error, 0
        return result

    def glGetString(self, name):
        return b'model'

    def ReleaseDC(self, window, dc):
        return not self.event('release_dc')

    def DestroyWindow(self, window):
        return not self.event('destroy_window')


class WglSafetyTests(unittest.TestCase):
    def empty(self, model):
        self.assertFalse(model.contexts)
        self.assertFalse(model.objects)
        for field in ('hwnd', 'hdc', 'core_hglrc', 'frontend_hglrc', '_bootstrap_hglrc'):
            self.assertFalse(getattr(model.owner, field), field)

    def test_success_repeated_create_and_close(self):
        model = Model(); model.owner.create()
        count = len(model.events); model.owner.create()
        self.assertEqual(len(model.events), count)
        self.assertTrue(model.owner.close()); self.assertTrue(model.owner.close())
        self.empty(model)

    def test_creation_failure_rolls_back_every_acquired_stage(self):
        for failure in ('pixel_format', 'context_create', 'activate', 'load_gl',
                        'gen_Textures', 'gen_Renderbuffers', 'gen_Framebuffers', 'fbo_status'):
            with self.subTest(failure=failure):
                model = Model(failure)
                with self.assertRaises((RuntimeError, OSError)):
                    model.owner.create()
                self.empty(model)

    def test_modern_creation_failure_keeps_bootstrap_owned(self):
        model = Model()
        model.owner.context_type = abi.RETRO_HW_CONTEXT_OPENGL_CORE
        model.owner._load_wgl_create_context_attribs = lambda: True
        def fail(): raise RuntimeError('attribute creation failed')
        model.owner._create_attrib_context = fail
        with self.assertRaisesRegex(RuntimeError, 'attribute creation'):
            model.owner.create()
        self.empty(model)

    def test_gl_delete_failure_does_not_skip_other_objects(self):
        model = Model(); model.owner.create(); model.fail = 'delete_Framebuffers'
        self.assertTrue(model.owner.close())
        self.assertIn('delete_Renderbuffers', model.events)
        self.assertIn('delete_Textures', model.events)
        self.empty(model)

    def test_failed_context_delete_retains_dependencies_and_retries(self):
        model = Model(); model.owner.create(); model.fail = 'context_delete'
        self.assertFalse(model.owner.close())
        self.assertTrue(model.owner.core_hglrc)
        self.assertNotIn('release_dc', model.events)
        self.assertNotIn('destroy_window', model.events)
        model.fail = None
        self.assertTrue(model.owner.close()); self.empty(model)

    def test_failed_dc_and_window_release_retain_only_live_handles(self):
        for failure in ('release_dc', 'destroy_window'):
            model = Model(); model.owner.create(); model.fail = failure
            self.assertFalse(model.owner.close())
            self.assertFalse(model.owner.core_hglrc)
            self.assertTrue(model.owner.hwnd)
            self.assertEqual(bool(model.owner.hdc), failure == 'release_dc')
            model.fail = None
            self.assertTrue(model.owner.close()); self.empty(model)

    def test_failed_activation_does_not_delete_in_wrong_context(self):
        model = Model(); model.owner.create(); model.events.clear(); model.fail = 'activate'
        self.assertTrue(model.owner.close())
        self.assertFalse(any(event.startswith('delete_') for event in model.events))
        self.empty(model)

    def test_shared_creation_failure_rolls_back_both_contexts(self):
        for failure in ('share', 'activate', 'gen_Framebuffers', 'fbo_status'):
            model = Model(); model.owner.create(); model.fail = failure
            with self.assertRaises(RuntimeError): model.owner.enable_shared_context()
            self.empty(model)

    def test_shared_delete_failure_keeps_core_and_retries(self):
        model = Model(); model.owner.create(); model.owner.enable_shared_context()
        model.fail = 'context_delete'
        self.assertFalse(model.owner.close())
        self.assertTrue(model.owner.frontend_hglrc)
        self.assertTrue(model.owner.core_hglrc)
        model.fail = None
        self.assertTrue(model.owner.close()); self.empty(model)

    def test_shared_readback_exception_restores_core_context(self):
        model = Model(); model.owner.create(); model.owner.enable_shared_context()
        model.glFinish = lambda: None
        model.glPixelStorei = lambda *args: None
        model.glReadBuffer = lambda *args: None
        def fail(*args): raise RuntimeError('read failed')
        model.owner._read_bgra_buffer = fail
        with self.assertRaisesRegex(RuntimeError, 'read failed'):
            model.owner.capture_bgra(1, 1)
        self.assertEqual(model.current, model.owner.core_hglrc)
        model.owner.close(); self.empty(model)

    def test_single_readback_exception_restores_both_bindings(self):
        model = Model(); model.owner.create()
        restored = []
        model.glGetIntegerv = lambda key, pointer: setattr(pointer._obj, 'value', 12)
        model.glFinish = lambda: None
        model.glPixelStorei = lambda *args: None
        model.glReadBuffer = lambda value: restored.append(('buffer', value))
        model.owner.glBindFramebuffer = lambda target, value: restored.append(('fbo', value))
        def fail(*args): raise RuntimeError('read failed')
        model.owner._read_bgra_buffer = fail
        with self.assertRaisesRegex(RuntimeError, 'read failed'):
            model.owner.capture_bgra(1, 1)
        self.assertEqual(restored[-2:], [('fbo', 12), ('buffer', 12)])
        model.owner.close(); self.empty(model)

    def test_allocation_gl_error_rolls_back(self):
        model = Model()
        old = model.functions
        def functions():
            old()
            model.owner.glTexImage2D = lambda *args: setattr(model, 'error', 0x505)
        model.owner._init_gl_functions = functions
        with self.assertRaisesRegex(RuntimeError, 'OpenGL error'):
            model.owner.create()
        self.empty(model)


if __name__ == '__main__': unittest.main()
