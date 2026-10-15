"""Exercise the actual main/supervisor routing with fake windows/schedulers."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import config_snapshot
import independent_slots
import launch_options
import rom_catalog
import screen_layout
import single_system_mode as mode
from fixed_rom_catalog import Catalogs
import test_supervisor_session as supervisor_harness


class PresentationRoutingTests(unittest.TestCase):
    def run_main(self, sid, *, argv=('/s','--worker'), monitors=None):
        root=Path(__file__).parent
        systems=[dict(id=s,name=s,enabled=True,max_concurrent=i+1) for i,s in enumerate(mode.SUPPORTED)]
        catalogs=Catalogs({s['id']:[Path(s['id']+'.rom')] for s in systems})
        cfg=dict(independent_slots_enabled=True,fullscreen=True,multi_monitor=True,
                 **{mode.SESSION_KEY:sid})
        win=SimpleNamespace(virtual_left=0,virtual_top=0,create=lambda:True,
                            client_size=lambda:(800,600),close=Mock())
        ns=dict(__name__='routing_test',sys=SimpleNamespace(argv=['saver',*argv],modules={'routing_test':SimpleNamespace()}),
                os=SimpleNamespace(environ={}),APP_DIR=root,Path=Path,
                parse_screensaver_args=launch_options.parse_screensaver_args,
                init_runtime_trace_from_env=lambda:None,write_runtime_trace=lambda *a:None,
                resolve_app_relative_path=lambda value,default:root/(value or default),
                load_system_configs=lambda folder:copy.deepcopy(systems),
                _load_session_safety_from_env=lambda:({},set()),build_title_maps=lambda *a:{},
                GDIWindow=lambda *a,**k:win,
                get_monitor_rects=lambda:monitors or [(0,0,1920,1080),(1920,0,4480,1080)],
                build_monitor_slots=screen_layout.build_monitor_slots,
                build_windowed_slots=screen_layout.build_windowed_slots)
        tree=ast.parse((root/'native_saver.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if getattr(n,'name','')=='main')
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual presentation routing>','exec'),ns)
        with patch.object(config_snapshot,'load_worker_config',return_value=cfg), \
             patch.object(rom_catalog,'build_catalogs',return_value=catalogs), \
             patch.object(independent_slots,'run_scheduler',return_value=0) as scheduler:
            error=None
            try:result=ns['main']()
            except Exception as exc:result=None;error=exc
        return result,error,scheduler,win,systems,catalogs

    def test_actual_main_routes_64_tiles_only_to_chosen_machine(self):
        result,error,scheduler,win,original,catalogs=self.run_main('gb')
        self.assertIsNone(error);self.assertEqual(result,0);win.close.assert_called_once()
        api,window,rects,systems,filtered,cfg,fav,titles=scheduler.call_args.args
        self.assertEqual(len(rects),64);self.assertEqual([s['id'] for s in systems],['gb'])
        self.assertEqual(systems[0]['max_concurrent'],64)
        self.assertEqual(set(filtered),{'gb'});self.assertEqual(original[0]['max_concurrent'],1)
        self.assertEqual(set(catalogs),set(mode.SUPPORTED))
        self.assertTrue(cfg['_single_system_rendering'])
        self.assertEqual(cfg['independent_max_fps'],25)

    def test_normal_mode_keeps_original_layout_systems_and_limits(self):
        result,error,scheduler,win,original,catalogs=self.run_main(None)
        self.assertIsNone(error);self.assertEqual(result,0)
        self.assertEqual(len(scheduler.call_args.args[2]),12)
        self.assertEqual(scheduler.call_args.args[3],original)
        self.assertIs(scheduler.call_args.args[4],catalogs)
        self.assertNotIn('_single_system_rendering',scheduler.call_args.args[5])
        self.assertNotIn('independent_max_fps',scheduler.call_args.args[5])

    def test_grouped_main_routes_all_members_and_no_unrelated_machine(self):
        result,error,scheduler,win,original,catalogs=self.run_main(['megadrive','megacd'])
        self.assertIsNone(error);self.assertEqual(result,0);win.close.assert_called_once()
        self.assertEqual(len(scheduler.call_args.args[2]),64)
        self.assertEqual({s['id'] for s in scheduler.call_args.args[3]},{'megadrive','megacd'})
        self.assertTrue(all(s['max_concurrent']==64 for s in scheduler.call_args.args[3]))
        self.assertEqual(set(scheduler.call_args.args[4]),{'megadrive','megacd'})

    def test_fbneo_main_routes_16_plus_16_with_capacity_32(self):
        result,error,scheduler,win,original,catalogs=self.run_main(['fbneo'])
        self.assertIsNone(error);self.assertEqual(result,0);win.close.assert_called_once()
        rects=scheduler.call_args.args[2]
        self.assertEqual(len(rects),32)
        self.assertEqual(sum(x<1920 for x,y,w,h in rects),16)
        self.assertEqual(sum(x>=1920 for x,y,w,h in rects),16)
        self.assertEqual([s['id'] for s in scheduler.call_args.args[3]],['fbneo'])
        self.assertEqual(scheduler.call_args.args[3][0]['max_concurrent'],32)

    def test_explicit_fbneo_windowed_over_limit_closes_without_starting_children(self):
        argv=['--worker','--windowed','--slots','33','--presentation','single-system','--system','fbneo']
        result,error,scheduler,win,_,_=self.run_main(['fbneo'],argv=argv)
        self.assertIsInstance(error,ValueError);scheduler.assert_not_called();win.close.assert_called_once()

    def test_explicit_windowed_preview_uses_requested_count_and_closes_on_bad_count(self):
        argv=['--worker','--windowed','--slots','4','--presentation','single-system','--system','gb']
        result,error,scheduler,win,_,_=self.run_main('gb',argv=argv)
        self.assertIsNone(error);self.assertEqual(len(scheduler.call_args.args[2]),4)
        argv[3]='65'
        result,error,scheduler,win,_,_=self.run_main('gb',argv=argv)
        self.assertIsInstance(error,ValueError);scheduler.assert_not_called();win.close.assert_called_once()

    def test_more_than_64_monitor_layout_falls_back_to_normal(self):
        result,error,scheduler,win,original,_=self.run_main('gb',monitors=[(0,0,1920,1080)]*3)
        self.assertIsNone(error);self.assertEqual(len(scheduler.call_args.args[2]),12)
        self.assertEqual(scheduler.call_args.args[3],original)

    def test_actual_supervisor_does_not_repeat_lottery_after_recycle(self):
        with patch.object(mode,'prepare_session',side_effect=lambda cfg,*a,**k:cfg) as choose:
            result,error,events,launches,children=supervisor_harness.SupervisorSessionTests().run_session([(75,0),(0,0)],independent=True)
        self.assertIsNone(error);self.assertEqual(result,0);self.assertEqual(len(launches),2)
        choose.assert_called_once()
