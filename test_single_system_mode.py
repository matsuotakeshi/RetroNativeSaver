import copy
from pathlib import Path
import json
import random
import tempfile
import unittest
from unittest.mock import Mock

import single_system_mode as mode
from launch_options import parse_main_args
from fixed_rom_catalog import Catalogs, signature
from favorites import favorite_candidates
from independent_slots import select_slot, duration_seconds


class SingleSystemModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'systems').mkdir()
        (self.root/'roms').mkdir()
        (self.root/'test.dll').write_bytes(b'placeholder')
        self.systems = [dict(id=sid, name=sid, core=str(self.root/'test.dll'),
                             rom_dir=str(self.root/'roms'), max_concurrent=1,
                             enabled=True, render_backend='software') for sid in ('gb','gbc','megadrive')]
        self.save_systems()
        self.cfg = dict(independent_slots_enabled=True, fullscreen=True, cycle_seconds=150,
                        independent_jitter_seconds=15,
                        single_system_mode=dict(enabled=True, probability=.5, systems=list(('gb','gbc','megadrive'))))
        self.args = parse_main_args([], self.root)
        self.rng = Mock()
        self.rng.random.return_value = .1
        self.rng.choice.side_effect = lambda values: values[-1]

    def save_systems(self):
        for s in self.systems:
            (self.root/'systems'/f'{s["id"]}.json').write_text(json.dumps(s))

    def choose(self, cfg=None, args=None, launch='normal', **kwargs):
        return mode.prepare_session(self.cfg if cfg is None else cfg, self.root,
                                    self.args if args is None else args, launch, rng=self.rng, **kwargs)

    def test_explicit_redraw_repeats_weighted_lottery_and_group_choice(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['single_system_mode'].update(normal_weight=1,grouped_weight=3,groups=[['gb','gbc'],['megadrive']])
        self.rng.random.side_effect=[.9,.1,.1,.9]
        self.rng.choice.side_effect=lambda groups:groups[0] if self.rng.choice.call_count==1 else groups[-1]
        states=[]
        for _ in range(4):
            cfg=self.choose(cfg,reuse=False);states.append(cfg[mode.SESSION_KEY])
            before=self.rng.random.call_count
            self.assertIs(self.choose(cfg,reuse=True),cfg)
            self.assertEqual(self.rng.random.call_count,before)
        self.assertEqual(states,[None,['gb','gbc'],['megadrive'],None])
        self.assertEqual(cfg['single_system_mode']['normal_weight'],1)
        self.assertEqual(cfg['single_system_mode']['grouped_weight'],3)

    def test_old_config_and_manual_commands_keep_normal_behavior_without_draw(self):
        old = dict(self.cfg);del old['single_system_mode']
        self.assertEqual(self.choose(old), old)
        for argv in (['--windowed'], ['--system','gb'], ['--slots','3'], ['--presentation','normal']):
            self.assertNotIn(mode.SESSION_KEY, self.choose(args=parse_main_args(argv,self.root)))
        self.assertNotIn(mode.SESSION_KEY,self.choose(launch='preview'))
        self.assertNotIn(mode.SESSION_KEY,self.choose(dict(self.cfg,independent_slots_enabled=False)))
        self.rng.random.assert_not_called();self.rng.choice.assert_not_called()

    def test_probability_extremes_boundary_and_equal_machine_lottery(self):
        for probability, draw, dense in ((0,0,False),(.5,.5,False),(.5,.499,True),(1,.999,True)):
            cfg=copy.deepcopy(self.cfg);cfg['single_system_mode']['probability']=probability
            self.rng.random.return_value=draw
            result=self.choose(cfg)
            self.assertEqual(result[mode.SESSION_KEY] is not None,dense)
        self.assertEqual(set(self.rng.choice.call_args.args[0]),set(('gb','gbc','megadrive')))

    def test_unavailable_disabled_hardware_and_duplicates_not_selected(self):
        self.systems[0]['enabled']=False;self.systems[1]['core']=str(self.root/'absent.dll')
        self.save_systems()
        self.cfg['single_system_mode']['systems']=['gb','gb','gbc','megadrive']
        result=self.choose();self.assertEqual(result[mode.SESSION_KEY],'megadrive')
        self.assertEqual(self.rng.choice.call_args.args[0],['megadrive'])
        self.systems[2]['enabled']=False;self.save_systems()
        self.assertIsNone(self.choose()[mode.SESSION_KEY])

    def test_explicit_preview_command_reuses_windowed_slots_and_system_filter(self):
        args=parse_main_args(['--windowed','--slots','4','--presentation','single-system','--system','gb'],self.root)
        self.assertEqual(self.choose(args=args)[mode.SESSION_KEY],'gb')
        self.rng.random.assert_not_called()

    def test_invalid_optional_settings_fall_back_to_normal(self):
        for value in (None,[],True,{'enabled':True,'probability':float('nan')},
                      {'enabled':True,'probability':1.1},{'enabled':True,'probability':'0.5'},
                      {'enabled':True,'probability':False},{'enabled':True,'systems':['ps2']},
                      {'enabled':True,'systems':[{}]}):
            self.assertIsNone(self.choose(dict(self.cfg,single_system_mode=value)).get(mode.SESSION_KEY))

    def test_worker_restarts_keep_both_normal_and_single_system_choices(self):
        for sid in (None,'gb'):
            frozen=dict(self.cfg,**{mode.SESSION_KEY:sid})
            self.assertIs(self.choose(frozen,reuse=True),frozen)
        self.rng.random.assert_not_called();self.rng.choice.assert_not_called()

    def test_new_session_ignores_old_internal_choice_and_preserves_caller_config(self):
        cfg=dict(self.cfg,**{mode.SESSION_KEY:'gb'});before=copy.deepcopy(cfg)
        self.assertEqual(self.choose(cfg)[mode.SESSION_KEY],'megadrive')
        self.assertEqual(cfg,before)

    def test_snapshot_carries_one_choice_to_workers(self):
        from config_snapshot import ConfigSnapshot,load_worker_config
        cfg=self.choose();snapshot=ConfigSnapshot(cfg)
        try:
            env={};snapshot.apply(env)
            for _ in range(2):
                worker=load_worker_config(self.root/'no_file.json',env)
                self.assertEqual(self.choose(worker,reuse=True),cfg)
        finally:snapshot.close()

    def test_runtime_suspension_or_empty_catalog_stops_instead_of_switching_hardware(self):
        cfg=dict(self.cfg,**{mode.SESSION_KEY:'gb'})
        self.assertIs(mode.selected_systems(cfg,self.systems,{'gb':[Path('rom')]})[0],self.systems[0])
        with self.assertRaises(RuntimeError):mode.selected_systems(cfg,self.systems,{'gbc':[Path('rom')]})
        self.systems[0]['enabled']=False
        with self.assertRaises(RuntimeError):mode.selected_systems(cfg,self.systems,{'gb':[Path('rom')]})

    def test_exact_28_36_geometry_without_gaps_or_overlap(self):
        monitors=[(-1920,0,0,1080),(0,0,2560,1080)]
        rects=mode.monitor_slots(monitors,-1920,0)
        self.assertEqual(len(rects),64)
        for cells,offset,width in ((rects[:28],0,1920),(rects[28:],1920,2560)):
            self.assertEqual(sum(w*h for x,y,w,h in cells),width*1080)
            self.assertEqual(min(x for x,y,w,h in cells),offset)
            self.assertEqual(max(x+w for x,y,w,h in cells),offset+width)
            for i,(x,y,w,h) in enumerate(cells):
                self.assertGreater(w,0);self.assertGreater(h,0)
                for a,b,c,d in cells[i+1:]:
                    self.assertFalse(x<a+c and a<x+w and y<b+d and b<y+h)

    def test_monitor_order_primary_and_negative_origin_do_not_change_counts(self):
        rects=mode.monitor_slots([(-2560,-1080,0,0),(0,0,1920,1080)],-2560,-1080,2)
        self.assertEqual(len(rects),64)
        self.assertEqual(sum(y<1080 for x,y,w,h in rects),36)
        self.assertEqual(sum(y>=1080 for x,y,w,h in rects),28)
        self.assertEqual(len(mode.monitor_slots([(0,0,1920,1080)],0,0)),28)
        self.assertEqual(len(mode.monitor_slots([(0,0,2560,1080)],0,0)),36)
        self.assertIsNone(mode.monitor_slots([(0,0,1920,1080)]*3,0,0))

    def test_capacity_and_favorites_stay_local_and_rom_signatures_stay_identical(self):
        original=copy.deepcopy(self.systems[0]);roms=[Path(f'rom{i}.gb') for i in range(100)]
        catalog=Catalogs({'gb':roms,'gbc':[Path('other.gbc')]},{str(r):str(r) for r in roms})
        selected,filtered=mode.scheduler_inputs(self.systems[0],catalog,64)
        self.assertEqual(self.systems[0],original)
        self.assertEqual(signature(selected[0]),signature(original))
        self.assertIs(filtered.canonical_paths,catalog.canonical_paths)
        favorites=favorite_candidates(selected,filtered,{'items':[
            {'system':'gb','rom':str(roms[0])},{'system':'gbc','rom':'other.gbc'}]},log=lambda s:None)
        self.assertEqual(len(favorites),1)
        picked=[];rng=random.Random(21)
        for i in range(64):
            pick=select_slot(i,selected,filtered,self.cfg,picked,favorites,set(),set(),rng)
            self.assertIsNotNone(pick);picked.append(pick)
        self.assertEqual({s['id'] for s,r in picked},{'gb'})
        self.assertEqual(len({r for s,r in picked}),64)
        self.assertEqual(picked[0][1],roms[0])
        self.assertIsNone(select_slot(64,selected,filtered,self.cfg,picked,favorites,set(),set(),rng))

    def test_replacements_keep_hardware_and_inherit_cycle_options(self):
        system=dict(self.systems[2],cycle_seconds=200,independent_jitter_seconds=0)
        systems,catalogs=mode.scheduler_inputs(system,{'megadrive':[Path('a'),Path('b')]},64)
        self.assertEqual(duration_seconds(self.cfg,system=systems[0]),200)
        self.assertEqual(select_slot(3,systems,catalogs,self.cfg,[(systems[0],Path('a'))],[],set(),set())[1],Path('b'))
        self.assertIsNone(select_slot(3,systems,catalogs,self.cfg,[],[],set(),{'megadrive'}))
        self.assertIsNone(select_slot(3,systems,catalogs,self.cfg,[],[],{('megadrive','a'),('megadrive','b')},set()))

    def test_group_budgets_are_not_bypassed(self):
        system=dict(self.systems[0],resource_group='custom',resource_weight=1)
        systems,catalogs=mode.scheduler_inputs(system,{'gb':[Path('a'),Path('b')]},64)
        cfg={'resource_groups':{'custom':{'max_weight':1}}}
        self.assertIsNone(select_slot(1,systems,catalogs,cfg,[(systems[0],Path('a'))],[],set(),set()))

    def test_dense_display_cap_is_local_and_preserves_other_runtime_settings(self):
        cfg=dict(self.cfg,independent_max_fps=30,cycle_seconds=150,fade_enabled=True)
        before=copy.deepcopy(cfg)
        dense=mode.scheduler_config(cfg)
        self.assertEqual(dense['independent_max_fps'],25)
        self.assertTrue(dense['_single_system_rendering'])
        self.assertEqual(dense['cycle_seconds'],150)
        self.assertTrue(dense['fade_enabled'])
        self.assertEqual(cfg,before)
        self.assertEqual(mode.scheduler_config(dict(cfg,independent_max_fps=20))['independent_max_fps'],20)
        for value,expected in ((30,30),(24,24),(0,25),(False,25),('25',25),(float('nan'),25)):
            config=dict(cfg,single_system_mode=dict(cfg['single_system_mode'],max_fps=value))
            self.assertEqual(mode.scheduler_config(config)['independent_max_fps'],expected)


if __name__=='__main__':unittest.main()
