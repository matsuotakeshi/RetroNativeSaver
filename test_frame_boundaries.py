"""Compare core preparation and frame boundaries against the v0.20.88 baseline."""
import ast
import contextlib
import copy
import ctypes
import gc
import io
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
import libretro_abi as abi

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_frames_v088.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')

def core_node(source):
    return next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='LibretroCore')


def core_type(source):
    core=core_node(source)
    keep={'_install_callbacks','_register_perf_interface','_register_hw_render','_receive_video','_prepare_game_info','_read_pending_hw_frame','load_game','run_frame'}
    core.body=[n for n in core.body if getattr(n,'name','') in keep]
    ns=dict(vars(abi));ns.update(ctypes=ctypes,Path=Path,byref=ctypes.byref,time=SimpleNamespace(monotonic=lambda:100.0),decode_cstr=lambda v: v.decode('utf-8',errors='replace') if v else '',ENV_NAMES={})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[core],type_ignores=[])),'<core boundary>','exec'),ns)
    return ns['LibretroCore']

TYPES=[core_type(OLD),core_type(NEW)]

def new_core(cls):
    c=cls()
    defaults=dict(hw_context=None,frame_bytes=b'old',frame_w=9,frame_h=8,frame_pitch=7,frame_bottom_up=True,
      pixel_format=abi.RETRO_PIXEL_FORMAT_RGB565,_pending_hw_frame=None,_frame_layout_logged=False,
      system_info=None,core_option_overrides={},_game_data_buffer=None,_in_load_game=False,
      hw_context_reset_done=False,hw_context_reset_addr=0,display_aspect=0.0,_run_frame_index=0,
      _startup_input=None,frame_rebind_context=True,env_trace_frames=0,hw_readback=True,
      provide_log_interface=True,provide_perf_interface=True)
    c.__dict__.update(defaults)
    return c

def state(c):
    names=('frame_bytes','frame_w','frame_h','frame_pitch','frame_bottom_up','pixel_format',
           '_pending_hw_frame','_frame_layout_logged','_in_load_game','display_aspect',
           'hw_context_reset_done','_run_frame_index','core_option_overrides','_rom_path_bytes')
    return {n:copy.deepcopy(getattr(c,n)) for n in names if hasattr(c,n)}

def outcome(fn):
    log=io.StringIO()
    with contextlib.redirect_stdout(log):
        try:result=fn();error=None
        except Exception as exc:result=None;error=(type(exc).__name__,str(exc))
    return result,error,log.getvalue()

class FrameBoundaryTests(unittest.TestCase):

    def video(self,cls):
        # Real ctypes registration retains exactly the same callbacks as production.
        c=new_core(cls);registered={}
        c.dll=SimpleNamespace(**{name:(lambda value,n=name:registered.__setitem__(n,value)) for name in
          ('retro_set_environment','retro_set_video_refresh','retro_set_audio_sample','retro_set_audio_sample_batch','retro_set_input_poll','retro_set_input_state')})
        c._install_callbacks();gc.collect()
        self.assertIs(registered['retro_set_video_refresh'],c._video)
        return c,registered

    def test_software_buffers_and_padding(self):
        rng=random.Random(89)
        for i in range(150):
            w,h=rng.randrange(1,24),rng.randrange(1,12);fmt=rng.choice([0,1,2]);pitch=w*(4 if fmt==1 else 2)+rng.randrange(5)
            raw=rng.randbytes(pitch*h);buf=ctypes.create_string_buffer(raw);results=[]
            for cls in TYPES:
                c,callbacks=self.video(cls);c.pixel_format=fmt
                _,err,log=outcome(lambda:c._video(ctypes.addressof(buf),w,h,pitch))
                self.assertEqual(c.frame_bytes,raw);self.assertFalse(c.frame_bottom_up)
                _,_,again=outcome(lambda:c._video(ctypes.addressof(buf),w,h,pitch))
                self.assertEqual(again,'')
                results.append((state(c),err,log))
            self.assertEqual(*results)

    def test_null_and_hardware_frames(self):
        for hw in (False,True):
            for width,height in ((0,0),(320,240),(1,640)):
                results=[]
                for cls in TYPES:
                    c,callbacks=self.video(cls)
                    if hw:c.hw_context=SimpleNamespace()  # No GL methods: callback must never touch GL.
                    c._video(None,width,height,0)
                    self.assertEqual(c.frame_bytes,b'old')
                    if hw:
                        c._video(abi.RETRO_HW_FRAME_BUFFER_VALID,width,height,0)
                        self.assertEqual(c._pending_hw_frame,(width,height));self.assertEqual(c.frame_bytes,b'old')
                    results.append(state(c))
                self.assertEqual(*results)

    def test_registered_input_audio_callbacks_unchanged(self):
        for cls in TYPES:
            c,callbacks=self.video(cls)
            self.assertEqual(c._state(0,1,0,3),0)
            c._startup_input=SimpleNamespace(state=lambda p,d,i,b: int((p,d,i,b)==(0,1,0,3)))
            self.assertEqual(c._state(0,1,0,3),1)
            self.assertEqual(c._audio_batch(None,17),17);c._audio(0,0);c._poll()

    def load_case(self,path,info=None,overrides=None,fail=None,hw=False):
        results=[]
        for cls in TYPES:
            c=new_core(cls);c.system_info=info;c.core_option_overrides=dict(overrides or {});events=[]
            def load(ptr):
                gi=ctypes.cast(ptr,ctypes.POINTER(abi.RetroGameInfo))[0]
                gc.collect()
                events.append(('load',c._in_load_game,gi.path,gi.size,ctypes.string_at(gi.data,gi.size) if gi.data else None,gi.meta))
                if fail=='load':raise RuntimeError('load failure')
                return fail!='false'
            def avinfo(ptr):
                events.append(('av',c._in_load_game))
                if fail=='av':raise RuntimeError('av failure')
                av=ctypes.cast(ptr,ctypes.POINTER(abi.RetroSystemAVInfo))[0]
                av.geometry.base_width=320;av.geometry.base_height=240;av.geometry.aspect_ratio=0;av.timing.fps=60
            def context():
                events.append(('context',c._in_load_game))
                if fail=='context':raise RuntimeError('context failure')
            reset=abi.RetroHWContextResetCallback(lambda:events.append(('reset',)))
            if hw:
                c.hw_context=SimpleNamespace(make_current=lambda:events.append(('current',)) or True)
                c.hw_context_reset_addr=ctypes.cast(reset,ctypes.c_void_p).value
            c.dll=SimpleNamespace(retro_load_game=load,retro_get_system_av_info=avinfo);c._create_deferred_hw_context=context
            result,error,log=outcome(lambda:c.load_game(path))
            avtuple=None if result is None else (result.geometry.base_width,result.geometry.base_height,result.timing.fps)
            results.append((events,state(c),avtuple,error,log))
        self.assertEqual(*results)
        return results[1]

    def test_fullpath_and_memory_rom_lifetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'日本語 game.rom';p.write_bytes(b'a\x00b'*33)
            for full in (True,False):
                result=self.load_case(p,SimpleNamespace(library_name=b'Other',need_fullpath=full),hw=True)
                self.assertIsNone(result[3]);self.assertEqual(result[0][0][4],None if full else p.read_bytes())
                self.assertEqual(result[0][1:],[('av',False),('context',False),('current',),('reset',)])
            self.load_case(p,None)
            p.write_bytes(b'');self.load_case(p,SimpleNamespace(library_name=b'Other',need_fullpath=False))

    def test_load_failures_and_partial_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'game.rom';p.write_bytes(b'rom')
            for fail in ('false','av','context'):
                result=self.load_case(p,fail=fail)
                self.assertIsNotNone(result[3]);self.assertFalse(result[1]['_in_load_game'])
            missing=Path(tmp)/'missing.rom'
            result=self.load_case(missing,SimpleNamespace(library_name=b'Other',need_fullpath=False))
            self.assertEqual(result[0],[]);self.assertEqual(result[3][0],'FileNotFoundError')

    def test_wonderswan_orientation_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'game.ws';info=SimpleNamespace(library_name=b'Beetle WonderSwan',need_fullpath=True)
            for flag in (0,1):
                p.write_bytes(bytes(65532)+bytes([flag,0,0,0]))
                result=self.load_case(p,info)
                self.assertEqual(result[1]['core_option_overrides']['wswan_rotate_display'],b'portrait' if flag else b'landscape')
                self.load_case(p,info,{'wswan_rotate_display':b'manual'})
            p.write_bytes(b'x');result=self.load_case(p,info);self.assertEqual(result[0],[])
            self.assertEqual(result[3][0],'ValueError')

    def run_case(self,hw=True,pending=(10,20),readback=True,rebind=True,fail=None,logged=False,trace=2,startup=False):
        results=[]
        for cls in TYPES:
            c=new_core(cls);events=[];c.hw_readback=readback;c.frame_rebind_context=rebind;c.env_trace_frames=trace;c._frame_layout_logged=logged
            def current():
                events.append(('current',))
                if fail=='current':raise RuntimeError('current failure')
                return True
            def capture(w,h):
                events.append(('capture',w,h))
                if fail=='capture':raise RuntimeError('capture failure')
                return b'frame',7,8
            if hw:c.hw_context=SimpleNamespace(make_current=current,capture_bgra=capture)
            def run():
                events.append(('run',c._pending_hw_frame));c._pending_hw_frame=pending
                if fail=='run':raise RuntimeError('run failure')
            c.dll=SimpleNamespace(retro_run=run)
            c._pending_hw_frame=(99,99)
            if startup:
                c._startup_input=SimpleNamespace(advance=lambda t:events.append(('input',t)) or True,count=1);c._startup_input_label='test'
            _,error,log=outcome(c.run_frame)
            results.append((events,state(c),error,log))
        self.assertEqual(*results)
        return results[1]

    def test_readback_order_and_frame_state(self):
        r=self.run_case(startup=True)
        self.assertEqual(r[0],[('input',100.0),('current',),('run',None),('current',),('capture',10,20)])
        self.assertEqual((r[1]['frame_w'],r[1]['frame_h'],r[1]['frame_pitch']),(7,8,28))
        self.assertTrue(r[1]['frame_bottom_up']);self.assertIsNone(r[1]['_pending_hw_frame'])

    def test_readback_disabled_missing_frames_and_options(self):
        for hw in (False,True):
            for pending in (None,(0,0),(320,240)):
                for readback in (False,True):
                    for rebind in (False,True):
                        for logged in (False,True):
                            self.run_case(hw,pending,readback,rebind,logged=logged,trace=0)

    def test_run_and_readback_failures(self):
        for failure in ('current','run','capture'):
            for rebind in (False,True):
                r=self.run_case(fail=failure,rebind=rebind);self.assertIsNotNone(r[2])

if __name__=='__main__':unittest.main()
