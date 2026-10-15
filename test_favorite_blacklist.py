import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import favorites
import independent_slots
import rom_list_policy
import rom_state_store
import saver_actions
import saver_controls
from fixed_rom_catalog import Catalogs
from runtime_catalogs import load_state
from slot_selection import choose_slots, initial_retry_candidates, normal_retry_candidate
from supervisor_safety import SupervisorSafety


class FavoriteBlacklistTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.system={'id':'a','name':'A','rom_dir':str(self.root),'extensions':['.rom'],
                     'resource_group':'heavy_cd','resource_weight':1,'max_concurrent':3}
        self.roms=[self.root/name for name in ('favorite.rom','other_blocked.rom','ordinary.rom')]
        for p in self.roms:p.touch()
        self.raw=Catalogs({'a':list(self.roms)}, {'hint':'unchanged'})
        self.black=self.root/'state/persistent_rom_blacklist.json'
        self.black.parent.mkdir()
        self.black.write_text(json.dumps({'systems':{'A':{
            p.name:{'blacklisted':True,'failure_sessions':4} for p in self.roms[:2]}}}),encoding='utf-8')
        self.favorite=self.root/'favorites.json'
        self.input={'delay_seconds':5,'device':'joypad','key':'Start'}
        self.favorite.write_text(json.dumps({'items':[{'system':'a','rom':str(self.roms[0]),'startup_input':self.input}]}),encoding='utf-8')
        self.cfg={'resource_groups':{'heavy_cd':{'max_weight':2}}}
        self.api=SimpleNamespace(resolve_app_relative_path=lambda value,default:self.root/(value or default))
        for module in (rom_list_policy,rom_state_store):
            for name in dir(module):
                if name.startswith('_') and callable(getattr(module,name)):
                    setattr(self.api,name,getattr(module,name))
        self.output=io.StringIO();self.redirect=contextlib.redirect_stdout(self.output);self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__,None,None,None)

    def load(self,cfg=None,raw=None,seed=False):
        return load_state(self.api,[self.system],self.raw if raw is None else raw,
                          self.cfg if cfg is None else cfg,whitelist_seed=seed)

    def matched(self,raw=None,failed=None):
        return favorites.load_cycle_favorites(self.favorite,[self.system],
            self.raw if raw is None else raw,set() if failed is None else failed)

    def select(self,index,ordinary,favorite,occupied=(),banned=(),suspended=(),raw=None):
        return independent_slots.select_slot(index,[self.system],ordinary,self.cfg,list(occupied),
            favorite,set(banned),set(suspended),favorite_catalogs=self.raw if raw is None else raw,
            normal_occupied=[])

    def test_preexisting_blacklist_is_bypassed_only_in_favorite_slot_both_modes(self):
        saved=self.black.read_bytes()
        _,_,_,ordinary=self.load()
        self.assertEqual(ordinary['a'],[self.roms[2]])
        self.assertIs(ordinary.canonical_paths,self.raw.canonical_paths)
        favorite=self.matched()
        self.assertEqual(favorite[0][0]['_favorite_startup_input'],self.input)
        first=self.select(0,ordinary,favorite)
        self.assertEqual(first[1],self.roms[0])
        second=self.select(1,ordinary,favorite,occupied=[first])
        self.assertEqual(second[1],self.roms[2])
        self.assertIsNone(self.select(2,ordinary,favorite,occupied=[first,second]))
        picks=choose_slots([self.system],ordinary,self.cfg,3,favorite)
        self.assertEqual([r for _,r in picks],[self.roms[0],self.roms[2]])
        self.assertEqual(self.black.read_bytes(),saved)

    def test_only_blacklisted_favorite_available_still_starts_both_modes(self):
        raw=Catalogs({'a':self.roms[:2]})
        _,_,_,ordinary=self.load(raw=raw)
        favorite=self.matched(raw)
        self.assertEqual(self.select(0,ordinary,favorite,raw=raw)[1],self.roms[0])
        self.assertIsNone(self.select(1,ordinary,favorite,raw=raw))
        self.assertEqual([r for _,r in choose_slots([self.system],ordinary,self.cfg,3,favorite)],[self.roms[0]])

    def test_disabled_or_removed_favorite_does_not_rescue_blacklist(self):
        _,_,_,ordinary=self.load()
        for data in ({'enabled':False,'items':[{'system':'a','rom':str(self.roms[0])}]},{'items':[]}):
            self.favorite.write_text(json.dumps(data),encoding='utf-8')
            favorite=self.matched()
            self.assertEqual(favorite,[])
            self.assertEqual(self.select(0,ordinary,favorite)[1],self.roms[2])
            self.assertTrue(all(r==self.roms[2] for _,r in choose_slots([self.system],ordinary,self.cfg,2,favorite)))

    def test_session_failure_and_suspended_system_still_exclude_favorite(self):
        _,_,_,ordinary=self.load()
        favorite=self.matched()
        self.assertEqual(self.select(0,ordinary,favorite,banned=[('a',str(self.roms[0]))])[1],self.roms[2])
        self.assertIsNone(self.select(0,ordinary,favorite,suspended=['A']))
        self.assertEqual(self.matched(failed={str(self.roms[0])}),[])
        from rom_catalog import build_catalogs
        with patch('rom_catalog.scan_roms',return_value=list(self.roms)):
            filtered=build_catalogs([self.system],{},True,{'A':{self.roms[0].name.casefold()}},lambda *a,**k:None)
        self.assertEqual(self.matched(filtered),[])
        self.assertNotIn(self.roms[0],filtered['a'])

    def test_disabled_system_and_missing_or_ambiguous_rom_are_not_resurrected(self):
        self.system['enabled']=False
        self.assertEqual(self.matched(),[])
        self.system['enabled']=True
        self.assertEqual(self.matched(Catalogs({'a':[self.roms[2]]})),[])
        self.favorite.write_text(json.dumps({'items':[{'system':'a','rom':self.roms[0].name}]}),encoding='utf-8')
        ambiguous=Catalogs({'a':[self.roms[0],self.root/'other'/self.roms[0].name]})
        self.assertEqual(self.matched(ambiguous),[])

    def test_favorite_retry_works_but_ordinary_fallback_stays_filtered(self):
        _,_,_,ordinary=self.load();favorite=self.matched()
        candidates,enabled=initial_retry_candidates(*favorite[0],[self.system],ordinary,set(),favorite)
        self.assertEqual(candidates,favorite)
        fallback=normal_retry_candidate(self.system,enabled,ordinary,{str(self.roms[0])},{},self.cfg)
        self.assertEqual(fallback[1],self.roms[2])

    def test_parent_restart_keeps_actual_failure_separate_from_persistent_entry(self):
        safety=SupervisorSafety(self.cfg,self.api.resolve_app_relative_path)
        safety.load()
        self.assertEqual(safety.session_quarantine,{})
        saver_actions.refresh_safety(safety)
        self.assertEqual(safety.session_quarantine,{})
        safety.record_runtime_failure({'system':'A','rom':self.roms[0].name,'phase':'RUN_ENTER'},False)
        saver_actions.refresh_safety(safety)
        self.assertEqual(safety.session_quarantine,{'A':{self.roms[0].name}})
        payload=json.dumps({k:sorted(v) for k,v in safety.session_quarantine.items()})
        quarantine,_=rom_list_policy.load_session_safety({'Q':payload},'Q','D')
        self.assertIn(self.roms[0].name.casefold(),quarantine['A'])
        new_session=SupervisorSafety(self.cfg,self.api.resolve_app_relative_path);new_session.load()
        self.assertEqual(new_session.session_quarantine,{})

    def test_ordinary_manual_delete_keeps_favorite_and_never_creates_session_failure(self):
        path,state,white,ordinary=self.load()
        favorite=self.matched();record=dict(ready=True,proc=Mock(poll=Mock(return_value=None)),pick=favorite[0])
        slots=[None,record];ui=saver_controls.Selection(slots,lambda:100.);ui.publish=Mock()
        ui.key(saver_controls.RIGHT);ui.key(saver_controls.DELETE)
        banned=set()
        saver_controls.process_actions(ui,slots,self.cfg,ordinary,self.favorite,path,state,white,
            self.api.resolve_app_relative_path,banned,lambda i:slots.__setitem__(i,None),[0.,0.],100.,
            favorite_catalogs=self.raw)
        self.assertFalse(banned);self.assertEqual(slots,[None,None])
        self.assertEqual(self.select(0,ordinary,self.matched())[1],self.roms[0])
        self.assertEqual(ordinary['a'],[self.roms[2]])
        self.assertEqual(self.matched()[0][0]['_favorite_startup_input'],self.input)
        self.assertFalse(saver_actions.add_favorite(self.favorite,self.system,self.roms[0],self.raw))

    def test_blacklist_flag_and_whitelist_seed_keep_ordinary_behavior(self):
        _,_,_,ordinary=self.load(cfg=dict(self.cfg,persistent_rom_blacklist_enabled=False))
        self.assertEqual(ordinary,self.raw)
        seed=self.root/'persistent_rom_whitelist.default.json'
        seed.write_text(json.dumps({'systems':{'A':[self.roms[0].name]}}),encoding='utf-8')
        _,_,_,ordinary=self.load(seed=True)
        self.assertEqual(ordinary['a'],[self.roms[0],self.roms[2]])
        _,_,_,ordinary=self.load(cfg=dict(self.cfg,persistent_rom_whitelist_enabled=False),seed=True)
        self.assertEqual(ordinary['a'],[self.roms[2]])


if __name__=='__main__':unittest.main()
