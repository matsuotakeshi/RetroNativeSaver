import ast
import contextlib
import ctypes
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
import libretro_abi as abi

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_core_v087.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
def legacy_abi():
    text=OLD[OLD.index('RETRO_API_VERSION = 1'):OLD.index('# ---------------- Win32 GDI / WGL')]
    ns=dict(vars(ctypes),ctypes=ctypes)
    exec(text,ns)
    return ns

def core_methods(source):
    tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LibretroCore')
    return {n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}

def handler(old, name, constant):
    methods=core_methods(OLD if old else NEW)
    if old:
        env=next(n for n in methods['_install_callbacks'].body if getattr(n,'name','')=='env')
        branch=next(n for n in env.body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and any(isinstance(x,ast.Name) and x.id==constant for x in n.test.comparators))
        fn=ast.parse('def run(self, data): pass').body[0]; fn.body=branch.body
    else: fn=methods[name]; fn.name='run'
    ns=dict(vars(ctypes)); ns.update(vars(abi)); ns['ctypes']=ctypes
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<handler>','exec'),ns)
    return ns['run']

class CoreBoundaryTests(unittest.TestCase):
    def test_abi_constants(self):
        for k,v in legacy_abi().items():
            if k.startswith('RETRO_'): self.assertEqual(getattr(abi,k),v,k)

    def test_structure_layouts(self):
        for k,old in legacy_abi().items():
            if k.startswith('Retro') and isinstance(old,type) and issubclass(old,ctypes.Structure):
                new=getattr(abi,k)
                self.assertEqual(ctypes.sizeof(old),ctypes.sizeof(new),k)
                self.assertEqual(ctypes.alignment(old),ctypes.alignment(new),k)
                self.assertEqual([(n,getattr(old,n).offset,ctypes.sizeof(t)) for n,t in old._fields_],[(n,getattr(new,n).offset,ctypes.sizeof(t)) for n,t in new._fields_])

    def test_callback_signatures(self):
        for k,old in legacy_abi().items():
            if isinstance(old,type) and issubclass(old,ctypes._CFuncPtr) and hasattr(abi,k):
                new=getattr(abi,k)
                self.assertEqual(old._flags_,new._flags_)
                self.assertEqual(old._restype_,new._restype_)
                self.assertEqual([ctypes.sizeof(x) for x in old._argtypes_],[ctypes.sizeof(x) for x in new._argtypes_])

    def test_binding_identical(self):
        node=core_methods(OLD)['_bind_api']; ns=dict(vars(abi))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<bind>','exec'),ns)
        class Dll:
            def __getattr__(self,n):
                obj=SimpleNamespace();setattr(self,n,obj);return obj
        a,b=Dll(),Dll();ns['_bind_api'](SimpleNamespace(dll=a));abi.bind_api(b)
        self.assertEqual(vars(a),vars(b))

    def test_perf_registration_and_lifetime(self):
        for old in (True,False):
            fn=handler(old,'_register_perf_interface','RETRO_ENVIRONMENT_GET_PERF_INTERFACE')
            for enabled in (False,True):
                owner=SimpleNamespace(provide_perf_interface=enabled); cb=abi.RetroPerfCallback()
                self.assertFalse(fn(owner,None))
                self.assertEqual(fn(owner,ctypes.addressof(cb)),enabled)
                if not enabled: continue
                import gc;gc.collect()
                self.assertEqual(abi.RetroPerfGetCpuFeaturesCallback(cb.get_cpu_features)(),0)
                self.assertGreater(abi.RetroPerfGetTimeUsecCallback(cb.get_time_usec)(),0)
                counter=abi.RetroPerfCounter();ptr=ctypes.pointer(counter)
                owner._perf_register_cb(ptr);self.assertTrue(counter.registered)
                owner._perf_stop_cb(ptr);self.assertEqual(counter.call_cnt,0)
                owner._perf_start_cb(ptr);owner._perf_stop_cb(ptr)
                self.assertEqual(counter.call_cnt,1);self.assertGreaterEqual(counter.total,0)
                owner._perf_register_cb(None);owner._perf_start_cb(None);owner._perf_stop_cb(None);owner._perf_log_cb()

    def test_hw_registration_matches(self):
        for backend in ('software','opengl','glcore','other'):
            for requested in (0,1,3,4):
                results=[]
                for old in (True,False):
                    fn=handler(old,'_register_hw_render','RETRO_ENVIRONMENT_SET_HW_RENDER')
                    owner=SimpleNamespace(render_backend=backend,hw_context=None)
                    hw=abi.RetroHWRenderCallback(context_type=requested,version_major=3,version_minor=2,debug_context=True,context_reset=123,context_destroy=456)
                    log=io.StringIO()
                    with contextlib.redirect_stdout(log):result=fn(owner,ctypes.addressof(hw))
                    state={k:v for k,v in vars(owner).items() if not k.startswith('_hw_')}
                    if result:
                        import gc;gc.collect()
                        self.assertEqual(owner._hw_get_fb_cb(),0);self.assertFalse(owner._hw_get_proc_cb(b'test'))
                        owner.hw_context=SimpleNamespace(framebuffer_id=lambda:29,proc_address=lambda n:42)
                        self.assertEqual(abi.RetroHWGetCurrentFramebufferCallback(hw.get_current_framebuffer)(),29)
                        self.assertEqual(abi.RetroHWGetProcAddressCallback(hw.get_proc_address)(b'glTest'),42)
                        owner.hw_context=None
                    results.append((result,state,log.getvalue()))
                    self.assertFalse(fn(owner,None))
                self.assertEqual(*results)


if __name__=='__main__':unittest.main()

