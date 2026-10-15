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

class WglBoundaryTests(unittest.TestCase):

    def compare(self,width,height,shared=False,fail_at=None,previous=(-1,-2)):
        results=[]
        for compiled in CODES:
            events=[]
            def event(name,*args):
                events.append((name,*args))
                if len(events)==fail_at:raise OSError('injected failure')
            class GL:
                def glFinish(self):event('finish')
                def glPixelStorei(self,*args):event('pixel_store',*args)
                def glReadBuffer(self,*args):event('read_buffer',*args)
                def glGetIntegerv(self,key,ptr):
                    event('get',key);ptr._obj.value=previous[0] if key==10 else previous[1]
                def glReadPixels(self,x,y,w,h,fmt,kind,ptr):
                    event('read_pixels',x,y,w,h,fmt,kind)
                    data=bytes((i%251 for i in range(w*h*4)));ctypes.memmove(ptr,data,len(data))
            ns=dict(ctypes=ctypes,c_int=ctypes.c_int,c_uint=ctypes.c_uint,c_void_p=ctypes.c_void_p,byref=ctypes.byref,
               opengl32=GL(),GL_READ_FRAMEBUFFER=1,GL_PACK_ALIGNMENT=2,GL_COLOR_ATTACHMENT0=3,GL_BGRA=4,GL_UNSIGNED_BYTE=5,
               GL_READ_FRAMEBUFFER_BINDING=10,GL_READ_BUFFER=11)
            exec(compiled,ns);obj=ns['WGLHardwareContext']();obj.width=12;obj.height=9;obj.shared_context_enabled=shared
            obj.fbo=77;obj.frontend_read_fbo=88;obj.make_current=lambda:event('core_current') or True;obj.make_frontend_current=lambda:event('frontend_current') or True;obj.glBindFramebuffer=lambda *a:event('bind',*a)
            try:value=obj.capture_bgra(width,height);error=None
            except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
            results.append((value,error,events))
        self.assertEqual(*results);return results[1]

    def test_dimensions_pixels_and_path_order(self):
        rng=random.Random(97)
        for shared in (False,True):
            for i in range(120):
                width,height=rng.randint(-5,25),rng.randint(-5,20)
                value,error,events=self.compare(width,height,shared);self.assertIsNone(error)
                w,h=max(1,min(width,12)),max(1,min(height,9));self.assertEqual(value[1:],(w,h));self.assertEqual(value[0],bytes(i%251 for i in range(w*h*4)))
            value,error,events=self.compare(3,2,shared)
            expected=['core_current','finish','frontend_current','bind','pixel_store','read_buffer','read_pixels','core_current'] if shared else ['core_current','get','get','bind','finish','pixel_store','read_buffer','read_pixels','bind','read_buffer']
            self.assertEqual([e[0] for e in events],expected)


    def test_previous_signed_state_and_zero_handles(self):
        for previous in ((0,0),(77,3),(-1,-2),(2147483647,-2147483648)):
            value,error,events=self.compare(1,1,previous=previous)
            self.assertEqual(events[-2:], [('bind',1,ctypes.c_uint(previous[0]).value),('read_buffer',ctypes.c_uint(previous[1]).value)])

    def test_invalid_dimensions_before_gl(self):
        for shared in (False,True):
            for width,height in (('bad',2),(2,None),(float('nan'),1),(1,float('inf'))):
                value,error,events=self.compare(width,height,shared);self.assertIsNotNone(error);self.assertEqual(events,[])

if __name__=='__main__':unittest.main()
