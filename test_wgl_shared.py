import ast,copy,ctypes,contextlib,io,unittest
from pathlib import Path
import libretro_abi as abi
import wgl_bindings
ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_wgl_shared_v098.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')


def compile_context(source):
 t=ast.parse(source)
 body=[n for n in t.body if (isinstance(n,ast.ClassDef) and n.name=='WGLHardwareContext') or (isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id.startswith(('GL_','WGL_','PFD_')) for x in n.targets))]
 return compile(ast.Module(body=body,type_ignores=[]),'<shared>','exec')
CODES=[compile_context(s) for s in (OLD,NEW)]
class SharedTests(unittest.TestCase):
 def compare(self,core=False,fail=None,share=True,create=True,status=True,enabled=False,hdc=17,ctx=31,delete_fail=False):
  results=[]
  for compiled in CODES:
   events=[]
   def event(name,*args):
    events.append((name,*args))
    if len(events)==fail:raise OSError('injected')
   class GL:
    def glGetError(self): return 0
    def wglCreateContext(self,dc):event('create',dc);return 41 if create else 0
    def wglShareLists(self,a,b):event('share',a,b);return share
    def wglDeleteContext(self,c):
     event('delete',c)
     if delete_fail:raise OSError('delete failed')
   ns=dict(vars(ctypes));ns.update(vars(abi));ns.update(ctypes=ctypes,opengl32=GL())
   exec(compiled,ns);o=ns['WGLHardwareContext'].__new__(ns['WGLHardwareContext'])
   o.__dict__.update(shared_context_enabled=enabled,hdc=hdc,core_hglrc=ctx,frontend_hglrc=None,frontend_read_fbo=0,color_tex=61,fbo=62,context_type=abi.RETRO_HW_CONTEXT_OPENGL_CORE if core else abi.RETRO_HW_CONTEXT_OPENGL)
   o._create_attrib_context=lambda share_context:event('attrib',share_context) or 41
   o.make_frontend_current=lambda:event('frontend_current') or True
   o.make_current=lambda:event('core_current') or True
   def gen(n,p):event('gen',n);p._obj.value=71
   o.glGenFramebuffers=gen
   o.glBindFramebuffer=lambda *a:event('bind',*a)
   o.glFramebufferTexture2D=lambda *a:event('attach',*a)
   o.glCheckFramebufferStatus=lambda *a:event('status',*a) or (ns['GL_FRAMEBUFFER_COMPLETE'] if status else 0)
   log=io.StringIO()
   with contextlib.redirect_stdout(log):
    try:value=o.enable_shared_context();err=None
    except Exception as e:value=None;err=(type(e).__name__,str(e))
   results.append((value,err,events,tuple(getattr(o,k) for k in ('shared_context_enabled','frontend_hglrc','frontend_read_fbo')),log.getvalue()))
  self.assertEqual(*results);return results[1]
 def test_shared_context_success_and_short_circuits(self):
  for core in (False,True):
   r=self.compare(core=core);self.assertEqual(r[0],True);self.assertEqual(r[3],(True,41,71))
  for opts in ({'enabled':True},{'hdc':0},{'ctx':None}):self.assertEqual(self.compare(**opts)[2],[])
 def test_binding_signatures_order_and_partial_failure(self):
  for failure in (None,*range(1,16)):
   results=[]
   for compiled in CODES:
    ns=dict(vars(ctypes));ns.update(vars(abi));exec(compiled,ns);o=ns['WGLHardwareContext'].__new__(ns['WGLHardwareContext']);events=[]
    def load(*args):
     events.append(args)
     if len(events)==failure:raise RuntimeError('missing GL function')
     return len(events)
    o._load_gl=load
    try:o._init_gl_functions();error=None
    except Exception as e:error=(type(e).__name__,str(e))
    results.append((events,error,{k:v for k,v in vars(o).items() if k!='_load_gl'}))
   self.assertEqual(*results)
   self.assertEqual(len(results[0][0]),failure or 15)
if __name__=='__main__':unittest.main()
