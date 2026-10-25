import ast
import re
import contextlib
import copy
import io
import json
from pathlib import Path
import random
import shutil
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import independent_slots as current

ROOT=Path(__file__).parent
LEGACY=(ROOT/'tests_fixtures/legacy_scheduler_v089.py').read_text(encoding='utf-8')

def old_module():
    m=ModuleType('legacy_scheduler');exec(compile(LEGACY,'<legacy scheduler>','exec'),m.__dict__);return m


class SchedulerBoundaryTests(unittest.TestCase):

    def scenario(self,mode='normal',black=True,white=True,frozen=False):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);folder=base/'scheduler';fav=base/'favorites.json'
            # Compare unchanged ordinary blacklist behavior here. The new
            # favorite override has integration coverage in test_favorite_blacklist.
            fav.write_text(json.dumps({'enabled':not (black and not white),
                'items':[{'system':'a','rom':'a.zip'}]}),encoding='utf-8')
            system=dict(id='a',name='A',max_concurrent=2,resource_group='heavy_cd',resource_weight=1)
            systems=[system];catalogs={'a':[Path('a.zip'),Path('b.zip')]}
            # Explicit serial mode preserves the pre-parallel scheduler contract.
            cfg={'independent_startup_parallelism':1,'cycle_seconds':180,'persistent_rom_blacklist_enabled':black,'persistent_rom_whitelist_enabled':white,'resource_groups':{'heavy_cd':{'max_weight':1}}}
            results=[]
            for module in (old_module(),current):
                events=[];specs=[];procs=[];clock=[100.];rng=random.Random(90)
                class Window:
                    hwnd=123;fullscreen=True;should_close=False;exit_reason='test';power_idle=False;pumps=0
                    def begin_composite(self):events.append(('begin',))
                    def present(self):events.append(('closed_present' if self.should_close else 'present',))
                    def _note_exit(self,*args):events.append(('note',args))
                    def pump(self):
                        self.pumps+=1;events.append(('pump',self.pumps))
                        if mode=='standby' and self.pumps==2:self.power_idle=True
                        if self.pumps>=4:self.should_close=True
                win=Window()
                class Proc:
                    pid=456
                    def __init__(self):self.killed=False
                    def poll(self):
                        events.append(('poll',))
                        if self.killed:return -1
                        if win.pumps>=2 and mode in ('complete','crash','user'):return {'complete':75,'crash':0xC0000005,'user':0}[mode]
                        return None
                    def kill(self):events.append(('kill',));self.killed=True
                    def wait(self,timeout):events.append(('wait',timeout));return 0
                class Trace:
                    def close(self):events.append(('trace_close',))
                class Temp:
                    def __init__(self,**kw):
                        if kw.get('dir', 'absent') is None: kw.pop('dir')  # Parent ownership tested separately.
                        events.append(('temp',kw));folder.mkdir();self.name=str(folder)
                    def cleanup(self):events.append(('cleanup',));shutil.rmtree(folder)
                def popen(cmd,env):
                    events.append(('popen',cmd,env));specs.append(json.loads(Path(cmd[-1]).read_text(encoding='utf-8')))
                    self.assertFalse(Path(specs[-1]['gate']).exists())
                    if mode=='popen_error':raise OSError('popen test')
                    proc=Proc();procs.append(proc);return proc
                def assign(job,proc):
                    events.append(('assign',job));self.assertFalse(Path(specs[-1]['gate']).exists());return mode!='assign_error'
                def snapshot(trace):
                    events.append(('snapshot',));self.assertTrue((folder/'gate_0').exists())
                    phase={'complete':'SLOT_COMPLETE','crash':'RUN_ENTER','user':'SLOT_USER_EXIT'}.get(mode,'SLOT_RUNNING')
                    return {'phase':phase,'raw':'same'}
                def tick():clock[0]+=.1;return clock[0]
                def sleep(t):events.append(('sleep',t));clock[0]+=100 if mode=='hang' else t
                def resolve(value,default):events.append(('path',value,default));return base/default
                def contains(mapping,name,rom):return rom in mapping.get(name,[])
                def loadstate(path):events.append(('state',str(path)));return {'A':['a.zip']}
                def loadwhite(path):events.append(('white',str(path)));return {'A':['a.zip']}
                def effective(state,white):return ({k:[r for r in v if not contains(white,k,r)] for k,v in state.items()},None)
                def title(*args):
                    events.append(('title',args[0]['id'],str(args[1])))
                    if mode=='title_error':raise ValueError('title test')
                    return '日本語 title'
                api=SimpleNamespace(__file__=str(base/'native_saver.py'),RUNTIME_TRACE_SIZE=4096,RUNTIME_TRACE_ENV='TRACE',
                    resolve_app_relative_path=resolve,_load_persistent_rom_state=loadstate,
                    _load_persistent_rom_whitelist=loadwhite,_persistent_whitelisted_roms=lambda s:s,
                    _persistent_blacklisted_roms=lambda s:s,_apply_persistent_whitelist=effective,_rom_in_name_map=contains,
                    _create_worker_job_object=lambda:9,_assign_worker_to_job=assign,
                    kernel32=SimpleNamespace(CloseHandle=lambda job:events.append(('close_job',job)) or True),
                    read_runtime_trace=snapshot,write_runtime_trace=lambda *a,**kw:events.append(('trace',a,kw)),
                    resolve_display_title=title,_record_persistent_rom_failure=lambda *a:events.append(('durable',a)))
                original_select=module.select_slot
                def select(*args,**kw):
                    events.append(('select',copy.deepcopy(args[2]),copy.deepcopy(args[5]),set(args[6]),set(args[7])))
                    return original_select(*args,**kw,rng=rng)
                fakeos=SimpleNamespace(environ={'BASE':'kept'},getpid=lambda:1234)
                kwargs=dict(os=fakeos,sys=SimpleNamespace(executable='python.exe',frozen=frozen),
                  time=SimpleNamespace(monotonic=tick,monotonic_ns=lambda:123456,sleep=sleep),
                  tempfile=SimpleNamespace(TemporaryDirectory=Temp),mmap=SimpleNamespace(mmap=lambda *a,**kw:Trace()),
                  subprocess=SimpleNamespace(Popen=popen),select_slot=select,duration_seconds=lambda cfg, **kw:module.duration_seconds_original(cfg,rng,**kw))
                # Preserve the original implementation before replacing its entry point.
                module.duration_seconds_original=module.duration_seconds
                log=io.StringIO()
                with patch.multiple(module,**kwargs),contextlib.redirect_stdout(log):
                    try:value=module.run_scheduler(api,win,[(0,0,320,240),(320,0,320,240)],systems,catalogs,cfg,fav,{}) ;error=None
                    except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
                self.assertFalse(folder.exists())
                # Only the intentionally shortened scheduler exit line differs.
                text=re.sub(r'\[exit-diagnostic\] scheduler leaving .*? reason=(.*?) standby=.*',
                            r'[independent] scheduler exit reason=\1',log.getvalue())
                results.append((value,error,events,specs,text,rng.getstate()))
            # Intentional fix: no paint after an exit request. Compare every
            # remaining event, including live replacements and all releases.
            self.assertNotIn(('closed_present',),results[1][2])
            adjusted_old=list(results[0]);adjusted_old[2]=[e for e in adjusted_old[2] if e!=('closed_present',)]
            results[0]=tuple(adjusted_old)
            if mode=='title_error':
                # Intentional fix: the pre-Popen mapping is now closed when
                # spec/title preparation fails. All other behavior stays equal.
                self.assertEqual(results[1][2].count(('trace_close',)),1)
                self.assertEqual(results[0][2].count(('trace_close',)),0)
                adjusted=list(results[1]);adjusted[2]=[e for e in adjusted[2] if e!=('trace_close',)]
                self.assertEqual(tuple(adjusted),results[0])
            else:
                self.assertEqual(*results)
            return results[1]

    def test_normal_launch_serialization_and_weight(self):
        r=self.scenario();self.assertIsNone(r[1]);self.assertEqual(len(r[3]),1)
        self.assertEqual(r[3][0]['title'],'日本語 title');self.assertEqual(r[3][0]['index'],0)

    def test_whitelist_blacklist_and_frozen_commands(self):
        for black in (False,True):
            for white in (False,True):
                for frozen in (False,True):
                    r=self.scenario(black=black,white=white,frozen=frozen);self.assertIsNone(r[1])
                    self.assertEqual(r[3][0]['rom'],'b.zip' if black and not white else 'a.zip')

    def test_exit_classification_and_replacement(self):
        for mode in ('complete','crash','user','hang'):
            r=self.scenario(mode);self.assertIsNone(r[1])

    def test_standby_cleanup_order(self):
        r=self.scenario('standby');self.assertIsNone(r[1]);self.assertIn(('close_job',9),r[2])

    def test_launch_failures_cleanup(self):
        for mode in ('title_error','popen_error','assign_error'):
            r=self.scenario(mode);self.assertIsNotNone(r[1])

    def test_favorites_refresh_retains_identity_and_error_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'favorites.json';system={'id':'a','name':'A'};systems=[system];catalogs={'a':[Path('a.zip')]}
            stamp,items=current._refresh_scheduler_favorites(path,object(),[],systems,catalogs)
            self.assertIsNone(stamp);self.assertEqual(items,[])
            path.write_text(json.dumps({'items':[{'system':'a','rom':'a.zip'}]}),encoding='utf-8')
            stamp,items=current._refresh_scheduler_favorites(path,stamp,items,systems,catalogs)
            self.assertEqual(items,[(system,Path('a.zip'))])
            again=current._refresh_scheduler_favorites(path,stamp,items,systems,catalogs);self.assertIs(again[1],items)
            path.write_text('{invalid',encoding='utf-8');log=io.StringIO()
            with contextlib.redirect_stdout(log):stamp,items=current._refresh_scheduler_favorites(path,stamp,items,systems,catalogs)
            self.assertEqual(items,[]);self.assertIn('configuration error',log.getvalue())
            with patch.object(current,'load_favorites',side_effect=AssertionError('must not retry unchanged file')):
                current._refresh_scheduler_favorites(path,stamp,items,systems,catalogs)

if __name__=='__main__':unittest.main()

