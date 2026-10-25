"""Exercise the actual supervisor orchestration without windows or native cores."""
import ast
import contextlib
import io
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import config_snapshot
import launch_options
import startup_timing
from runtime_policy import NATIVE_CRASH_CODES
from supervisor_safety import SupervisorSafety
from supervisor_watchdog import WorkerWatchdog


class SupervisorSessionTests(unittest.TestCase):
    def run_session(self, workers, *, snapshot=None, final_snapshot=None, backdrop_event=None,
                    independent=False, assigned=True, spawn_error=False,
                    handoff=False, cleanup_error=False, launch_error=False):
        events=[]
        cfg=dict(persistent_rom_blacklist_enabled=False,persistent_rom_whitelist_enabled=False,
                 session_system_crash_limit=1,worker_run_hang_timeout_seconds=1,
                 worker_prepare_hang_timeout_seconds=1,supervisor_watchdog_enabled=False,
                 independent_slots_enabled=independent)
        if handoff:
            cfg.update(saver_controls_enabled=True,independent_slots_enabled=True)
        children=[]
        for code,polls in workers:
            child=Mock(pid=100+len(children),returncode=code,_handle=None)
            remaining=[polls]
            def poll(child=child,remaining=remaining):
                if remaining[0]:remaining[0]-=1;return None
                return child.returncode
            def stop(child=child,remaining=remaining):
                events.append(('terminate',child.pid));remaining[0]=0;child.returncode=75
            child.poll.side_effect=poll
            child.terminate.side_effect=stop
            child.kill.side_effect=stop
            children.append(child)
        launches=[]
        def spawn(cmd,env):
            events.append(('spawn',));launches.append(env.copy())
            if spawn_error:raise OSError('spawn failure')
            if len(launches)>len(children):raise AssertionError('unexpected restart')
            return children[len(launches)-1]
        trace=Mock()
        trace.close.side_effect=lambda:events.append(('trace_close',))
        frozen=Mock()
        frozen.apply.side_effect=lambda env:env.update(SNAPSHOT='same')
        frozen.close.side_effect=lambda:events.append(('snapshot_close',))
        import retroarch_launch
        channel=Mock()
        channel.apply.side_effect=lambda env:events.append(('handoff_reset',))
        channel.read.side_effect=lambda pid:events.append(('handoff_read',pid)) or {'pid':pid,'system':{'id':'test'},'rom':'game'}
        channel.close.side_effect=lambda:events.append(('handoff_close',))
        def launch(*args):
            events.append(('retroarch_start',))
            if launch_error:raise OSError('test launch failure')
        backdrop=None
        if backdrop_event:
            backdrop=Mock(should_close=False,power_idle=False,exit_reason='mouse')
            pumps=[0]
            def pump():
                pumps[0]+=1
                if backdrop_event=='before_spawn' and pumps[0]==1:backdrop.power_idle=True
                if pumps[0]==2:
                    if backdrop_event=='mouse':backdrop.should_close=True
                    elif backdrop_event=='standby':backdrop.power_idle=True
            backdrop.pump.side_effect=pump
        def standby(backdrop,job,*rest):
            events.append(('standby',job,len(rest)));return 9
        ns=dict(sys=SimpleNamespace(argv=['saver','--windowed'],executable='saver.exe',frozen=True),
                os=SimpleNamespace(name='nt',getpid=lambda:77,environ={}),
                APP_DIR=Path(__file__).parent,_LOG_DIR=Path(__file__).parent,
                parse_screensaver_args=lambda argv:('windowed',None,argv),
                resolve_app_relative_path=lambda value,default:value or default,
                mmap=SimpleNamespace(mmap=lambda *a,**k:trace),RUNTIME_TRACE_SIZE=4096,
                create_supervisor_backdrop=lambda cfg:backdrop,
                time=SimpleNamespace(monotonic=itertools.count(1).__next__,sleep=lambda s:None),
                _create_worker_job_object=lambda:123,_assign_worker_to_job=lambda *a:assigned,
                subprocess=SimpleNamespace(Popen=spawn),Path=Path,__file__=__file__,json=json,
                RUNTIME_TRACE_ENV='TRACE',SESSION_QUARANTINE_ENV='QUARANTINE',SESSION_DISABLED_SYSTEMS_ENV='DISABLED',
                WORKER_RESTART_EXIT_CODE=75,NATIVE_CRASH_CODES=NATIVE_CRASH_CODES,
                read_runtime_trace=lambda mm:snapshot,
                log_runtime_trace_snapshot=lambda *a:final_snapshot,
                kernel32=SimpleNamespace(CloseHandle=lambda h:events.append(('job_close',h)) or not cleanup_error),
                user32=Mock(),
                restore_windows_desktop=lambda w:events.append(('restore',)),
                wait_for_display_resume=standby,wait_for_scheduler_standby=standby)
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if getattr(n,'name','')=='supervisor_main')
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual supervisor>','exec'),ns)
        with patch.object(launch_options,'load_supervisor_config',return_value=cfg), \
             patch.object(config_snapshot,'ConfigSnapshot',return_value=frozen), \
             patch('worker_workspace.WorkerWorkspace'), \
             patch.object(retroarch_launch,'LaunchChannel',return_value=channel), \
             patch.object(retroarch_launch,'launch',side_effect=launch), \
             patch('process_cleanup.retain'), \
             patch.object(startup_timing,'measure',side_effect=lambda name,fn,*a,**k:fn(*a,**k)), \
             patch.object(startup_timing,'point'),contextlib.redirect_stdout(io.StringIO()):
            try:result=ns['supervisor_main']();error=None
            except Exception as exc:result=None;error=exc
        return result,error,events,launches,children

    def test_retroarch_only_after_successful_full_cleanup(self):
        result,error,events,_,_=self.run_session([(0,0)],handoff=True)
        self.assertIsNone(error);self.assertEqual(result,0)
        self.assertEqual(events[-6:],[('job_close',123),('restore',),('trace_close',),('snapshot_close',),
                                     ('handoff_close',),('retroarch_start',)])
        self.assertEqual(events.count(('retroarch_start',)),1)

    def test_retroarch_never_starts_on_crash_power_mouse_or_cleanup_failure(self):
        for options in ({'workers':[(1,0)]}, {'workers':[(0,1)],'backdrop_event':'mouse'},
                        {'workers':[(0,1)],'backdrop_event':'standby'},
                        {'workers':[(0,0)],'cleanup_error':True}):
            result,error,events,_,_=self.run_session(handoff=True,**options)
            self.assertNotIn(('retroarch_start',),events)
            self.assertIn(('handoff_close',),events)
        self.assertIsNotNone(error)

    def test_retroarch_launch_failure_does_not_restart_saver(self):
        result,error,events,launches,_=self.run_session([(0,0)],handoff=True,launch_error=True)
        self.assertIsNone(error);self.assertEqual(result,0);self.assertEqual(len(launches),1)
        self.assertEqual(events.count(('retroarch_start',)),1)

    def test_retroarch_channel_resets_after_worker_recycle(self):
        result,error,events,_,_=self.run_session([(75,0),(0,0)],handoff=True)
        self.assertIsNone(error);self.assertEqual(events.count(('handoff_reset',)),2)
        self.assertNotIn(('handoff_read',100),events);self.assertIn(('handoff_read',101),events)

    def test_recycle_preserves_session_snapshot_and_clears_watchdog(self):
        result,error,events,launches,_=self.run_session([(75,0),(0,1)])
        self.assertIsNone(error);self.assertEqual(result,0);self.assertEqual(len(launches),2)
        self.assertEqual(launches[0],launches[1])
        self.assertEqual(events[-4:],[('job_close',123),('restore',),('trace_close',),('snapshot_close',)])

    def test_runtime_hang_snapshot_survives_missing_final_trace(self):
        snap=dict(phase='RUN_ENTER',system='A',rom='game.zip')
        result,error,events,launches,_=self.run_session([(0,3),(0,0)],snapshot=snap)
        self.assertIsNone(error);self.assertEqual(result,0)
        self.assertIn(('terminate',100),events)
        self.assertEqual(json.loads(launches[1]['QUARANTINE']),{'A':['game.zip']})
        self.assertEqual(json.loads(launches[1]['DISABLED']),['A'])

    def test_frontend_hang_closes_without_restarting_or_terminating_directly(self):
        for phase in ('ROM_CATALOG','SLOT_SCHEDULER'):
            result,error,events,launches,_=self.run_session([(0,2)],snapshot=dict(phase=phase))
            self.assertIsNone(error);self.assertEqual(result,1);self.assertEqual(len(launches),1)
            self.assertFalse(any(e[0]=='terminate' for e in events));self.assertIn(('job_close',123),events)

    def test_native_crash_updates_next_worker_quarantine(self):
        result,error,_,launches,_=self.run_session([(0xC0000005,0),(0,0)],
            final_snapshot=dict(phase='RUN_ENTER',system='A',rom='x'))
        self.assertIsNone(error);self.assertEqual(result,0)
        self.assertEqual(json.loads(launches[1]['QUARANTINE']),{'A':['x']})

    def test_mouse_exit_releases_owned_resources_without_restart(self):
        result,error,events,launches,_=self.run_session([(0,1)],backdrop_event='mouse')
        self.assertIsNone(error);self.assertEqual(result,0);self.assertEqual(len(launches),1)
        self.assertEqual(events[-4:],[('job_close',123),('restore',),('trace_close',),('snapshot_close',)])

    def test_standby_job_ownership_and_no_new_worker(self):
        for event,independent,extra,owns_job,count in (
            ('before_spawn',False,0,False,0),('standby',False,0,False,1),
            ('standby',True,2,True,1)):
            result,error,events,launches,_=self.run_session([(0,1)],backdrop_event=event,independent=independent)
            self.assertIsNone(error);self.assertEqual(result,9);self.assertEqual(len(launches),count)
            self.assertIn(('standby',123,extra),events)
            self.assertEqual(('job_close',123) in events,owns_job)

    def test_spawn_and_job_assignment_failures_still_clean_up(self):
        for spawn_error in (True,False):
            _,error,events,_,children=self.run_session([(0,1)],spawn_error=spawn_error,assigned=False)
            self.assertIsInstance(error,OSError if spawn_error else RuntimeError)
            self.assertEqual(events[-4:],[('job_close',123),('restore',),('trace_close',),('snapshot_close',)])
            if not spawn_error:children[0].kill.assert_called_once();self.assertEqual(children[0].wait.call_count,2)

    def test_watchdog_instances_never_share_progress(self):
        snap={'phase':'RUN_ENTER'};terminate=Mock()
        first=WorkerWatchdog({'worker_run_hang_timeout_seconds':1},.25,lambda mm:snap,terminate)
        second=WorkerWatchdog({},.25,lambda mm:snap,terminate)
        with contextlib.redirect_stdout(io.StringIO()):
            first.check(SimpleNamespace(pid=1),1,object());first.check(SimpleNamespace(pid=1),2,object())
        self.assertTrue(first.watchdog_triggered)
        self.assertFalse(second.watchdog_triggered);self.assertIsNone(second.watchdog_snapshot)
        self.assertIsNone(second.watchdog_since);self.assertEqual(second.watchdog_last_check,0)

    def test_settings_defaults_clamps_paths_and_invalid_values(self):
        paths=[]
        def resolve(value,default):paths.append((value,default));return value or default
        safety=SupervisorSafety({},resolve)
        self.assertEqual(len(paths),3);self.assertEqual(safety.session_system_crash_limit,3)
        self.assertEqual(safety.persistent_rom_blacklist_threshold_sessions,2)
        self.assertEqual((safety.worker_run_hang_timeout_seconds,safety.worker_start_hang_timeout_seconds,
                          safety.worker_watchdog_poll_seconds),(15,45,.25))
        safety=SupervisorSafety(dict(session_system_crash_limit=0,persistent_rom_blacklist_threshold_sessions=0,
                                     worker_watchdog_poll_seconds=0),resolve)
        self.assertEqual((safety.session_system_crash_limit,safety.persistent_rom_blacklist_threshold_sessions,
                          safety.worker_watchdog_poll_seconds),(1,2,.05))
        for key in ('session_system_crash_limit','persistent_rom_blacklist_threshold_sessions',
                    'worker_run_hang_timeout_seconds','worker_start_hang_timeout_seconds','worker_watchdog_poll_seconds'):
            with self.assertRaises(ValueError):SupervisorSafety({key:'bad'},resolve)


if __name__=='__main__':unittest.main()
