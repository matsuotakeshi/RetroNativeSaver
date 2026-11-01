"""Grouped presentation policy, distinct from the normal resource budgets."""
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock

import single_system_mode as mode
from config_snapshot import ConfigSnapshot, load_worker_config
from favorites import favorite_candidates
from fixed_rom_catalog import Catalogs, signature
from independent_slots import duration_seconds, select_slot
from launch_options import parse_main_args


class GroupedModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'systems').mkdir();(self.root/'roms').mkdir()
        (self.root/'core.dll').touch()
        self.systems=[dict(id=sid,name=sid,enabled=True,core=str(self.root/'core.dll'),
            rom_dir=str(self.root/'roms'),render_backend='software',max_concurrent=1)
            for sid in mode.SUPPORTED]
        self.save_systems()
        self.cfg=dict(independent_slots_enabled=True,fullscreen=True,independent_max_fps=30,
            cycle_seconds=150,independent_jitter_seconds=15,resource_groups={'heavy_cd':{'max_weight':7}},
            single_system_mode=dict(enabled=True,normal_weight=50,grouped_weight=50,
                groups=[list(g) for g in mode.DEFAULT_GROUPS],max_fps=25,
                resource_groups={'heavy_cd':{'max_weight':64}}))
        self.args=parse_main_args([],self.root)
        self.rng=Mock();self.rng.random.return_value=.1
        self.rng.choice.side_effect=lambda groups:groups[0]

    def save_systems(self):
        for s in self.systems:
            (self.root/'systems'/f'{s["id"]}.json').write_text(json.dumps(s))

    def choose(self,cfg=None,args=None):
        return mode.prepare_session(cfg or self.cfg,self.root,args or self.args,'screen',rng=self.rng)

    def test_requested_eight_groups_are_uniform_group_candidates(self):
        before=copy.deepcopy(self.cfg)
        self.assertEqual(self.choose()[mode.SESSION_KEY],['megadrive','megacd'])
        self.assertEqual(self.rng.choice.call_args.args[0],[list(g) for g in mode.DEFAULT_GROUPS])
        self.assertEqual(len(self.rng.choice.call_args.args[0]),8)
        self.assertEqual(self.cfg,before)

    def test_nec_group_includes_pcfx_with_alias_pause_and_explicit_config_preserved(self):
        group=['pcengine','pcenginecd','pcfx']
        self.assertIn(group,mode.configured_groups({}))
        self.rng.choice.side_effect=lambda groups:next(g for g in groups if 'pcengine' in g)
        self.assertEqual(self.choose()[mode.SESSION_KEY],group)
        self.assertEqual(mode.configured_groups({'groups':[['pcengine','cdrom2','pcfx']]}),[group])
        # Existing explicit groups are not silently expanded on other installations.
        self.assertEqual(mode.configured_groups({'groups':[group[:2]]}),[group[:2]])
        self.cfg['single_system_mode']['disabled_systems']=['pcfx']
        self.assertEqual(self.choose()[mode.SESSION_KEY],group[:2])
        self.cfg['single_system_mode']['disabled_systems']=[]
        next(s for s in self.systems if s['id']=='pcfx')['enabled']=False
        self.save_systems()
        self.assertEqual(self.choose()[mode.SESSION_KEY],group[:2])

    def test_nec_group_uses_existing_pcfx_settings_and_group_resource_budget(self):
        group=['pcengine','pcenginecd','pcfx']
        selected=[json.loads((Path(__file__).parent/'systems.example'/f'{sid}.json').read_text(encoding='utf-8')) for sid in group]
        before=copy.deepcopy(selected)
        catalogs=Catalogs({sid:[Path(f'{sid}_{i}.chd') for i in range(80)] for sid in group})
        systems,catalogs=mode.scheduler_inputs(selected,catalogs,64)
        self.assertEqual(selected,before)
        pcfx=next(s for s in systems if s['id']=='pcfx')
        original=next(s for s in before if s['id']=='pcfx')
        self.assertEqual(pcfx,dict(original,max_concurrent=64))
        self.assertEqual((pcfx['resource_group'],pcfx['resource_weight']),('heavy_cd',1))
        self.assertNotIn('startup_input',pcfx)
        self.assertEqual(signature(pcfx),signature(original))
        cfg=mode.scheduler_config(self.cfg)
        self.assertEqual(cfg['resource_groups']['heavy_cd']['max_weight'],64)
        self.assertEqual(self.cfg['resource_groups']['heavy_cd']['max_weight'],7)
        picked=[];rng=random.Random(23)
        for index in range(64):
            pick=select_slot(index,systems,catalogs,cfg,picked,[],set(),set(),rng)
            self.assertIsNotNone(pick);picked.append(pick)
        self.assertEqual({s['id'] for s,r in picked},set(group))
        replacement=select_slot(3,systems,catalogs,cfg,picked[:3]+picked[4:],[],set(),set(),rng)
        self.assertIn(replacement[0]['id'],group)

    def test_computer_group_is_one_candidate_and_respects_existing_lists_and_pause(self):
        group=['msx','x1','x68000','pc88','pc98']
        self.assertIn(group,mode.configured_groups({}))
        self.cfg['single_system_mode'].update(normal_weight=15,grouped_weight=85,disabled_systems=['fbneo'])
        self.rng.choice.side_effect=lambda groups:next(g for g in groups if 'msx' in g)
        cfg=self.choose()
        self.assertEqual(cfg[mode.SESSION_KEY],group)
        self.assertEqual(len(self.rng.choice.call_args.args[0]),7)
        self.assertAlmostEqual(mode.presentation_probability(self.cfg['single_system_mode']),.85)
        snapshot=ConfigSnapshot(cfg)
        try:
            env={};snapshot.apply(env)
            worker=load_worker_config(self.root/'absent',env)
            self.assertEqual(mode.prepare_session(worker,self.root,self.args,'screen',reuse=True)[mode.SESSION_KEY],group)
        finally:snapshot.close()
        self.cfg['single_system_mode']['disabled_systems'].append('pc98')
        self.assertEqual(self.choose()[mode.SESSION_KEY],group[:-1])
        self.assertEqual(mode.configured_groups({'groups':[['msx']]}),[['msx']])
        self.assertEqual(mode.configured_groups({'systems':['msx','x1','pc98']}),[['msx'],['x1'],['pc98']])
        next(s for s in self.systems if s['id']=='x1')['enabled']=False
        self.save_systems()
        self.assertEqual(self.choose()[mode.SESSION_KEY],['msx','x68000','pc88'])

    def test_computer_tiles_keep_machine_settings_and_favorite_input(self):
        group=['msx','x1','x68000','pc88','pc98']
        selected=[json.loads((Path(__file__).parent/'systems'/f'{sid}.json').read_text(encoding='utf-8-sig')) for sid in group]
        before=copy.deepcopy(selected)
        catalogs=Catalogs({sid:[Path(f'{sid}_{i}.rom') for i in range(80)] for sid in group})
        systems,catalogs=mode.scheduler_inputs(selected,catalogs,64)
        self.assertEqual(selected,before)
        for system,original in zip(systems,before):
            self.assertEqual(system,dict(original,max_concurrent=64))
            self.assertEqual(signature(system),signature(original))
        self.assertEqual(len(mode.monitor_slots([(0,0,1920,1080),(1920,0,4480,1080)],0,0,systems=systems)),64)
        auto_input=dict(delay_seconds=5,device='keyboard',key='Space')
        favorites=favorite_candidates(systems,catalogs,{'items':[
            dict(system='pc88',rom='pc88_0.rom',startup_input=auto_input),
            dict(system='gb',rom='gb_0.rom')]},log=lambda s:None)
        picked=[];rng=random.Random(19);cfg=mode.scheduler_config(self.cfg)
        for index in range(64):
            pick=select_slot(index,systems,catalogs,cfg,picked,favorites,set(),set(),rng)
            self.assertIsNotNone(pick);picked.append(pick)
        self.assertEqual({s['id'] for s,r in picked},set(group))
        self.assertEqual(picked[0][0]['id'],'pc88')
        self.assertEqual(picked[0][0]['_favorite_startup_input'],auto_input)
        replacement=select_slot(3,systems,catalogs,cfg,picked[:3]+picked[4:],favorites,set(),set(),rng)
        self.assertIn(replacement[0]['id'],group)

    def test_group_pause_excludes_fbneo_and_empty_list_restores_without_changing_weights(self):
        self.cfg['single_system_mode'].update(disabled_systems=['fbneo'],normal_weight=40,grouped_weight=60)
        before=copy.deepcopy(self.cfg)
        self.choose()
        candidates=self.rng.choice.call_args.args[0]
        self.assertEqual(candidates,[list(g) for g in mode.DEFAULT_GROUPS if g!=('fbneo',)])
        self.assertEqual(self.cfg,before)
        self.assertAlmostEqual(mode.presentation_probability(self.cfg['single_system_mode']),.6)
        self.cfg['single_system_mode']['disabled_systems']=[]
        self.choose();self.assertIn(['fbneo'],self.rng.choice.call_args.args[0])

    def test_pause_applies_to_legacy_lists_and_aliases_and_preserves_other_members(self):
        self.assertEqual(mode.configured_groups({'systems':['fbneo','gb'],'disabled_systems':['fbneo']}),[['gb']])
        self.assertEqual(mode.configured_groups({'groups':[['pcengine','pcenginecd']],
            'disabled_systems':['cdrom2']}),[['pcengine']])
        self.assertEqual(mode.configured_groups({'groups':[['pcengine','cdrom2']],
            'disabled_systems':['pcenginecd']}),[['pcengine']])
        for value in (None,'fbneo',{},[{}],['unknown'],[True]):
            cfg=copy.deepcopy(self.cfg);cfg['single_system_mode']['disabled_systems']=value
            self.assertIsNone(self.choose(cfg).get(mode.SESSION_KEY))

    def test_pause_does_not_disable_normal_mode_and_explicit_grouped_launch_cannot_bypass(self):
        self.cfg['single_system_mode']['disabled_systems']=['fbneo']
        args=parse_main_args(['--presentation','normal','--system','fbneo'],self.root)
        result=self.choose(args=args)
        self.assertNotIn(mode.SESSION_KEY,result)
        self.rng.random.assert_not_called();self.rng.choice.assert_not_called()
        self.assertTrue(next(s for s in self.systems if s['id']=='fbneo')['enabled'])
        args=parse_main_args(['--presentation','single-system','--system','fbneo'],self.root)
        self.assertIsNone(self.choose(args=args)[mode.SESSION_KEY])
        self.cfg['single_system_mode']['groups']=[['fbneo']]
        self.assertIsNone(self.choose()[mode.SESSION_KEY])

    def test_relative_weights_endpoints_and_old_probability(self):
        for normal,grouped,expected in ((50,50,.5),(70,30,.3),(1,3,.75),(0,1,1),(1,0,0),(1e308,1e308,.5)):
            self.assertAlmostEqual(mode.presentation_probability(dict(normal_weight=normal,grouped_weight=grouped)),expected)
        self.assertEqual(mode.presentation_probability({'probability':.2}),.2)
        self.assertEqual(mode.presentation_probability(dict(normal_weight=1,grouped_weight=3,probability=.1)),.75)
        for value in ({'normal_weight':0,'grouped_weight':0},{'normal_weight':1},
                      {'normal_weight':True,'grouped_weight':1},{'normal_weight':-1,'grouped_weight':1},
                      {'normal_weight':1,'grouped_weight':float('inf')},
                      {'normal_weight':'50','grouped_weight':50}):
            with self.assertRaises(ValueError):mode.presentation_probability(value)
        for draw,expected in ((.699,True),(.7,False),(.999,False)):
            self.rng.random.return_value=draw
            self.cfg['single_system_mode'].update(normal_weight=30,grouped_weight=70)
            self.assertEqual(self.choose()[mode.SESSION_KEY] is not None,expected)

    def test_groups_aliases_legacy_and_invalid_values(self):
        self.assertEqual(mode.configured_groups({'groups':[['pcengine','cdrom2']]}),[['pcengine','pcenginecd']])
        self.assertEqual(mode.configured_groups({'systems':['gb','gbc']}),[['gb'],['gbc']])
        self.assertEqual(mode.configured_groups({'groups':[['gb','gb'],['gb']]}),[['gb']])
        for groups in (None,{},['gb'],[[]],[['ps2']],[[{}]],[[True]]):
            cfg=copy.deepcopy(self.cfg);cfg['single_system_mode']['groups']=groups
            self.assertIsNone(self.choose(cfg).get(mode.SESSION_KEY))

    def test_unavailable_members_filtered_without_disabling_entire_group(self):
        for s in self.systems:
            if s['id'] in ('megacd','snes'):s['enabled']=False
            if s['id']=='fbneo':s['core']=str(self.root/'missing.dll')
        self.save_systems();self.choose()
        groups=self.rng.choice.call_args.args[0]
        self.assertEqual(groups[0],['megadrive'])
        self.assertNotIn(['snes'],groups);self.assertNotIn(['fbneo'],groups)
        for s in self.systems:s['enabled']=False
        self.save_systems();self.assertIsNone(self.choose()[mode.SESSION_KEY])

    def test_snapshot_freezes_members_and_remaining_members_survive_suspension(self):
        cfg=self.choose();snapshot=ConfigSnapshot(cfg)
        try:
            env={};snapshot.apply(env)
            for _ in range(2):
                loaded=load_worker_config(self.root/'absent',env)
                self.assertIs(mode.prepare_session(loaded,self.root,self.args,'screen',reuse=True,rng=self.rng),loaded)
                self.assertEqual(loaded[mode.SESSION_KEY],['megadrive','megacd'])
        finally:snapshot.close()
        catalogs={sid:[Path(sid+'.rom')] for sid in mode.SUPPORTED}
        for s in self.systems:
            if s['id']=='megacd':s['enabled']=False
        self.assertEqual([s['id'] for s in mode.selected_systems(cfg,self.systems,catalogs)],['megadrive'])
        del catalogs['megadrive']
        with self.assertRaises(RuntimeError):mode.selected_systems(cfg,self.systems,catalogs)

    def test_group_covers_64_slots_favorites_and_replacement_without_other_hardware(self):
        selected=[dict(s,cycle_seconds=180,independent_jitter_seconds=0) for s in self.systems if s['id'] in ('megadrive','megacd')]
        before=copy.deepcopy(selected)
        original=Catalogs({sid:[Path(f'{sid}_{i}.rom') for i in range(100)] for sid in mode.SUPPORTED},{'a':'a'})
        systems,catalogs=mode.scheduler_inputs(selected,original,64)
        self.assertIs(catalogs.canonical_paths,original.canonical_paths)
        self.assertEqual(selected,before)
        self.assertEqual([signature(s) for s in systems],[signature(s) for s in selected])
        favorites=favorite_candidates(systems,catalogs,{'items':[
            {'system':'megacd','rom':'megacd_0.rom'},{'system':'gb','rom':'gb_0.rom'}]},log=lambda s:None)
        rng=random.Random(16);picked=[]
        for i in range(64):
            pick=select_slot(i,systems,catalogs,self.cfg,picked,favorites,set(),set(),rng)
            self.assertIsNotNone(pick);picked.append(pick)
        self.assertEqual(picked[0][0]['id'],'megacd')
        self.assertEqual({s['id'] for s,r in picked},{'megadrive','megacd'})
        self.assertEqual(len({str(r) for s,r in picked}),64)
        self.assertEqual(duration_seconds(self.cfg,system=systems[0]),180)
        replacement=select_slot(3,systems,catalogs,self.cfg,picked[:3]+picked[4:],favorites,set(),set(),rng)
        self.assertIn(replacement[0]['id'],('megadrive','megacd'))

    def test_dense_resource_override_local_normal_seven_dense_sixty_four(self):
        before=copy.deepcopy(self.cfg);cfg=mode.scheduler_config(self.cfg)
        self.assertEqual(self.cfg,before)
        system=dict(self.systems[-1],resource_group='heavy_cd',resource_weight=1)
        systems,catalogs=mode.scheduler_inputs([system],{system['id']:[Path(str(i)) for i in range(65)]},64)
        occupied=[(systems[0],Path(str(i))) for i in range(7)]
        self.assertIsNone(select_slot(7,systems,catalogs,self.cfg,occupied,[],set(),set()))
        for i in range(7,64):
            pick=select_slot(i,systems,catalogs,cfg,occupied,[],set(),set())
            self.assertIsNotNone(pick);occupied.append(pick)
        # Weight limits still apply to heavier members even with capacity left.
        systems[0]['resource_weight']=2
        self.assertIsNone(select_slot(32,systems,catalogs,cfg,occupied[:32],[],set(),set()))
        cfg['resource_groups']['heavy_cd']['max_weight']=99
        self.assertEqual(self.cfg,before)

    def test_bad_override_fails_explicitly_without_removing_normal_limits(self):
        for value in (None,[],{'heavy_cd':{}},{'heavy_cd':{'max_weight':0}},
                      {'heavy_cd':{'max_weight':True}},{'heavy_cd':{'max_weight':'64'}}):
            cfg=copy.deepcopy(self.cfg);cfg['single_system_mode']['resource_groups']=value
            with self.assertRaises(ValueError):mode.scheduler_config(cfg)
            self.assertEqual(cfg['resource_groups']['heavy_cd']['max_weight'],7)

    def test_fbneo_uses_common_64_tile_layout_and_explicit_rows(self):
        from tile_layout import plan
        system=next(s for s in self.systems if s['id']=='fbneo')
        monitors=[(-1920,-1080,0,0),(0,0,2560,1080)]
        rects=mode.monitor_slots(monitors,-1920,-1080,systems=[system])
        self.assertEqual(len(rects),64)
        for cells,x0,y0,width,cols in ((rects[:28],0,0,1920,7),(rects[28:],1920,1080,2560,9)):
            self.assertEqual(sum(w*h for x,y,w,h in cells),width*1080)
            self.assertEqual({x for x,y,w,h in cells},{x0+width*i//cols for i in range(cols)})
            self.assertEqual({y for x,y,w,h in cells},{y0+1080*i//4 for i in range(4)})
        self.assertEqual(set(mode.monitor_slots(list(reversed(monitors)),-1920,-1080,systems=[system])),set(rects))
        self.assertEqual(len(mode.monitor_slots(monitors[:1],-1920,-1080,systems=[system])),28)
        self.assertIsNone(mode.monitor_slots(monitors+[monitors[0]],-1920,-1080,systems=[system]))
        self.assertEqual(plan(monitors,(-1920,-1080),4,limit=mode.tile_limit([system]))[1],rects)
        for group in mode.DEFAULT_GROUPS:
            selected=[s for s in self.systems if s['id'] in group]
            self.assertEqual(len(mode.monitor_slots(monitors,-1920,-1080,systems=selected)),64)

    def test_fbneo_64_capacity_keeps_resource_budget_and_source_settings(self):
        system=next(s for s in self.systems if s['id']=='fbneo')
        system.update(resource_group='heavy_cd',resource_weight=1)
        before=copy.deepcopy(system)
        catalogs={'fbneo':[Path(f'{i}.zip') for i in range(65)]}
        selected,filtered=mode.scheduler_inputs([system],catalogs,64)
        self.assertEqual(selected[0]['max_concurrent'],64)
        self.assertEqual(system,before)
        with self.assertRaises(ValueError):mode.scheduler_inputs([system],catalogs,65)
        cfg=mode.scheduler_config(self.cfg)
        occupied=[]
        for i in range(64):
            pick=select_slot(i,selected,filtered,cfg,occupied,[],set(),set(),rng=random.Random(i))
            self.assertIsNotNone(pick)
            occupied.append(pick)
        self.assertIsNone(select_slot(64,selected,filtered,cfg,occupied,[],set(),set()))
        # A smaller grouped resource budget still prevents extra instances.
        cfg['resource_groups']['heavy_cd']['max_weight']=32
        self.assertIsNone(select_slot(32,selected,filtered,cfg,occupied[:32],[],set(),set()))
        self.assertEqual(self.cfg['resource_groups']['heavy_cd']['max_weight'],7)
        selected[0]['resource_weight']=2
        cfg['resource_groups']['heavy_cd']['max_weight']=64
        self.assertIsNone(select_slot(32,selected,filtered,cfg,occupied[:32],[],set(),set()))
        neo=next(s for s in self.systems if s['id']=='neocd')
        selected,_=mode.scheduler_inputs([system,neo],dict(catalogs,neocd=[Path('a.chd')]),64)
        self.assertEqual([s['max_concurrent'] for s in selected],[64,64])
        self.assertEqual(system,before)


if __name__=='__main__':unittest.main()
