import ast
import contextlib
import copy
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import supervisor_safety
from supervisor_safety import SupervisorSafety
import runtime_policy
from rom_list_policy import _rom_in_name_map

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_supervisor_v091.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
def supervisor(text):return next(n for n in ast.parse(text).body if getattr(n,'name','')=='supervisor_main')
def legacy_classifier():
    node=next(n for n in ast.parse(OLD).body if getattr(n,'name','')=='classify')
    ns={'_is_session_runtime_crash':runtime_policy._is_session_runtime_crash}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<legacy classification>','exec'),ns)
    return ns['classify']

def record_node(old):
    return next(n for n in ast.parse(OLD).body if getattr(n,'name','')=='record_runtime_failure')


class SupervisorFailureTests(unittest.TestCase):

    def test_classification_matrix(self):
        old=legacy_classifier()
        phases=('', 'RUN_ENTER','RUN_EXCEPTION','START_ENTER','START_FAILED','START_NATIVE_FAULT','SLOT_RUNNING','WAIT_FRAME','SLOT_COMPLETE','RUN_ENTER ')
        for phase in phases:
            for code in (0,75,76,1,0xC0000005,0xC000001D,0xC0000409,0xC0000374):
                for watchdog in (False,True):
                    snap={'phase':phase};self.assertEqual(old(snap,code,watchdog,runtime_policy.NATIVE_CRASH_CODES),runtime_policy.worker_runtime_failure(snap,code,watchdog,runtime_policy.NATIVE_CRASH_CODES))
        for snap in (None,{}, {'phase':None}):
            for watchdog in (False,True):
                self.assertEqual(old(snap,0,watchdog,set()),runtime_policy.worker_runtime_failure(snap,0,watchdog,set()))

    def compare(self,sequence,options=None,reply=(1,False,False),fail=False):
        results=[]
        for old in (True,False):
            ns=dict(session_crash_counts={},session_quarantine={},session_disabled_systems=set(),session_system_crash_limit=3,
                    session_rom_quarantine_enabled=True,persistent_rom_whitelist_enabled=True,persistent_whitelisted={},
                    persistent_rom_blacklist_enabled=True,persistent_rom_state={},persistent_rom_blacklist_path='state.json',
                    persistent_session_id='session',persistent_rom_blacklist_threshold_sessions=2,_rom_in_name_map=_rom_in_name_map)
            ns.update(copy.deepcopy(options or {}));calls=[]
            def save(state,*args):
                calls.append(copy.deepcopy(args))
                if fail:raise OSError('write failure')
                state['last']=args;return reply
            ns['_record_persistent_rom_failure']=save
            if old:
                exec(compile(ast.Module(body=[record_node(True)],type_ignores=[]),'<record failure>','exec'),ns)
                record=ns['record_runtime_failure']
            else:
                safety=SupervisorSafety.__new__(SupervisorSafety)
                safety.__dict__.update(ns)
                record=safety.record_runtime_failure
            log=io.StringIO();errors=[]
            with contextlib.redirect_stdout(log), patch.object(supervisor_safety, "_record_persistent_rom_failure", save):
                for snapshot,watchdog in sequence:
                    try:record(snapshot,watchdog);errors.append(None)
                    except Exception as exc:errors.append((type(exc).__name__,str(exc)))
            states={name:ns[name] for name in ('session_crash_counts','session_quarantine','session_disabled_systems','persistent_rom_state')}
            results.append((states,calls,errors,log.getvalue()))
        self.assertEqual(*results);return results[1]

    def test_repeated_failure_quarantine_and_suspend(self):
        snap={'system':' A ','rom':' game.zip ','phase':' RUN_ENTER '}
        r=self.compare([(snap,False)]*4)
        self.assertEqual(r[0]['session_crash_counts'],{'A':4});self.assertEqual(r[0]['session_quarantine'],{'A':{'game.zip'}})
        self.assertEqual(r[0]['session_disabled_systems'],{'A'});self.assertEqual(r[3].count('SYSTEM SUSPENDED'),1)
        self.assertEqual(r[3].count('ROM quarantined'),1)

    def test_whitelist_protects_evidence_but_not_session(self):
        r=self.compare([({'system':'A','rom':'game.zip','phase':'RUN_ENTER'},False)],{'persistent_whitelisted':{'a':{'GAME.ZIP'}}})
        self.assertEqual(r[1],[]);self.assertEqual(r[0]['session_quarantine'],{'A':{'game.zip'}})
        self.assertIn('WHITELIST protects',r[3])

    def test_config_flags_missing_names_and_hang(self):
        for quarantine in (False,True):
            for black in (False,True):
                for white in (False,True):
                    for snap in ({},{'system':'A'},{'system':'','rom':'x'},{'system':'A','rom':'x','phase':'START_ENTER'}):
                        self.compare([(snap,True)],dict(session_rom_quarantine_enabled=quarantine,persistent_rom_blacklist_enabled=black,persistent_rom_whitelist_enabled=white,persistent_whitelisted={'A':{'x'}}))

    def test_evidence_result_logs(self):
        for reply in ((1,False,False),(2,True,False),(2,False,True),(2,True,True)):
            self.compare([({'system':'A','rom':'x','phase':'RUN_ENTER'},False)],reply=reply)

    def test_record_failure_keeps_partial_state(self):
        r=self.compare([({'system':'A','rom':'x','phase':'RUN_ENTER'},False)],{'session_system_crash_limit':1},fail=True)
        self.assertEqual(r[2],[('OSError','write failure')]);self.assertEqual(r[0]['session_crash_counts'],{'A':1})
        self.assertEqual(r[0]['session_quarantine'],{'A':{'x'}});self.assertEqual(r[0]['session_disabled_systems'],set())

if __name__=='__main__':unittest.main()
