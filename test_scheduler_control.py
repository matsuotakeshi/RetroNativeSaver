import ast
import contextlib
import copy
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
import independent_slots as current

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_scheduler_v090.py').read_text(encoding='utf-8')


def monitor(old):
    text=OLD if old else (ROOT/'independent_slots.py').read_text(encoding='utf-8-sig')
    scheduler=next(n for n in ast.parse(text).body if getattr(n,'name','')=='run_scheduler')
    if not old:return next(n for n in scheduler.body if getattr(n,'name','')=='monitor_slots')
    outer=next(n for n in scheduler.body if isinstance(n,ast.Try));loop=outer.body[0]
    start=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='starting')
    fn=ast.parse('def monitor_slots(now): pass').body[0]
    fn.body=loop.body[start:start+2]+ast.parse('return starting').body
    return ast.fix_missing_locations(fn)

class SchedulerControlTests(unittest.TestCase):

    def compare(self,definitions,now=100,fail_at=None,cfg=None):
        results=[]
        for old in (True,False):
            events=[];slots=[];next_try=[-1]*len(definitions);win=SimpleNamespace(hwnd=1,should_close=False,_note_exit=lambda *a:events.append(('note',a)))
            for i,definition in enumerate(definitions):
                if definition is None:slots.append(None);continue
                d=copy.deepcopy(definition)
                def poll(i=i,d=d):
                    events.append(('poll',i))
                    if fail_at=='poll':raise RuntimeError('poll failure')
                    return d.get('code')
                proc=SimpleNamespace(pid=100+i,poll=poll,kill=lambda i=i:events.append(('kill',i)),wait=lambda timeout,i=i:events.append(('wait',i,timeout)))
                slots.append(dict(proc=proc,trace=i,index=i,spawned=d.get('spawned',90),progress=d.get('progress',90),ready=d.get('ready',False),last_trace=d.get('last_trace','old')))
            def read(trace):
                events.append(('read',trace))
                if fail_at=='read':raise RuntimeError('read failure')
                return definitions[trace].get('snapshot')
            def dispose(index):
                events.append(('dispose',index))
                if fail_at=='dispose':raise RuntimeError('dispose failure')
                slots[index]=None
            def fail(record,snapshot,reason,exit_code=None):events.append(('fail',record['index'],snapshot,reason,exit_code))
            ns=dict(api=SimpleNamespace(read_runtime_trace=read),slots=slots,next_try=next_try,win=win,cfg=cfg or {},
                    _read_slot_progress=current._read_slot_progress,tile_exit_status=current.tile_exit_status,tile_hung=current.tile_hung,COMPLETE=current.COMPLETE,dispose=dispose,fail=fail)
            exec(compile(ast.Module(body=[monitor(old)],type_ignores=[]),'<monitor>','exec'),ns)
            log=io.StringIO()
            with contextlib.redirect_stdout(log):
                try:value=ns['monitor_slots'](now);error=None
                except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
            states=[None if r is None else {k:v for k,v in r.items() if k!='proc'} for r in slots]
            results.append((value,error,events,states,next_try,win.should_close,log.getvalue()))
        self.assertEqual(*results)
        return results[1]

    def test_loading_blocks_startup_until_ready(self):
        r=self.compare([None,{'snapshot':{'phase':'START_ENTER','raw':'new'}}]);self.assertTrue(r[0])
        r=self.compare([{'snapshot':{'phase':'SLOT_RUNNING','raw':'new'}}]);self.assertFalse(r[0]);self.assertTrue(r[3][0]['ready'])

    def test_progress_changes_and_missing_snapshot(self):
        for snapshot in (None,{}, {'phase':'WAIT_FRAME','raw':'old'}, {'phase':'WAIT_FRAME','raw':'new'}, {'phase':'SLOT_RUNNING','raw':'old'}):
            for ready in (False,True):
                self.compare([{'snapshot':snapshot,'ready':ready}])

    def test_exit_breaks_before_later_slots(self):
        r=self.compare([{'code':0,'snapshot':{'phase':'SLOT_USER_EXIT'}},{'snapshot':{'phase':'SLOT_RUNNING'}}])
        self.assertTrue(r[5]);self.assertNotIn(('read',1),r[2]);self.assertEqual(r[4],[-1,-1])

    def test_complete_crash_and_hang_retry_times(self):
        for code,phase in ((75,'SLOT_COMPLETE'),(75,'RUN_ENTER'),(0xC0000005,'RUN_ENTER'),(0,'OTHER')):
            r=self.compare([{'code':code,'snapshot':{'phase':phase}}]);self.assertEqual(r[4],[100]);self.assertIsNone(r[3][0])
        r=self.compare([{'ready':True,'progress':0,'snapshot':{'phase':'SLOT_RUNNING','raw':'old'}}])
        self.assertEqual(r[4],[101]);self.assertEqual([e[0] for e in r[2]],['read','poll','kill','wait','fail','dispose'])

    def test_failure_preserves_partial_updates(self):
        for fail in ('read','poll','dispose'):
            r=self.compare([{'code':75,'snapshot':{'phase':'SLOT_COMPLETE','raw':'new'}}],fail_at=fail)
            self.assertIsNotNone(r[1]);self.assertEqual(r[4],[-1])
        r=self.compare([{'snapshot':{'phase':'START_ENTER'}}],cfg={'worker_run_hang_timeout_seconds':'invalid'})
        self.assertEqual(r[1][0],'ValueError')

if __name__=='__main__':unittest.main()
