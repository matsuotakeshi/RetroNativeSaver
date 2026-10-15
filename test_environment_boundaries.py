import ast
import contextlib
import copy
import ctypes
import gc
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
import libretro_abi as abi

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_environment_v094.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
NAMES={'_handle_environment','_register_log_interface','_set_variables','_get_variable'}
def core(source):return next(n for n in ast.parse(source).body if getattr(n,'name','')=='LibretroCore')
def restore_environment_core(c):
    methods={n.name:n for n in c.body if isinstance(n,ast.FunctionDef)}
    if '_handle_environment' not in methods:return c
    env=next(n for n in methods['_install_callbacks'].body if getattr(n,'name','')=='env')
    env.body=copy.deepcopy(methods['_handle_environment'].body)
    for n in env.body:
        if isinstance(n,ast.If) and len(n.body)==1 and isinstance(n.body[0],ast.Return):
            call=n.body[0].value
            if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr in NAMES:
                n.body=copy.deepcopy(methods[call.func.attr].body)
    c.body=[n for n in c.body if getattr(n,'name','') not in NAMES];return c

def build(source,old):
    c=core(source)
    if old:
        install=next(n for n in c.body if getattr(n,'name','')=='_install_callbacks')
        env=copy.deepcopy(next(n for n in install.body if getattr(n,'name','')=='env'))
        env.name='_handle_environment';env.decorator_list=[];env.args.args.insert(0,ast.arg(arg='self'));c.body.append(env)
    ns=dict(vars(ctypes));ns.update(vars(abi));ns.update(ctypes=ctypes,Path=Path,decode_cstr=lambda v:v.decode('utf-8',errors='replace') if v else '')
    envnames=next(n for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ENV_NAMES' for t in n.targets))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[envnames,c],type_ignores=[])),'<core environment>','exec'),ns)
    return ns['LibretroCore']
TYPES=(build(OLD,True),build(NEW,False))
def owner(cls):
    c=cls.__new__(cls)
    c.__dict__.update(env_trace_frames=0,_run_frame_index=0,system_info=None,provide_log_interface=True,provide_perf_interface=True,
       render_backend='software',pixel_format=2,trace_core_vars=True,variables={},core_option_overrides={},display_aspect=1.0,
       _system_dir_cstr=ctypes.c_char_p(b'system'),_save_dir_cstr=ctypes.c_char_p(b'save'),_assets_dir_cstr=ctypes.c_char_p(b'assets'),
       _hw_shared_requested=False,hw_context=None)
    return c

class EnvironmentBoundaryTests(unittest.TestCase):

    def compare(self,operation,options=None):
        results=[]
        for cls in TYPES:
            c=owner(cls);c.__dict__.update(copy.deepcopy(options or {}));log=io.StringIO()
            with contextlib.redirect_stdout(log):
                try:value=operation(c);error=None
                except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
            state={k:copy.deepcopy(getattr(c,k)) for k in ('variables','core_option_overrides','pixel_format','display_aspect','_hw_shared_requested')}
            results.append((value,error,state,log.getvalue()))
        self.assertEqual(*results);return results[1]

    def test_capability_and_null_responses(self):
        commands=[abi.RETRO_ENVIRONMENT_SET_ROTATION,abi.RETRO_ENVIRONMENT_SET_CONTROLLER_INFO,abi.RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE,
          abi.RETRO_ENVIRONMENT_GET_INPUT_BITMASKS,abi.RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK,abi.RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE,
          abi.RETRO_ENVIRONMENT_SET_DISK_CONTROL_EXT_INTERFACE,abi.RETRO_ENVIRONMENT_SET_SAVE_STATE_IN_BACKGROUND,abi.RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT,
          abi.RETRO_ENVIRONMENT_SET_CORE_OPTIONS,abi.RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL,abi.RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY,
          abi.RETRO_ENVIRONMENT_GET_VARIABLE,abi.RETRO_ENVIRONMENT_GET_LOG_INTERFACE,abi.RETRO_ENVIRONMENT_GET_PERF_INTERFACE,
          abi.RETRO_ENVIRONMENT_GET_FASTFORWARDING,abi.RETRO_ENVIRONMENT_GET_DISK_CONTROL_INTERFACE_VERSION,abi.RETRO_ENVIRONMENT_SET_HW_RENDER,9999]
        self.compare(lambda c:[c._handle_environment(cmd,None) for cmd in commands])
        for name in (b'Beetle WonderSwan',b'Flycast',b'',None):
            r=self.compare(lambda c:c._handle_environment(abi.RETRO_ENVIRONMENT_SET_ROTATION,None),{'system_info':SimpleNamespace(library_name=name)})
            self.assertEqual(r[0],name!=b'Beetle WonderSwan')

    def test_pointer_outputs_formats_and_geometry(self):
        def operation(c):
            result=[]
            for cmd in (abi.RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY,abi.RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY,abi.RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY):
                out=ctypes.c_char_p();result.append((c._handle_environment(cmd,ctypes.addressof(out)),out.value))
            for cmd in (abi.RETRO_ENVIRONMENT_GET_CAN_DUPE,abi.RETRO_ENVIRONMENT_GET_FASTFORWARDING,abi.RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE):
                out=ctypes.c_bool(True);result.append((c._handle_environment(cmd,ctypes.addressof(out)),out.value))
            for backend in ('software','opengl','glcore','other'):
                c.render_backend=backend;out=ctypes.c_uint(999);result.append((c._handle_environment(abi.RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER,ctypes.addressof(out)),out.value))
            for fmt in (0,1,2,3,999):
                value=ctypes.c_uint(fmt);result.append((c._handle_environment(abi.RETRO_ENVIRONMENT_SET_PIXEL_FORMAT,ctypes.addressof(value)),c.pixel_format))
            for aspect in (0.,-1.,1.5,2.):
                geo=abi.RetroGameGeometry(aspect_ratio=aspect);result.append((c._handle_environment(abi.RETRO_ENVIRONMENT_SET_GEOMETRY,ctypes.addressof(geo)),c.display_aspect))
                av=abi.RetroSystemAVInfo();av.geometry=geo;result.append((c._handle_environment(abi.RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO,ctypes.addressof(av)),c.display_aspect))
            return result
        self.compare(operation)

    def test_variables_actual_methods_and_buffer_lifetime(self):
        def operation(c):
            result=[]
            for raw in (None,b'',b'label',b'label; first|second',b'label; |second',b'label; a;extra|b'):
                values=(abi.RetroVariable*3)();values[0]=abi.RetroVariable(b'dolphin_x',raw);values[1]=abi.RetroVariable(b'key',raw)
                result.append(c._handle_environment(abi.RETRO_ENVIRONMENT_SET_VARIABLES,ctypes.addressof(values)))
                for key in (b'dolphin_x',b'key',b'dynamic',b'missing',None):
                    out=abi.RetroVariable(key,b'old');result.append(c._handle_environment(abi.RETRO_ENVIRONMENT_GET_VARIABLE,ctypes.addressof(out)));gc.collect();result.append(out.value)
            return result
        for trace in (False,True):self.compare(operation,{'trace_core_vars':trace,'core_option_overrides':{'key':b'override','dynamic':b'value'}})

    def test_registered_environment_and_log_callback_lifetime(self):
        for cls in TYPES:
            c=owner(cls);registered={}
            c.dll=SimpleNamespace(**{name:(lambda value,n=name:registered.__setitem__(n,value)) for name in
              ('retro_set_environment','retro_set_video_refresh','retro_set_audio_sample','retro_set_audio_sample_batch','retro_set_input_poll','retro_set_input_state')})
            c._install_callbacks();gc.collect();self.assertIs(c._env,registered['retro_set_environment'])
            out=ctypes.c_bool(False);self.assertTrue(c._env(abi.RETRO_ENVIRONMENT_GET_CAN_DUPE,ctypes.addressof(out)));self.assertTrue(out.value)
            for enabled in (False,True):
                c.provide_log_interface=enabled;cb=abi.RetroLogCallback()
                self.assertEqual(c._env(abi.RETRO_ENVIRONMENT_GET_LOG_INTERFACE,ctypes.addressof(cb)),enabled)
                if enabled:
                    gc.collect();self.assertEqual(cb.log,ctypes.cast(c._log_cb,ctypes.c_void_p).value)
                    abi.RetroLogPrintfCallback(cb.log)(1,b'fixed arguments only')
                else:self.assertFalse(cb.log)

if __name__=='__main__':unittest.main()
