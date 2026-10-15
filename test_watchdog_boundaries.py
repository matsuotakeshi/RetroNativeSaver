import ast
import contextlib
import copy
import ctypes
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from runtime_policy import PREPARATION_PHASES,watchdog_timeout,progress_key
from supervisor_watchdog import WorkerWatchdog, terminate_hung_worker

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_watchdog_v093.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
def sup(source):return next(n for n in ast.parse(source).body if getattr(n,'name','')=='supervisor_main')
def legacy_block():
    return next(n for n in ast.walk(sup(OLD)) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and any(isinstance(v,ast.Name) and v.id=='watchdog_last_check' for v in ast.walk(n.test)))


def factory(old,ns):
    if not old:
        monitor=WorkerWatchdog(ns['supervisor_cfg'],ns['worker_watchdog_poll_seconds'],
                              ns['read_runtime_trace'],
                              lambda proc: terminate_hung_worker(proc,ns['kernel32'],ns['WORKER_RESTART_EXIT_CODE']))
        def state():
            return (monitor.watchdog_last_check,monitor.watchdog_key,monitor.watchdog_since,
                    monitor.watchdog_triggered,monitor.watchdog_snapshot)
        return lambda proc,now:monitor.check(proc,now,ns['runtime_trace_mm']),state
    definition=ast.parse('''def make():
    watchdog_last_check=0.0
    watchdog_key=None
    watchdog_since=None
    watchdog_triggered=False
    watchdog_snapshot=None
    def state():
        return watchdog_last_check,watchdog_key,watchdog_since,watchdog_triggered,watchdog_snapshot
    return check_worker_watchdog,state
''').body[0]
    check=ast.parse("def check_worker_watchdog(proc, now_watchdog):\n    nonlocal watchdog_last_check, watchdog_key, watchdog_since, watchdog_triggered, watchdog_snapshot").body[0]
    check.body.append(copy.deepcopy(legacy_block()))
    definition.body[-1:-1]=[check]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[definition],type_ignores=[])),'<watchdog>','exec'),ns)
    return ns['make']()

class WatchdogBoundaryTests(unittest.TestCase):

    def compare(self,sequence,handle=123,api_error=False,terminate_error=False,kill_error=False,mapping=True,cfg=None,read_error=False,api_result=True):
        results=[]
        for old in (True,False):
            events=[];current=[None]
            def read(mm):
                events.append(('read',mm))
                if read_error:raise OSError('mapping read failure')
                return current[0]
            def terminate_api(h,c):
                events.append(('TerminateProcess',h.value,c.value))
                if api_error:raise OSError('api failure')
                return api_result
            def terminate():
                events.append(('terminate',))
                if terminate_error:raise OSError('terminate failure')
            def kill():
                events.append(('kill',))
                if kill_error:raise OSError('kill failure')
            proc=SimpleNamespace(pid=456,_handle=handle,terminate=terminate,kill=kill)
            ns=dict(runtime_trace_mm='mapping' if mapping else None,worker_watchdog_poll_seconds=.25,
                    supervisor_cfg={"worker_run_hang_timeout_seconds":20, **(cfg or {})},read_runtime_trace=read,watchdog_timeout=watchdog_timeout,progress_key=progress_key,
                    PREPARATION_PHASES=PREPARATION_PHASES,WORKER_RESTART_EXIT_CODE=75,kernel32=SimpleNamespace(TerminateProcess=terminate_api),
                    c_void_p=ctypes.c_void_p,c_uint=ctypes.c_uint)
            step,state=factory(old,ns);observed=[];log=io.StringIO()
            with contextlib.redirect_stdout(log):
                for now,snapshot in sequence:
                    current[0]=copy.deepcopy(snapshot)
                    try:result=step(proc,now);error=None
                    except Exception as exc:result=None;error=(type(exc).__name__,str(exc))
                    observed.append((result,error,copy.deepcopy(state())))
                    if result==1 or error:break
            results.append((events,observed,log.getvalue()))
        self.assertEqual(*results);return results[1]

    def test_poll_boundaries_and_absent_mapping(self):
        snap={'phase':'RUN_ENTER'}
        r=self.compare([(0.1,snap),(.25,snap),(.49,snap),(.50,snap)]);self.assertEqual(len(r[0]),2)
        r=self.compare([(1,snap),(30,snap)],mapping=False);self.assertEqual(r[0],[])

    def test_native_timeout_boundary_and_reset(self):
        snap={'phase':'RUN_ENTER','call_count':1}
        r=self.compare([(1,snap),(20.5,snap),(21,snap),(22,snap),(41,snap),(42,snap)])
        self.assertEqual(sum(e[0]=='TerminateProcess' for e in r[0]),2)
        self.assertEqual(r[1][2][2][1:3],(None,None));self.assertTrue(r[1][2][2][3])
        self.assertEqual(r[1][2][2][4],snap)

    def test_frontend_stalls_return_without_termination(self):
        for phase in (*PREPARATION_PHASES,'SLOT_SCHEDULER'):
            r=self.compare([(1,{'phase':phase}),(200,{'phase':phase})])
            self.assertEqual(r[1][-1][0],1);self.assertFalse(any(e[0]=='TerminateProcess' for e in r[0]))

    def test_progress_change_unknown_phase_and_empty_read(self):
        seq=[(1,{'phase':'RUN_ENTER','call_count':1}),(5,None),(10,{'phase':'RUN_ENTER','call_count':2}),
             (20,{'phase':'OTHER'}),(30,{'phase':' RUN_ENTER ','call_count':2}),(49,{'phase':'RUN_ENTER','call_count':2,'raw':'changed'})]
        r=self.compare(seq);self.assertFalse(any(e[0]=='TerminateProcess' for e in r[0]))
        self.assertEqual(r[1][1][2][2],1);self.assertEqual(r[1][3][2][1:3],(None,None))

    def test_termination_paths_and_failures(self):
        seq=[(1,{'phase':'START_ENTER'}),(46,{'phase':'START_ENTER'})]
        for handle in (None,0,123):
            for api_error in (False,True):
                for terminate_error in (False,True):
                    for kill_error in (False,True):
                        r=self.compare(seq,handle,api_error,terminate_error,kill_error)
                        self.assertIsNone(r[1][-1][1]);self.assertEqual(r[1][-1][2][1:3],(None,None))
        r=self.compare(seq,api_result=False);self.assertNotIn(('kill',),r[0])

    def test_read_and_conversion_failures_partial_state(self):
        r=self.compare([(1,{'phase':'RUN_ENTER'})],read_error=True);self.assertEqual(r[1][0][1][0],'OSError');self.assertEqual(r[1][0][2][0],1)
        for snap,cfg in (({'phase':'RUN_ENTER','cycle':'bad'},{}),({'phase':'RUN_ENTER'},{'worker_run_hang_timeout_seconds':'bad'})):
            r=self.compare([(1,snap)],cfg=cfg);self.assertEqual(r[1][0][1][0],'ValueError')

if __name__=='__main__':unittest.main()

