import contextlib
import copy
import datetime
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import rom_state_store as current
from tests_fixtures import legacy_diagnostics_v083 as old


class Clock:
    @staticmethod
    def now(zone):return datetime.datetime(2026,10,9,12,34,56,tzinfo=zone)


class FailureRecordingTests(unittest.TestCase):
    def run_sequence(self,module,initial,fail=None):
        state=copy.deepcopy(initial); events=[]; outputs=[]
        def save(path,data):
            events.append(('save',str(path),copy.deepcopy(data)))
            if fail=='raise':raise OSError('save error')
            return fail!='false'
        clock=SimpleNamespace(datetime=Clock,timezone=datetime.timezone)
        with patch.object(module,'datetime',clock),patch.object(module,'_save_persistent_rom_state',save):
            for session,threshold in (('one',2),('one',2),('two',2),('three',2)):
                try:out=module._record_persistent_rom_failure(state,'state.json',session,threshold,'A','GAME.zip','RUN_ENTER','native')
                except Exception as exc:out=(type(exc).__name__,str(exc))
                outputs.append(copy.deepcopy(out))
        return state,events,outputs

    def test_mutation_save_failure_and_duplicate_sessions(self):
        for initial in ({},{'systems':{'A':{'game.zip':{'failure_sessions':-2}}}},
                        {'systems':{'A':{'GAME.zip':{'failure_sessions':'bad'}}}},
                        {'systems':None},{'systems':{'A':{'GAME.zip':{'failure_sessions':4,'blacklisted':True,'first_failure_utc':'before'}}}}):
            for fail in (None,'raise','false'):
                self.assertEqual(self.run_sequence(old,initial,fail),self.run_sequence(current,initial,fail))

    def test_exact_persisted_bytes_with_real_store(self):
        clock=SimpleNamespace(datetime=Clock,timezone=datetime.timezone)
        results=[]
        for module in (old,current):
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'state.json'; state={}; values=[]
                with patch.object(module,'datetime',clock):
                    for session in ('one','one','two'):
                        values.append(module._record_persistent_rom_failure(state,path,session,2,'機種','GAME.zip','RUN_ENTER','native'))
                results.append((values,state,path.read_bytes(),sorted(p.name for p in path.parent.iterdir())))
        self.assertEqual(*results)

    def test_actual_write_failure_preserves_memory_state_and_log(self):
        clock=SimpleNamespace(datetime=Clock,timezone=datetime.timezone); results=[]
        for module in (old,current):
            state={}; log=io.StringIO()
            with patch.object(module,'datetime',clock),patch.object(current,'_write_state_json',side_effect=PermissionError('blocked')),contextlib.redirect_stdout(log):
                value=module._record_persistent_rom_failure(state,Path('state.json'),'one',1,'A','game','RUN_ENTER','native')
            results.append((value,state,log.getvalue()))
        self.assertEqual(*results)
        self.assertTrue(results[1][1]['systems']['A']['game']['blacklisted'])

    def test_clock_failure_precedes_entry_field_updates(self):
        clock=SimpleNamespace(datetime=SimpleNamespace(now=lambda zone: (_ for _ in ()).throw(RuntimeError('clock'))),timezone=datetime.timezone)
        results=[]
        for module in (old,current):
            state={}
            with patch.object(module,'datetime',clock):
                try:value=module._record_persistent_rom_failure(state,None,'one',1,'A','g','RUN_ENTER','native')
                except Exception as exc:value=(type(exc).__name__,str(exc))
            results.append((value,state))
        self.assertEqual(*results)
