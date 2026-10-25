import ast
import contextlib
import copy
import datetime
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import rom_state_store
from runtime_policy import NATIVE_CRASH_CODES, persistent_failure


NAMES={'_persistent_entry_for_rom','_persistent_blacklisted_roms','_persistent_whitelisted_roms',
       '_rom_in_name_map','_apply_persistent_whitelist','_is_session_runtime_crash','_record_persistent_rom_failure'}


def load(path):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in NAMES]
    ns={}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
    return ns


def call(ns,name,*args):
    args=copy.deepcopy(args)
    log=io.StringIO()
    with contextlib.redirect_stdout(log):
        try: value=('ok',ns[name](*args))
        except Exception as exc: value=('error',type(exc).__name__,str(exc))
    return value,args,log.getvalue()


class RomPolicyCompatibilityTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).parent
        self.old=load(root/'tests_fixtures/legacy_rom_policy_v070.py')
        self.new=load(root/'native_saver.py')
        # Evidence arithmetic remains compatible; transactional merge has its own tests.
        self.new['_record_persistent_rom_failure']=rom_state_store._record_failure_in_state

    def compare(self,name,*args):
        a=call(self.old,name,*args); b=call(self.new,name,*args)
        self.assertEqual(a,b)
        return b

    def test_registration_lookup_partial_mutation_and_case_rules(self):
        states=[{}, {'systems':None}, {'systems':[]},
                {'systems':{'MAME':None}}, {'systems':{'MAME':{'Game.zip':None}}},
                {'systems':{'MAME':{'Game.zip':{'unknown':1},'game.zip':{'other':2}}}}]
        for state in states:
            for name in ('Game.zip','GAME.ZIP','other.zip','Straße.zip'):
                for create in (True,False):
                    self.compare('_persistent_entry_for_rom',state,'MAME',name,create)
        state={'systems':{'MAME':{'Game.zip':{'unknown':1}}}}
        _,entry=self.new['_persistent_entry_for_rom'](state,'MAME','GAME.ZIP',True)
        self.assertIs(entry,state['systems']['MAME']['Game.zip'])

    def test_blacklist_and_whitelist_shape_conversion(self):
        for systems in (None,[],{}, {'MAME':['Game.zip','',None,0,' ']},
                        {'MAME':{'a':{'blacklisted':True},'b':{'blacklisted':'false'},'c':None,'d':{}}},
                        {1:['Straße.zip','GAME.ZIP'], 'Other':None}):
            for name in ('_persistent_blacklisted_roms','_persistent_whitelisted_roms'):
                self.compare(name,{'systems':systems,'unknown':'keep'})
        for name in ('_persistent_blacklisted_roms','_persistent_whitelisted_roms'):
            self.compare(name,{})

    def test_membership_and_whitelist_override_preserve_first_bucket(self):
        maps=[{}, {'MAME':{'Game.zip','Straße.zip'}}, {'MAME':set(),'mame':{'Game.zip'}},
              {'MAME':None}, {None:[None,0]}, {'MAME':'game.zip'}]
        for mapping in maps:
            for system in ('MAME','mame',None):
                for rom in ('GAME.ZIP','STRASSE.ZIP',None):
                    self.compare('_rom_in_name_map',mapping,system,rom)
            self.compare('_apply_persistent_whitelist',{'mame':{'Game.zip','other.zip'},'PS2':{'x'}},mapping)
        self.assertFalse(self.new['_rom_in_name_map']({'MAME':set(),'mame':{'Game.zip'}},'mame','Game.zip'))

    def test_crash_classification_and_existing_path_differences(self):
        phases=['RUN_ENTER','RUN_EXCEPTION','START_ENTER','START_NATIVE_FAULT','SLOT_RUNNING',
                'WAIT_FRAME','START_FAILED','SLOT_COMPLETE','SHUTDOWN',' RUN_ENTER ',None,'']
        for phase in phases:
            for code in (0,75,76,1,-1073741819,0xC0000005,0xC000001D,0xC0000409,0xC0000374,None):
                self.compare('_is_session_runtime_crash',{'phase':phase},code,NATIVE_CRASH_CODES)
        for snapshot in (None,{},[],{'phase':[]}):
            self.compare('_is_session_runtime_crash',snapshot,0,NATIVE_CRASH_CODES)
        self.assertTrue(self.new['_is_session_runtime_crash']({'phase':'RUN_EXCEPTION'},1,NATIVE_CRASH_CODES))
        self.assertFalse(persistent_failure({'phase':'RUN_EXCEPTION'},1))

    def record_sequence(self,ns,initial,threshold,save_result):
        events=[]
        class Clock:
            @staticmethod
            def now(zone):
                events.append('clock')
                return datetime.datetime(2026,10,8,tzinfo=zone)
        def save(path,state):
            events.append(('save',path,copy.deepcopy(state)))
            return save_result
        ns['datetime']=SimpleNamespace(datetime=Clock,timezone=datetime.timezone)
        ns['_save_persistent_rom_state']=save
        state=copy.deepcopy(initial)
        results=[]
        for session,rom in [('s1','Game.zip'),('s1','GAME.ZIP'),('s2','game.zip'),('s3','Game.zip')]:
            try:
                with patch.object(rom_state_store, 'datetime', ns['datetime']), patch.object(rom_state_store, '_save_persistent_rom_state', save):
                    results.append(ns['_record_persistent_rom_failure'](state,'fake.json',session,threshold,'MAME',rom,'RUN_ENTER','crash'))
            except Exception as exc:
                results.append((type(exc).__name__,str(exc)))
        return state,results,events

    def test_session_evidence_threshold_timestamp_and_save_failure(self):
        for initial in ({}, {'version':1,'systems':{'MAME':{'Game.zip':{'failure_sessions':-3,'unknown':'keep'}}}},
                        {'systems':{'MAME':{'Game.zip':{'failure_sessions':'bad'}}}},
                        {'systems':{'MAME':{'Game.zip':{'failure_sessions':8,'blacklisted':True,'first_failure_utc':'earlier'}}}}):
            for threshold in (1,2,0,'bad'):
                for saved in (True,False):
                    self.assertEqual(self.record_sequence(self.old,initial,threshold,saved),
                                     self.record_sequence(self.new,initial,threshold,saved))
        state,results,events=self.record_sequence(self.new,{},2,False)
        self.assertEqual(results,[(1,False,False),(1,False,True),(2,True,False),(3,False,False)])
        self.assertEqual(sum(isinstance(e,tuple) and e[0]=='save' for e in events),3)
        self.assertTrue(state['systems']['MAME']['Game.zip']['blacklisted'])


if __name__=='__main__': unittest.main()
