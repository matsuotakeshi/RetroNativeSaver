import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import supervisor_safety
from supervisor_safety import SupervisorSafety
import launch_options
import rom_list_policy as policy

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_supervisor_v092.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
def sup(source):return next(n for n in ast.parse(source).body if getattr(n,'name','')=='supervisor_main')
SAFETY_NAMES=('persistent_rom_state','persistent_whitelisted','session_quarantine','session_crash_counts','session_disabled_systems')

def node(name,old):
    body=ast.parse(OLD).body if old else sup(NEW).body
    return next(n for n in body if getattr(n,'name','')==name)


def call(fn):
    log=io.StringIO()
    with contextlib.redirect_stdout(log):
        try:value=fn();error=None
        except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
    return value,error,log.getvalue()

class SupervisorPreparationTests(unittest.TestCase):

    def test_config_path_precedence_and_read_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a.json';b=root/'b.json'
            (root/'config.json').write_text('{"value":0}',encoding='utf-8')
            a.write_text('{"value":1}',encoding='utf-8');b.write_text('{"value":2}',encoding='utf-8')
            for args in ([],['--config',str(a)],['--config='+str(a)],
                         ['--config',str(a),'--config='+str(b)],
                         ['--config='+str(a),'--config',str(b)],['--conf',str(b)]):
                worker=launch_options.parse_main_args(args,root)
                expected=json.loads(Path(worker.config).read_text(encoding='utf-8'))
                self.assertEqual(launch_options.load_supervisor_config(args,root),expected)
            b.write_text('{bad',encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                launch_options.load_supervisor_config(['--config',str(b)],root)
            with self.assertRaises(FileNotFoundError):
                launch_options.load_supervisor_config(['--config',str(root/'missing')],root)
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):launch_options.load_supervisor_config(['--config'],root)

    def safety(self,black=True,white=True,fail=None):
        results=[]
        for old in (True,False):
            events=[]
            def loadblack(path):
                events.append(('black',path))
                if fail=='black':raise OSError('black read')
                return {'systems':{'A':{'a.zip':{'blacklisted':True},'b.zip':{'blacklisted':True}}}}
            def loadwhite(path,seed):
                events.append(('white',path,seed))
                if fail=='white':raise OSError('white read')
                return {'systems':{'A':['a.zip']}}
            ns=dict(_empty_persistent_rom_state=lambda:{'systems':{}},_empty_persistent_rom_whitelist=lambda:{'systems':{}},
                    _load_persistent_rom_state=loadblack,_load_persistent_rom_whitelist=loadwhite,
                    _persistent_blacklisted_roms=policy._persistent_blacklisted_roms,_persistent_whitelisted_roms=policy._persistent_whitelisted_roms,
                    _apply_persistent_whitelist=policy._apply_persistent_whitelist,
                    persistent_rom_blacklist_enabled=black,persistent_rom_whitelist_enabled=white,
                    persistent_rom_blacklist_path='black.json',persistent_rom_whitelist_path='white.json',persistent_rom_whitelist_seed_path='seed.json',
                    persistent_rom_blacklist_threshold_sessions=2,persistent_session_id='test',session_rom_quarantine_enabled=True,session_system_crash_limit=3,
                    worker_run_hang_timeout_seconds=15.,worker_start_hang_timeout_seconds=45.,worker_watchdog_poll_seconds=.25)
            if old:
                exec(compile(ast.Module(body=[node('load_safety_state',True)],type_ignores=[]),'<safety>','exec'),ns)
                value,error,log=call(ns['load_safety_state'])
            else:
                safety=SupervisorSafety.__new__(SupervisorSafety)
                safety.__dict__.update({k:v for k,v in ns.items() if not k.startswith('_')})
                overrides={k:v for k,v in ns.items() if k.startswith('_')}
                with patch.multiple(supervisor_safety,**overrides):
                    value,error,log=call(safety.load)
            results.append((value,error,events,log))
        # Only the intentional v0.21.6 state split differs: persistent entries
        # are filtered by the worker for ordinary picks, not session quarantine.
        if results[0][0] is not None:
            legacy=list(results[0][0]);legacy[2]={}
            results[0]=(tuple(legacy),*results[0][1:])
        self.assertEqual(*results);return results[1]

    def test_safety_flags_and_whitelist_seed(self):
        for black in (False,True):
            for white in (False,True):
                value,error,events,_=self.safety(black,white);self.assertIsNone(error)
                self.assertEqual(value[2],{});self.assertEqual(value[3],{});self.assertEqual(value[4],set())
                self.assertEqual(len(events),int(black)+int(white))

    def test_safety_read_error_order(self):
        for fail in ('black','white'):
            value,error,events,log=self.safety(fail=fail);self.assertEqual(error[0],'OSError');self.assertEqual(log,'')
            self.assertEqual(len(events),1 if fail=='black' else 2)

    def launch(self,frozen,trace,quarantine,disabled):
        results=[]
        for old in (True,False):
            environ={'UNCHANGED':'value','TRACE':'inherited'}
            ns=dict(presentation_state=None,workspace=SimpleNamespace(apply=lambda env:None),launch_channel=None,config_snapshot=SimpleNamespace(apply=lambda env:None),sys=SimpleNamespace(executable='python.exe',frozen=frozen),raw_args=['/s','--config','日本語.json'],
                    os=SimpleNamespace(environ=environ,getpid=lambda:456),Path=Path,__file__=str(ROOT/'native_saver.py'),json=json,
                    persistent_session_id='session',runtime_trace_tag=trace,RUNTIME_TRACE_ENV='TRACE',SESSION_QUARANTINE_ENV='QUARANTINE',
                    SESSION_DISABLED_SYSTEMS_ENV='DISABLED',session_quarantine=copy.deepcopy(quarantine),session_disabled_systems=set(disabled))
            ns['safety']=SimpleNamespace(**ns)
            exec(compile(ast.Module(body=[node('prepare_worker_launch',old)],type_ignores=[]),'<launch>','exec'),ns)
            first=call(ns['prepare_worker_launch'])
            ns['session_quarantine']['next']={'new.rom'};ns['session_disabled_systems'].add('next')
            second=call(ns['prepare_worker_launch'])
            self.assertEqual(environ,{'UNCHANGED':'value','TRACE':'inherited'})
            results.append((first,second))
        self.assertEqual(*results);return results[1]

    def test_worker_commands_and_environment_refresh(self):
        for frozen in (False,True):
            for trace in (None,'tag'):
                first,second=self.launch(frozen,trace,{'日本語':{'b.zip','a.zip'},'empty':set()},{'Z','A'})
                cmd,env=first[0];self.assertEqual(cmd[:2],['python.exe','--worker'] if frozen else ['python.exe','-u'])
                self.assertEqual(json.loads(env['QUARANTINE']),{'日本語':['a.zip','b.zip']})
                self.assertEqual(json.loads(env['DISABLED']),['A','Z']);self.assertEqual(env['TRACE'],trace or 'inherited')
                self.assertIn('next',json.loads(second[0][1]['QUARANTINE']))

    def test_empty_worker_state_and_invalid_sort(self):
        first,_=self.launch(False,None,{},set());self.assertNotIn('passing state',first[2]);self.assertEqual(json.loads(first[0][1]['QUARANTINE']),{})
        first,_=self.launch(False,None,{'A':{'x',1}},set());self.assertEqual(first[1][0],'TypeError')

if __name__=='__main__':unittest.main()
