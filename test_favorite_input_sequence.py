import ast
import contextlib
import ctypes
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import favorite_input as inputs
from favorites import validate_favorites, save_favorites, load_favorites, favorite_candidates
from startup_preparation import apply_loaded_core_settings


def step(seconds,key='Start',device='joypad'):
    return dict(delay_seconds=seconds,device=device,key=key)


class SequenceTests(unittest.TestCase):
    def test_roundtrip_both_shapes_and_reject_bad_sequence_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'favorites.json'
            data={'enabled':True,'items':[{'system':'a','rom':'one','startup_input':step(5)},
                {'system':'a','rom':'two','startup_input':[step(5),step(6,'A'),step(8,'Enter','keyboard')]}]}
            save_favorites(path,data);self.assertEqual(load_favorites(path),data)
            original=path.read_bytes()
            for bad in ([],[[]],[None],[step(5),step(4)],[step(0),step(float('nan'))],
                        [step(0),step(True)],[step(0),step(1,'Enter')]):
                with self.assertRaises(ValueError):save_favorites(path,{'items':[{'system':'a','rom':'x','startup_input':bad}]})
                self.assertEqual(path.read_bytes(),original)
            summary=inputs.input_summary(data['items'][1]['startup_input'])
            self.assertIn('5秒後',summary);self.assertIn('Enter',summary);self.assertEqual(summary.count('→'),2)

    def test_start_relative_deadlines_mixed_devices_and_release(self):
        press=inputs.FavoritePress([step(5),step(6,'A'),step(8,'Enter','keyboard')]);callback=Mock()
        samples=[(10,0,0,0),(14.99,0,0,0),(15,1,0,0),(15.2,0,0,0),
                 (16,0,1,0),(16.2,0,0,0),(18,0,0,1),(18.2,0,0,0),(100,0,0,0)]
        for now,start,a,enter in samples:
            press.advance(now);press.dispatch_keyboard(callback)
            self.assertEqual((press.state(0,1,0,3),press.state(0,1,0,8),press.state(0,3,0,13)),(start,a,enter))
        self.assertEqual(press.count,3)
        self.assertEqual([c.args for c in callback.call_args_list],[(True,13,13,0),(False,13,0,0)])

    def test_repeated_keys_equal_times_and_long_stall_have_release_frames(self):
        press=inputs.FavoritePress([step(0,'Enter','keyboard')]*3);callback=Mock();states=[]
        for now in (0,100,100.01,100.2,100.21,100.4,500):
            press.advance(now);press.dispatch_keyboard(callback);states.append(press.state(0,3,0,13))
        self.assertEqual(states,[1,0,1,0,1,0,0]);self.assertEqual(press.count,3)
        self.assertEqual([c.args[0] for c in callback.call_args_list],[True,False]*3)

    def test_keyboard_release_uses_previous_key_before_next_device(self):
        press=inputs.FavoritePress([step(0,'Lshift','keyboard'),step(0,'A','keyboard'),step(0,'B')]);callback=Mock()
        for now in (0,.2,.21,.4,.41,.6):
            press.advance(now);press.dispatch_keyboard(callback)
        self.assertEqual([c.args for c in callback.call_args_list],
                         [(True,304,0,1),(False,304,0,0),(True,97,97,0),(False,97,0,0)])
        self.assertFalse(press.down);self.assertEqual(press.count,3)

    def test_single_object_and_single_item_sequence_have_identical_behavior(self):
        a=inputs.FavoritePress(step(2));b=inputs.FavoritePress([step(2)])
        for now in (10,11,12,12.05,12.2,20):
            self.assertEqual(a.advance(now),b.advance(now))
            self.assertEqual((a.config,a.count,a.down,a.state(0,1,0,3)),(b.config,b.count,b.down,b.state(0,1,0,3)))

    def test_catalog_routing_copies_steps_and_does_not_leak_into_another_rom(self):
        sequence=[step(5),step(6,'A')];system={'id':'a'};a,b=Path('a'),Path('b')
        favorites=favorite_candidates([system],{'a':[a,b]},
            {'items':[{'system':'a','rom':'a','startup_input':sequence}]})
        marked=inputs.system_for_favorite_rom(system,a,favorites)
        press=inputs.FavoritePress(marked['_favorite_startup_input'])
        press.config['key']='B'
        self.assertEqual(sequence[0]['key'],'Start')
        self.assertEqual(marked['_favorite_startup_input'][0]['key'],'Start')
        self.assertNotIn('_favorite_startup_input',inputs.system_for_favorite_rom(marked,b,favorites))
        self.assertNotIn('_favorite_startup_input',system)

    def test_slot_json_and_cd_default_override(self):
        system={'_favorite_startup_input':[step(5),step(6,'A')]}
        decoded=json.loads(json.dumps(system));core=SimpleNamespace()
        for sid in ('megacd','pcenginecd','pc88'):
            apply_loaded_core_settings(core,decoded,sid)
            self.assertIsInstance(core._startup_input,inputs.FavoritePress)
            self.assertEqual(core._startup_input.steps,system['_favorite_startup_input'])

    def test_insert_and_remove_preserve_other_rom_sequence(self):
        import saver_actions
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'favorites.json';a=Path(temp)/'a';b=Path(temp)/'b'
            system={'id':'a'};catalogs={'a':[a,b]};sequence=[step(5),step(6,'Enter','keyboard')]
            save_favorites(path,{'items':[{'system':'a','rom':str(a),'startup_input':sequence}]})
            self.assertTrue(saver_actions.add_favorite(path,system,b,catalogs))
            self.assertTrue(saver_actions.remove_favorite(path,system,b,catalogs))
            self.assertEqual(load_favorites(path)['items'][0]['startup_input'],sequence)

    def test_actual_core_callbacks_send_sequence_before_run_and_never_leave_key_down(self):
        import libretro_abi as abi
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if getattr(n,'name','')=='LibretroCore')
        node.body=[n for n in node.body if getattr(n,'name','') in ('_handle_environment','_install_callbacks','run_frame')]
        clock=[10.];ns=dict(vars(abi),ctypes=ctypes,time=SimpleNamespace(monotonic=lambda:clock[0]),ENV_NAMES={})
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<sequence callbacks>','exec'),ns)
        core=ns['LibretroCore']()
        core.__dict__.update(_startup_input=inputs.FavoritePress([step(0,'Enter','keyboard'),step(.3),step(.6,'Space','keyboard')]),
            _startup_input_label='test',_run_frame_index=0,env_trace_frames=0,_callback_error=None,
            hw_context=None,frame_rebind_context=True,frame_bytes=None,_read_pending_hw_frame=lambda:None)
        registered={};events=[];observed=[]
        @inputs.KeyboardEvent
        def callback(*args):events.append(args)
        core.dll=SimpleNamespace(**{name:(lambda fn,n=name:registered.__setitem__(n,fn)) for name in
            ('retro_set_environment','retro_set_video_refresh','retro_set_audio_sample',
             'retro_set_audio_sample_batch','retro_set_input_poll','retro_set_input_state')})
        core._install_callbacks()
        address=ctypes.c_void_p(ctypes.cast(callback,ctypes.c_void_p).value)
        self.assertTrue(registered['retro_set_environment'](abi.RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK,ctypes.byref(address)))
        poll=registered['retro_set_input_state']
        core.dll.retro_run=lambda:observed.append((poll(0,3,0,13),poll(0,1,0,3),poll(0,3,0,32)))
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            for now in (10,10.2,10.31,10.5,10.61,10.8,50):clock[0]=now;core.run_frame()
        self.assertEqual(observed,[(1,0,0),(0,0,0),(0,1,0),(0,0,0),(0,0,1),(0,0,0),(0,0,0)])
        self.assertEqual(events,[(True,13,13,0),(False,13,0,0),(True,32,32,0),(False,32,0,0)])
        self.assertEqual(output.getvalue().count('[favorite-input]'),3)


if __name__=='__main__':unittest.main()
