import ast
import contextlib
import ctypes
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import favorite_input as inputs
from favorites import validate_favorites,save_favorites,load_favorites,favorite_candidates
from startup_preparation import apply_loaded_core_settings
from startup_input import StartTwice

CONFIG=dict(delay_seconds=2.5,device='keyboard',key='Enter')
ROOT=Path(__file__).parent

class FavoriteInputTests(unittest.TestCase):
    def test_old_files_and_new_fields_roundtrip(self):
        old={'enabled':True,'items':[{'system':'pc88','rom':'game.d88'}]}
        self.assertEqual(validate_favorites(old),old)
        data={'enabled':True,'items':[dict(old['items'][0],startup_input=CONFIG)]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'favorites.json';save_favorites(path,data)
            self.assertEqual(load_favorites(path),data)
            original=path.read_bytes()
            for bad in (None,{},dict(CONFIG,delay_seconds=-1),dict(CONFIG,key='invalid')):
                with self.assertRaises(ValueError):save_favorites(path,{'items':[dict(old['items'][0],startup_input=bad)]})
                self.assertEqual(path.read_bytes(),original)

    def test_invalid_input_cannot_reach_runtime(self):
        for delay in (-1,True,None,'5',float('inf'),float('nan'),10**1000):
            with self.assertRaises(ValueError):inputs.validate_input(dict(CONFIG,delay_seconds=delay))
        for device,key in [('other','Enter'),('joypad','Enter'),('keyboard','Start'),([], 'Enter')]:
            with self.assertRaises(ValueError):inputs.validate_input(dict(CONFIG,device=device,key=key))
        self.assertEqual(inputs.validate_input(dict(CONFIG,delay_seconds=0))['delay_seconds'],0)

    def test_catalog_match_keeps_settings_local_and_safety_filters(self):
        system=dict(id='pc88');one=Path('one.d88');two=Path('two.d88')
        data={'items':[dict(system='pc88',rom=str(one),startup_input=CONFIG)]}
        favorites=favorite_candidates([system],{'pc88':[one,two]},data)
        self.assertNotIn('_favorite_startup_input',system)
        self.assertEqual(favorites[0][0]['_favorite_startup_input'],CONFIG)
        self.assertEqual(inputs.system_for_favorite_rom(system,one,favorites)['_favorite_startup_input'],CONFIG)
        self.assertIs(inputs.system_for_favorite_rom(system,two,favorites),system)
        self.assertNotIn('_favorite_startup_input',inputs.system_for_favorite_rom(favorites[0][0],two,favorites))
        self.assertEqual(favorite_candidates([system],{'pc88':[two]},data,log=lambda s:None),[])
        self.assertEqual(favorite_candidates([system],{'pc88':[one]},dict(data,enabled=False)),[])

    def test_duplicates_keep_first_entry_setting(self):
        data={'items':[dict(system='s',rom='Game',startup_input=CONFIG),dict(system='S',rom='game')]}
        self.assertEqual(len(validate_favorites(data)['items']),1)
        self.assertEqual(validate_favorites(data)['items'][0]['startup_input'],CONFIG)

    def test_one_press_delay_and_release_even_after_long_stall(self):
        press=inputs.FavoritePress(CONFIG)
        for now,down in [(10,False),(12.49,False),(12.5,True),(12.55,True),(100,False),(101,False)]:
            press.advance(now);self.assertEqual(press.down,down)
            self.assertEqual(press.state(0,3,0,13),int(down))
        self.assertEqual(press.count,1)

    def test_all_buttons_mask_and_device_isolation(self):
        for name,ident in inputs.BUTTONS.items():
            press=inputs.FavoritePress(dict(delay_seconds=0,device='joypad',key=name));press.advance(0)
            self.assertEqual(press.state(0,1,0,ident),1)
            self.assertEqual(press.state(0,1,0,256),ctypes.c_int16(1<<ident).value)
            for args in [(1,1,0,ident),(0,3,0,ident),(0,1,1,ident),(0,1,0,(ident+1)%16)]:
                self.assertEqual(press.state(*args),0)
            press.advance(.11);self.assertEqual(press.state(0,1,0,256),0)

    def test_every_keyboard_key_and_callback_press_release(self):
        for name,ident in inputs.KEYBOARD.items():
            press=inputs.FavoritePress(dict(CONFIG,delay_seconds=0,key=name));event=Mock()
            press.advance(0);press.dispatch_keyboard(event);press.dispatch_keyboard(event)
            self.assertEqual(press.state(0,3,0,ident),1)
            self.assertEqual(press.state(0,1,0,ident),0)
            press.advance(.11);press.dispatch_keyboard(event)
            self.assertEqual([c.args[:2] for c in event.call_args_list],[(True,ident),(False,ident)])
            self.assertEqual(press.state(0,3,0,ident),0)
        enter=inputs.FavoritePress(dict(CONFIG,delay_seconds=0));event=Mock()
        enter.advance(0);enter.dispatch_keyboard(event);event.assert_called_once_with(True,13,13,0)

    def test_native_keyboard_callback_address_and_unregister(self):
        events=[]
        @inputs.KeyboardEvent
        def callback(down,key,char,mods):events.append((down,key,char,mods))
        address=ctypes.c_void_p(ctypes.cast(callback,ctypes.c_void_p).value)
        core=SimpleNamespace()
        self.assertTrue(inputs.register_keyboard_callback(core,ctypes.byref(address)))
        press=inputs.FavoritePress(dict(CONFIG,delay_seconds=0))
        press.advance(0);press.dispatch_keyboard(core._keyboard_event)
        press.advance(.11);press.dispatch_keyboard(core._keyboard_event)
        self.assertEqual(events,[(True,13,13,0),(False,13,0,0)])
        inputs.register_keyboard_callback(core,None);self.assertIsNone(core._keyboard_event)

    def test_personal_input_overrides_default_start_and_removal_restores_it(self):
        core=SimpleNamespace();system=dict(_favorite_startup_input=CONFIG)
        apply_loaded_core_settings(core,system,'megacd');self.assertIsInstance(core._startup_input,inputs.FavoritePress)
        apply_loaded_core_settings(core,{},'megacd');self.assertIsInstance(core._startup_input,StartTwice)
        other=SimpleNamespace(_startup_input=None);apply_loaded_core_settings(other,{},'pc88')
        self.assertIsNone(other._startup_input)

    def test_input_roundtrips_through_slot_spec_json(self):
        system=dict(id='pc88',_favorite_startup_input=CONFIG)
        decoded=json.loads(json.dumps(dict(system=system)))['system']
        core=SimpleNamespace();apply_loaded_core_settings(core,decoded,'pc88')
        self.assertEqual(core._startup_input.config,CONFIG)

    def test_actual_native_environment_poll_and_run_frame_callbacks(self):
        import libretro_abi as abi
        tree=ast.parse((ROOT/'native_saver.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if getattr(n,'name','')=='LibretroCore')
        node.body=[n for n in node.body if getattr(n,'name','') in ('_handle_environment','_install_callbacks','run_frame')]
        clock=[100.]
        ns=dict(vars(abi));ns.update(ctypes=ctypes,time=SimpleNamespace(monotonic=lambda:clock[0]),ENV_NAMES={})
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<native input integration>','exec'),ns)
        core=ns['LibretroCore']()
        core.__dict__.update(_startup_input=inputs.FavoritePress(dict(CONFIG,delay_seconds=0)),
            _startup_input_label='test',_run_frame_index=0,env_trace_frames=0,_callback_error=None,
            hw_context=None,frame_rebind_context=True,frame_bytes=None,_read_pending_hw_frame=lambda:None)
        registered={};events=[]
        @inputs.KeyboardEvent
        def callback(*args):events.append(args)
        address=ctypes.c_void_p(ctypes.cast(callback,ctypes.c_void_p).value)
        core.dll=SimpleNamespace(**{name:(lambda fn,n=name:registered.__setitem__(n,fn)) for name in
            ('retro_set_environment','retro_set_video_refresh','retro_set_audio_sample',
             'retro_set_audio_sample_batch','retro_set_input_poll','retro_set_input_state')})
        core._install_callbacks()
        self.assertTrue(registered['retro_set_environment'](abi.RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK,ctypes.byref(address)))
        observed=[];core.dll.retro_run=lambda:observed.append(registered['retro_set_input_state'](0,3,0,13))
        with contextlib.redirect_stdout(io.StringIO()):
            core.run_frame();clock[0]+=.11;core.run_frame();clock[0]+=10;core.run_frame()
        self.assertEqual(observed,[1,0,0]);self.assertEqual(events,[(True,13,13,0),(False,13,0,0)])

    def test_normal_retry_clears_previous_rom_input_and_applies_new_rom_input(self):
        import resource_policy
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'core.dll';source.touch()
            system=dict(id='pc88',name='PC88',core=str(source))
            one,two=Path('one.d88'),Path('two.d88')
            favorites=favorite_candidates([system],{'pc88':[one,two]},
                {'items':[dict(system='pc88',rom=str(one),startup_input=CONFIG)]})
            tree=ast.parse((ROOT/'native_saver.py').read_text(encoding='utf-8'))
            fn=next(n for n in tree.body if getattr(n,'name','')=='start_slot_with_retry')
            ns=dict(Path=Path,APP_DIR=root,shutil=Mock(),prepare_rom=lambda s,r,d:r,
                resolve_app_relative_path=lambda v,d:root/d,write_runtime_trace=Mock(),
                is_native_access_violation=lambda e:False,
                _resource_group_can_add=resource_policy._resource_group_can_add)
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'<favorite retry>','exec'),ns)
            # A normal tile can select a favorite ROM even without a marked system.
            core=Mock(_startup_input=None);ns['LibretroCore']=Mock(return_value=core)
            with contextlib.redirect_stdout(io.StringIO()):
                ns['start_slot_with_retry'](1,system,one,[system],{'pc88':[one,two]},
                    {},root,set(),favorite_inputs=favorites,max_attempts=1)
            self.assertIsInstance(core._startup_input,inputs.FavoritePress)
            # A failed marked favorite must not leak its input to a normal retry.
            bad,good=Mock(_startup_input=None),Mock(_startup_input=None)
            bad.load_game.side_effect=RuntimeError('bad ROM')
            ns['LibretroCore']=Mock(side_effect=[bad,good])
            with patch('slot_selection.normal_retry_candidate',return_value=(favorites[0][0],two)),contextlib.redirect_stdout(io.StringIO()):
                result=ns['start_slot_with_retry'](0,*favorites[0],[system],{'pc88':[one,two]},
                    {},root,set(),favorite_inputs=favorites,max_attempts=2)
            self.assertIsNone(good._startup_input)
            self.assertNotIn('_favorite_startup_input',result[2])
            self.assertEqual(result[3],two);bad.close.assert_called_once()

    def test_actual_independent_scheduler_applies_to_normal_tiles_only_for_matching_rom(self):
        import independent_slots as scheduler
        from test_parallel_startup import ParallelStartupTests
        favorite=dict(id='a',_favorite_startup_input=CONFIG)
        original=inputs.system_for_favorite_rom
        seen=[]
        def route(system,rom,favorites):
            result=original(system,rom,[(favorite,Path('a0.rom'))])
            seen.append((rom,result));return result
        # Force both a matching normal tile and a different ROM through real scheduling.
        selected=[(dict(id='a',name='A'),Path('a1.rom')),
                  (dict(id='a',name='A'),Path('a0.rom'))]
        with patch.object(scheduler,'select_slot',side_effect=selected),patch.object(inputs,'system_for_favorite_rom',side_effect=route):
            starts,events,error=ParallelStartupTests().run_case()
        self.assertIsNone(error);self.assertEqual([i for _,i in starts],[0,1])
        self.assertNotIn('_favorite_startup_input',seen[0][1])
        self.assertEqual(seen[1][1]['_favorite_startup_input'],CONFIG)


if __name__=='__main__':unittest.main()
