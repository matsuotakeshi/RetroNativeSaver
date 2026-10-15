import ast
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import process_cleanup as cleanup
import independent_slots


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.retained=list(cleanup._retained);cleanup._retained.clear()
        self.addCleanup(self.restore)
        self.output=io.StringIO()
        self.quiet=contextlib.redirect_stdout(self.output);self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__,None,None,None)

    def restore(self):
        cleanup._retained[:]=self.retained

    def supervisor(self, fail=None, bad_log=False):
        events=[]
        def action(name):
            events.append(name)
            if name==fail:raise OSError(name)
        kernel=SimpleNamespace(CloseHandle=lambda job:action('job') or fail!='job_false')
        guard=SimpleNamespace(close=lambda:action('guard'))
        window=SimpleNamespace(supervisor_guard=guard)
        trace=SimpleNamespace(close=lambda:action('trace'))
        snapshot=SimpleNamespace(close=lambda:action('snapshot'))
        def record(*args,**kwargs):
            if bad_log:raise OSError('diagnostic writer')
        error=None
        with patch('builtins.print',side_effect=OSError('stdout')) if bad_log else contextlib.nullcontext():
            try:cleanup.cleanup_supervisor(kernel, 1, window, guard, trace, snapshot, lambda w: action('desktop'))
            except Exception as exc:error=exc
        return events,error,window

    def test_supervisor_release_order(self):
        events,error,window=self.supervisor()
        self.assertIsNone(error)
        self.assertEqual(events,['job','desktop','guard','trace','snapshot'])
        self.assertIsNone(window.supervisor_guard)
        self.assertFalse(cleanup.has_retained_resources())

    def test_each_supervisor_failure_still_attempts_independent_releases(self):
        for failure in ('job','job_false','desktop','guard','trace','snapshot'):
            cleanup._retained.clear()
            events,error,window=self.supervisor(failure)
            self.assertEqual(events,['job','desktop','guard','trace','snapshot'])
            self.assertIsInstance(error,cleanup.IncompleteProcessCleanup)
            self.assertTrue(cleanup.has_retained_resources())
            if failure=='guard':self.assertIsNotNone(window.supervisor_guard)

    def test_logging_failure_does_not_skip_cleanup(self):
        events,error,_=self.supervisor(bad_log=True)
        self.assertIsNone(error)
        self.assertEqual(events,['job','desktop','guard','trace','snapshot'])

    def test_unprintable_release_error_does_not_skip_next_release(self):
        class BadError(Exception):
            def __str__(self):raise ValueError('cannot format')
        trace=Mock();trace.close.side_effect=BadError()
        snapshot=Mock()
        with self.assertRaises(cleanup.IncompleteProcessCleanup):
            cleanup.cleanup_supervisor(None, None, None, None, trace, snapshot, lambda w: None)
        snapshot.close.assert_called_once()

    def test_scheduler_wait_failure_retains_files_and_still_releases_other_slot(self):
        slots=[{'alive':True},{'alive':False}];events=[]
        temp=SimpleNamespace(cleanup=lambda:events.append('delete'),_finalizer=SimpleNamespace(detach=lambda:events.append('detach')))
        api=SimpleNamespace(kernel32=SimpleNamespace(CloseHandle=lambda h:False))
        def dispose(index):
            events.append(index)
            if index==0:raise TimeoutError('still alive')
            slots[index]=None
        with self.assertRaises(cleanup.IncompleteProcessCleanup):
            cleanup.cleanup_scheduler(api, 1, slots, dispose, temp)
        self.assertEqual(events,[0,1,'detach'])
        self.assertIn(slots,cleanup._retained)
        self.assertIn(temp,cleanup._retained)

    def test_failed_job_close_does_not_prevent_individual_child_cleanup(self):
        slots=[{},{}];temp=Mock();events=[]
        def dispose(index):slots[index]=None;events.append(index)
        with self.assertRaises(cleanup.IncompleteProcessCleanup):
            cleanup.cleanup_scheduler(SimpleNamespace(kernel32=SimpleNamespace(CloseHandle=lambda h: False)), 1, slots, dispose, temp)
        self.assertEqual(events,[0,1]);temp.cleanup.assert_called_once()

    def test_real_temp_finalizer_detached_when_retained(self):
        temp=tempfile.TemporaryDirectory()
        root=Path(temp.name);(root/'live.rom').touch()
        cleanup.preserve_temp(temp)
        self.assertFalse(temp._finalizer.alive)
        self.assertTrue((root/'live.rom').exists())
        temp.cleanup()  # Test owns no live child; explicitly clean this fixture.

    def test_temp_creation_or_first_present_failure_closes_job(self):
        for fail in ('temp','present'):
            events=[]
            api=SimpleNamespace(_create_worker_job_object=lambda:7,
                kernel32=SimpleNamespace(CloseHandle=lambda h:events.append('job') or True))
            win=SimpleNamespace(hwnd=1,should_close=False,exit_reason='test',begin_composite=lambda:None,
                                present=Mock(side_effect=OSError('present')))
            fake=SimpleNamespace(name='.',cleanup=lambda:events.append('temp'))
            with patch.object(independent_slots,'_load_scheduler_state',return_value=(None,{}, {},{})),\
                 patch.object(independent_slots.tempfile,'TemporaryDirectory',side_effect=OSError('temp') if fail=='temp' else None,return_value=fake):
                with self.assertRaises(OSError):
                    independent_slots.run_scheduler(api,win,[],[],{}, {},None,{})
            self.assertEqual(events,['job'] if fail=='temp' else ['job','temp'])

    def test_dispose_wait_failure_keeps_slot_and_files(self):
        source=ast.parse(Path(independent_slots.__file__).read_text(encoding='utf-8'))
        run=next(n for n in source.body if getattr(n,'name','')=='run_scheduler')
        dispose=next(n for n in run.body if getattr(n,'name','')=='dispose')
        proc=Mock();proc.poll.return_value=None;proc.kill.side_effect=OSError('kill');proc.wait.side_effect=TimeoutError('alive')
        trace=Mock();record=dict(proc=proc,trace=trace,content_dir='not-deleted');slots=[record]
        remove=Mock();ns=dict(slots=slots,exit_record=lambda *a,**k:None,retain=cleanup.retain,
            close_trace=cleanup.close_trace,shutil=SimpleNamespace(rmtree=remove),win=Mock())
        exec(compile(ast.Module(body=[dispose],type_ignores=[]),'<dispose>','exec'),ns)
        with self.assertRaises(TimeoutError):ns['dispose'](0)
        self.assertIs(slots[0],record);trace.close.assert_not_called();remove.assert_not_called()
        proc.wait.side_effect=None
        ns['dispose'](0)
        self.assertIsNone(slots[0]);trace.close.assert_called_once();remove.assert_called_once()

    def test_entry_forces_exit_when_process_resources_remain(self):
        source=(Path(__file__).parent/'native_saver.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        entry=next(n for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))
        self.assertIn('has_process_resources()',ast.unparse(entry))

    def test_unassigned_worker_stopped_even_if_job_close_failed(self):
        proc=Mock();proc.poll.return_value=None
        trace=Mock();snapshot=Mock();restore=Mock()
        with self.assertRaises(cleanup.IncompleteProcessCleanup):
            cleanup.cleanup_supervisor(SimpleNamespace(CloseHandle=lambda h: False), 1, None, None, trace, snapshot, restore, unassigned=proc)
        proc.kill.assert_called_once();proc.wait.assert_called_once_with(timeout=5)
        trace.close.assert_called_once();snapshot.close.assert_called_once();restore.assert_called_once()

    def test_job_creation_failure_releases_or_retains_owned_handle(self):
        source=ast.parse((Path(__file__).parent/'native_saver.py').read_text(encoding='utf-8'))
        fn=next(n for n in source.body if getattr(n,'name','')=='_create_worker_job_object')
        for set_ok,close_ok in ((True,True),(False,True),(False,False)):
            kernel=Mock();kernel.CreateJobObjectW.return_value=7
            kernel.SetInformationJobObject.return_value=set_ok;kernel.CloseHandle.return_value=close_ok
            ns=dict(kernel32=kernel,JOBOBJECT_EXTENDED_LIMIT_INFORMATION=lambda:SimpleNamespace(BasicLimitInformation=SimpleNamespace()),
                    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=1,JobObjectExtendedLimitInformation=9,
                    byref=lambda obj:obj,ctypes=SimpleNamespace(sizeof=lambda obj:1))
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'<job owner>','exec'),ns)
            if not close_ok:
                with self.assertRaises(OSError):ns['_create_worker_job_object']()
                self.assertIn(7,cleanup._retained)
            else:
                self.assertEqual(ns['_create_worker_job_object'](),7 if set_ok else None)
            self.assertEqual(kernel.CloseHandle.call_count,0 if set_ok else 1)


if __name__=='__main__':unittest.main()
