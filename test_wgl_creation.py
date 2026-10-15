import ast
import contextlib
import copy
import ctypes
import io
from pathlib import Path
import unittest
import libretro_abi as abi

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_wgl_creation_v097.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
NAMES={'_create_core_context','_log_context_created','_create_color_texture','_create_depth_stencil','_create_core_framebuffer'}
def context(source):return next(n for n in ast.parse(source).body if getattr(n,'name','')=='WGLHardwareContext')

def code(source):
    tree=ast.parse(source);c=context(source)
    constants=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id.startswith(('GL_','WGL_','PFD_')) for t in n.targets)]
    return compile(ast.Module(body=constants+[c],type_ignores=[]),'<WGL create>','exec')
CODES=(code(OLD),code(NEW))

class WglCreationTests(unittest.TestCase):

    def compare(self,core=True,fail_at=None,bootstrap=True,bootstrap_current=True,loader=True,modern_current=True,status=None,success_attempt=1,existing=False,requested=(3,3),share=None,attrib_only=False):
        results=[]
        for compiled in CODES:
            events=[];attempts=[0];context_switches=[0]
            def event(name,*args):
                events.append((name,*args))
                if len(events)==fail_at:raise OSError('injected creation failure')
            class GL:
                def glGetError(self): return 0
                def wglCreateContext(self,dc):event('bootstrap',dc);return 50 if bootstrap else 0
                def wglMakeCurrent(self,dc,ctx):
                    event('current',dc,ctx)
                    if ctx==50:return bootstrap_current
                    if ctx==60:return modern_current
                    return True
                def wglDeleteContext(self,ctx):event('delete_context',ctx);return True
                def glGetString(self,key):event('string',key);return b'GPU value'
            ns=dict(vars(ctypes));ns.update(vars(abi));ns.update(ctypes=ctypes,opengl32=GL(),HGLRC=ctypes.c_void_p,HDC=ctypes.c_void_p,decode_cstr=lambda v:v.decode('utf-8',errors='replace') if v else '')
            exec(compiled,ns);cls=ns['WGLHardwareContext'];obj=cls.__new__(cls)
            obj.__dict__.update(_ready=existing,hwnd=None,frontend_hglrc=None,_bootstrap_hglrc=None,core_hglrc=999 if existing else None,hdc=17 if (attrib_only or existing) else None,width=640,height=480,context_type=abi.RETRO_HW_CONTEXT_OPENGL_CORE if core else abi.RETRO_HW_CONTEXT_OPENGL,
                 version_major=requested[0],version_minor=requested[1],created_version=None,color_tex=0,depth_stencil_rb=0,fbo=0)
            def creator(dc,shared,attrs):
                attempts[0]+=1;event('attrib',dc,shared,tuple(attrs));return 60 if success_attempt==attempts[0] else 0
            obj._wgl_create_context_attribs=creator if loader else None
            obj._create_window_and_pixel_format=lambda:event('window') or setattr(obj,'hdc',17)
            obj._load_wgl_create_context_attribs=lambda:event('load_creator') or obj._wgl_create_context_attribs
            obj._init_gl_functions=lambda:event('load_gl')
            def gen(name,value):
                def f(count,ptr):event(name,count);ptr._obj.value=value
                return f
            obj.glGenTextures=gen('gen_texture',101);obj.glGenRenderbuffers=gen('gen_depth',102);obj.glGenFramebuffers=gen('gen_fbo',103)
            for name in ('glBindTexture','glTexParameteri','glTexImage2D','glBindRenderbuffer','glRenderbufferStorage','glBindFramebuffer','glFramebufferTexture2D','glFramebufferRenderbuffer'):
                setattr(obj,name,lambda *args,n=name:event(n,*args))
            def check(target):event('check_fbo',target);return ns['GL_FRAMEBUFFER_COMPLETE'] if status is None else status
            obj.glCheckFramebufferStatus=check
            log=io.StringIO()
            with contextlib.redirect_stdout(log):
                try:value=obj._create_attrib_context(share_context=share) if attrib_only else obj.create();error=None
                except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
            state={k:getattr(obj,k) for k in ('core_hglrc','created_version','color_tex','depth_stencil_rb','fbo')}
            results.append((value,error,events,state,log.getvalue()))
        self.assertEqual(*results);return results[1]

    def test_core_and_legacy_creation_order(self):
        for core in (False,True):
            r=self.compare(core);self.assertIsNone(r[1]);self.assertEqual((r[3]['color_tex'],r[3]['depth_stencil_rb'],r[3]['fbo']),(101,102,103))
            names=[e[0] for e in r[2]];self.assertLess(names.index('gen_texture'),names.index('gen_depth'));self.assertLess(names.index('gen_depth'),names.index('gen_fbo'))
        self.assertEqual(self.compare(existing=True)[2],[])



    def test_attribute_candidates_requested_minimum_and_share(self):
        for requested in ((0,0),(2,1),(3,0),(3,3),(4,6),(4,7),(5,0)):
            for share in (None,0,555):
                for success in (1,2,None):
                    self.compare(requested=requested,share=share,success_attempt=success,attrib_only=True)
        r=self.compare(requested=(3,3),share=555,attrib_only=True);self.assertEqual(r[3]['created_version'],(4,6));self.assertEqual(r[2][0][2],555)

if __name__=='__main__':unittest.main()
