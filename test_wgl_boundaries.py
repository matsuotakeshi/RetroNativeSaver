import ast
import copy
import ctypes
from pathlib import Path
import random
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_wgl_v096.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
NAMES={'_read_bgra_buffer','_capture_shared_bgra','_capture_single_bgra'}
def context(source):return next(n for n in ast.parse(source).body if getattr(n,'name','')=='WGLHardwareContext')

def code(source):
    c=context(source);c.body=[n for n in c.body if getattr(n,'name','') in NAMES|{'capture_bgra'}]
    return compile(ast.Module(body=[c],type_ignores=[]),'<capture>','exec')
CODES=(code(OLD),code(NEW))

class CaptureModel:
    def __init__(self, compiled=CODES[1], shared=False, read_error=False, setup_error=False):
        from wgl_readback import PACK_VALUES, PIXEL_PACK_BUFFER_BINDING, READ_FRAMEBUFFER_BINDING, READ_BUFFER
        self.state = {0x0D05:8, 0x0D02:37, 0x0D03:9, 0x0D04:11,
                      PIXEL_PACK_BUFFER_BINDING:99, READ_FRAMEBUFFER_BINDING:77, READ_BUFFER:0x405}
        self.initial = self.state.copy()
        self.events = []; self.error = 0; self.read_error = read_error; self.setup_error = setup_error
        ns=dict(ctypes=ctypes,c_int=ctypes.c_int,c_uint=ctypes.c_uint,c_void_p=ctypes.c_void_p,byref=ctypes.byref,
                opengl32=self,GL_READ_FRAMEBUFFER=0x8CA8,GL_PACK_ALIGNMENT=0x0D05,GL_COLOR_ATTACHMENT0=0x8CE0,
                GL_BGRA=0x80E1,GL_UNSIGNED_BYTE=0x1401,GL_READ_FRAMEBUFFER_BINDING=READ_FRAMEBUFFER_BINDING,GL_READ_BUFFER=READ_BUFFER)
        exec(compiled,ns);self.owner=ns['WGLHardwareContext']()
        self.owner.width=12;self.owner.height=9;self.owner.shared_context_enabled=shared
        self.owner.fbo=7;self.owner.frontend_read_fbo=8
        self.owner.make_current=lambda:self.events.append('core') or True
        self.owner.make_frontend_current=lambda:self.events.append('frontend') or True
        self.owner.glBindFramebuffer=lambda target,value:self.state.update({READ_FRAMEBUFFER_BINDING:ctypes.c_uint(value).value})
        self.owner.glBindBuffer=lambda target,value:self.state.update({PIXEL_PACK_BUFFER_BINDING:value})
        self.check_pack=compiled is CODES[1]

    def glGetError(self):
        error,self.error=self.error,0
        return error
    def glGetIntegerv(self,key,ptr):ptr._obj.value=self.state[key]
    def glFinish(self):pass
    def glPixelStorei(self,key,value):
        self.state[key]=value
        if self.setup_error and key==0x0D02 and value==0:self.error=0x502
    def glReadBuffer(self,value):self.state[0x0C02]=value
    def glReadPixels(self,x,y,w,h,fmt,kind,ptr):
        self.events.append('read')
        if self.check_pack:
            from wgl_readback import PACK_VALUES, PIXEL_PACK_BUFFER_BINDING
            assert all(self.state[k]==v for k,v in PACK_VALUES.items()), self.state
            assert self.state[PIXEL_PACK_BUFFER_BINDING]==0
        if self.read_error:
            self.error=0x502
            return
        data=bytes(i%251 for i in range(w*h*4));ctypes.memmove(ptr,data,len(data))


class WglBoundaryTests(unittest.TestCase):
    def test_legacy_dimensions_and_pixels_remain_identical(self):
        rng=random.Random(97)
        for shared in (False,True):
            for _ in range(120):
                width,height=rng.randint(-5,25),rng.randint(-5,20)
                old,new=(CaptureModel(code,shared) for code in CODES)
                self.assertEqual(old.owner.capture_bgra(width,height),new.owner.capture_bgra(width,height))
                self.assertEqual(new.state,new.initial)
                self.assertEqual(new.events[-1], 'core' if shared else 'read')

    def test_pack_offsets_stride_and_pbo_restored_on_read_error(self):
        for shared in (False,True):
            model=CaptureModel(shared=shared,read_error=True)
            with self.assertRaisesRegex(RuntimeError,'glReadPixels'):
                model.owner.capture_bgra(2,2)
            self.assertEqual(model.state,model.initial)
            if shared:self.assertEqual(model.events[-1],'core')

    def test_setup_failure_never_reads_into_client_memory(self):
        model=CaptureModel(setup_error=True)
        with self.assertRaisesRegex(RuntimeError,'prepare client-memory'):
            model.owner.capture_bgra(2,2)
        self.assertNotIn('read',model.events)
        self.assertEqual(model.state,model.initial)

    def test_core_errors_do_not_get_misreported_as_readback_failures(self):
        model=CaptureModel();model.error=0x500
        self.assertEqual(len(model.owner.capture_bgra(2,2)[0]),16)
        self.assertEqual(model.state,model.initial)

    def test_invalid_dimensions_before_gl(self):
        for shared in (False,True):
            for width,height in (('bad',2),(2,None),(float('nan'),1),(1,float('inf'))):
                model=CaptureModel(shared=shared)
                with self.assertRaises((ValueError,TypeError,OverflowError)):
                    model.owner.capture_bgra(width,height)
                self.assertEqual(model.events,[])


if __name__=='__main__':unittest.main()
