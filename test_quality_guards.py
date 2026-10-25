"""Regressions for the v0.22 audit fixes; no emulator or visible window."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from favorites import save_favorites, load_favorites_snapshot
from runtime_policy import RestartBudget, watchdog_timeout, worker_runtime_failure, NATIVE_CRASH_CODES
from supervisor_watchdog import terminate_hung_worker, WorkerWatchdog
import test_supervisor_session
from file_transaction import file_lock
from rom_state_store import _record_persistent_rom_failure
from saver_actions import add_favorite, blacklist_rom
from resource_policy import _resource_group_usage_from_picks
from worker_workspace import WorkerWorkspace

ROOT = Path(__file__).parent


class ExitGuards(unittest.TestCase):
    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__(); self.addCleanup(quiet.__exit__, None, None, None)

    def test_repeated_abnormal_restarts_stop_and_normal_cycles_are_unlimited(self):
        budget = RestartBudget()
        self.assertEqual([budget.allow(75, {'phase': 'ROM_CATALOG'}) for _ in range(3)], [True, True, False])
        for _ in range(100):
            self.assertTrue(budget.allow(75, {'phase': 'CYCLE_SWITCH'}))
        self.assertTrue(budget.allow(0xC0000005, {'phase': 'RUN_ENTER'}))
        self.assertTrue(budget.allow(75, {'phase': 'CLOSE_INCOMPLETE'}))
        self.assertFalse(budget.allow(75, {'phase': 'START_FAILED'}))

    def test_actual_supervisor_limits_failures_but_stops_fatal_exit_immediately(self):
        case = test_supervisor_session.SupervisorSessionTests()
        for code, phase, count in ((75, 'ROM_CATALOG', 3), (0xC0000005, 'RUN_ENTER', 3), (76, 'ROM_CATALOG', 1)):
            result, error, events, launches, _ = case.run_session([(code, 0)] * count, final_snapshot={'phase': phase})
            self.assertIsNone(error); self.assertNotEqual(result, 0)
            self.assertEqual(len(launches), count)
            self.assertIn(('job_close', 123), events)

    def test_worker_unhandled_exception_uses_fatal_exit(self):
        tree = ast.parse((ROOT / 'native_saver.py').read_text(encoding='utf-8'))
        entry = next(n for n in tree.body if isinstance(n, ast.If) and '__name__' in ast.unparse(n.test))
        block = next(n for n in ast.walk(entry) if isinstance(n, ast.If) and ast.unparse(n.test) == "'--worker' in sys.argv[1:]")
        self.assertIn('hard_exit_process(76)', ast.unparse(block))

    def test_cleanup_hang_has_own_timeout_and_no_rom_penalty(self):
        snap = {'phase': 'CLOSE_ENTER'}
        terminate = Mock(return_value=True)
        monitor = WorkerWatchdog({}, .25, lambda _: snap, terminate)
        proc = Mock(pid=1); proc.poll.return_value = None
        monitor.check(proc, 1, object()); monitor.check(proc, 45, object())
        terminate.assert_not_called()
        monitor.check(proc, 46, object()); terminate.assert_called_once_with(proc)
        self.assertFalse(worker_runtime_failure(snap, 75, True, NATIVE_CRASH_CODES))
        self.assertEqual(watchdog_timeout('CLOSE_ENTER', {'worker_close_hang_timeout_seconds': 90}), 90)
        self.assertEqual(watchdog_timeout('START_CLOSE_ENTER', {}), 45)
        exiting = WorkerWatchdog({}, .25, lambda _: {'phase': 'CLOSE_EXIT_ENTER'}, terminate)
        exiting.check(proc, 1, object())
        self.assertEqual(exiting.check(proc, 46, object()), 1)
        terminate.assert_called_once()  # User exit does not recycle the worker.

    def test_failed_terminate_api_uses_kill_and_failed_kill_closes_session(self):
        proc = Mock(pid=1, _handle=123); proc.poll.return_value = None
        kernel = Mock(); kernel.TerminateProcess.return_value = False
        self.assertTrue(terminate_hung_worker(proc, kernel, 75)); proc.kill.assert_called_once()
        proc.kill.side_effect = OSError('denied')
        self.assertFalse(terminate_hung_worker(proc, kernel, 75))
        proc.poll.return_value = 0; kernel.reset_mock(); proc.kill.reset_mock()
        self.assertTrue(terminate_hung_worker(proc, kernel, 75))
        kernel.TerminateProcess.assert_not_called(); proc.kill.assert_not_called()

    def test_successful_termination_request_must_really_exit(self):
        proc = Mock(pid=1); proc.poll.return_value = None
        for accepted in (False, True):
            terminate = Mock(return_value=accepted)
            monitor = WorkerWatchdog({'worker_run_hang_timeout_seconds': 1}, .25,
                                     lambda _: {'phase': 'RUN_ENTER'}, terminate)
            monitor.check(proc, 1, object())
            self.assertEqual(monitor.check(proc, 2, object()), None if accepted else 1)
            if accepted:
                self.assertIsNone(monitor.check(proc, 6.9, object()))
                self.assertEqual(monitor.check(proc, 7, object()), 1)
            terminate.assert_called_once()


class FileTransactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_stale_favorite_editor_cannot_remove_new_registration(self):
        path = self.root / 'favorites.json'
        a, b = self.root / 'a.rom', self.root / 'b.rom'; a.touch(); b.touch()
        save_favorites(path, {'items': [{'system': 's', 'rom': str(a)}]})
        stale, original = load_favorites_snapshot(path)
        add_favorite(path, {'id': 's'}, b, {'s': [a, b]})
        with self.assertRaisesRegex(RuntimeError, '別の操作|another'):
            save_favorites(path, stale, expected=original)
        self.assertEqual(len(load_favorites_snapshot(path)[0]['items']), 2)

    def test_transient_replace_denial_retries_but_never_overwrites_intervening_edit(self):
        from file_transaction import replace_checked
        path, temp = self.root/'state.json', self.root/'new.tmp'
        path.write_bytes(b'old'); temp.write_bytes(b'new')
        denied = PermissionError('busy'); denied.winerror = 32
        real = os.replace
        attempts = []
        def replace(source, target):
            attempts.append(1)
            if len(attempts) == 1: raise denied
            return real(source, target)
        with patch('file_transaction.os.replace', side_effect=replace):
            replace_checked(temp, path, b'old')
        self.assertEqual(path.read_bytes(), b'new'); self.assertEqual(len(attempts), 2)
        temp.write_bytes(b'overwrite')
        def intervening(source, target):
            path.write_bytes(b'external edit')
            raise denied
        with patch('file_transaction.os.replace', side_effect=intervening):
            with self.assertRaises(RuntimeError): replace_checked(temp, path, b'new')
        self.assertEqual(path.read_bytes(), b'external edit')

    def test_stale_failure_state_merges_manual_registration_and_preserves_corrupt_file(self):
        black, white = self.root / 'black.json', self.root / 'white.json'
        stale = {'version': 1, 'systems': {}}
        blacklist_rom(black, white, None, 's', 'manual.rom')
        _record_persistent_rom_failure(stale, black, 'session', 2, 's', 'crash.rom', 'RUN_ENTER', 'crash')
        data = json.loads(black.read_text(encoding='utf-8'))
        self.assertEqual(set(data['systems']['s']), {'manual.rom', 'crash.rom'})
        black.write_bytes(b'{broken')
        with contextlib.redirect_stdout(io.StringIO()):
            _record_persistent_rom_failure(stale, black, 'session2', 2, 's', 'crash.rom', 'RUN_ENTER', 'crash')
        self.assertEqual(black.read_bytes(), b'{broken')

    def test_cross_process_writers_preserve_every_registration(self):
        path = self.root / 'white.json'
        script = ('from rom_list_editor import add_to_whitelist; import sys; '
                  'from pathlib import Path; p=Path(sys.argv[1]); '
                  '[add_to_whitelist(p, [("s", sys.argv[2]+str(i))]) for i in range(5)]')
        procs = [subprocess.Popen([sys.executable, '-c', script, str(path), str(n)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for n in range(4)]
        try:
            for proc in procs:
                _, error = proc.communicate(timeout=30)
                self.assertEqual(proc.returncode, 0, error.decode(errors='replace'))
        finally:
            for proc in procs:
                if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
        self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['systems']['s']), 20)

    def test_lock_released_after_process_crash_and_timeout_is_bounded(self):
        path = self.root / 'state.json'
        script = ('from file_transaction import file_lock; import os,sys; '
                  'lock=file_lock(sys.argv[1]); lock.__enter__(); print("locked",flush=True); '
                  'sys.stdin.readline(); os._exit(75)')
        proc = subprocess.Popen([sys.executable, '-c', script, str(path)], cwd=ROOT,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(proc.stdout.readline().strip(), b'locked')
            with self.assertRaises(TimeoutError):
                with file_lock(path, timeout=.1): pass
            proc.communicate(b'go\n', timeout=10)
            self.assertEqual(proc.returncode, 75)
            with file_lock(path, timeout=.1):
                with file_lock(path, timeout=.1): pass  # same-thread reentrancy
        finally:
            if proc.poll() is None: proc.kill(); proc.wait(timeout=5)


class RetryReservations(unittest.TestCase):
    def test_concurrency_cap_applies_even_with_spare_group_budget(self):
        from slot_selection import normal_retry_candidate
        light = dict(id='a')
        heavy = dict(id='h', max_concurrent=1, resource_group='heavy_cd', resource_weight=1)
        self.assertIsNone(normal_retry_candidate(light, [heavy], {'h':[Path('h')]}, set(),
                          {'heavy_cd':1}, {'resource_groups':{'heavy_cd':{'max_weight':64}}}, [(heavy,Path('h'))]))

    def test_actual_startup_retries_commit_usage_and_respect_other_reservations(self):
        from test_startup_compatibility import functions
        light = [dict(id=s, name=s) for s in ('a', 'b')]
        heavy = dict(id='h', name='h', resource_group='heavy_cd', resource_weight=1, max_concurrent=2)
        systems = light + [heavy]
        cfg = {'resource_groups': {'heavy_cd': {'max_weight': 2}}}
        picks = [(s, Path(s['id'] + '.rom')) for s in systems]
        usage = _resource_group_usage_from_picks(picks)
        failed = set()
        class Core:
            def initialize(self): pass
            def load_game(self, rom):
                if rom.stem != 'h': raise RuntimeError('bad ROM')
                return 'av'
            def close(self): pass
        ns = dict(Path=Path, APP_DIR=ROOT, LibretroCore=Core, shutil=Mock(),
                  resolve_app_relative_path=lambda *a: ROOT, prepare_rom=lambda s,r,d:r,
                  write_runtime_trace=lambda *a,**k:None, is_native_access_violation=lambda e:False)
        exec(functions(ROOT/'native_saver.py'), ns)
        with patch('startup_preparation.prepare_core_paths', return_value=(ROOT,ROOT,ROOT)), \
             patch('startup_preparation.prepare_environment', return_value=(ROOT,ROOT,ROOT,{})), \
             patch('startup_preparation.create_configured_core', side_effect=lambda *a:Core()), \
             patch('startup_preparation.apply_loaded_core_settings'), contextlib.redirect_stdout(io.StringIO()):
            args = (systems, {s['id']:[Path(s['id']+'.rom')] for s in systems}, cfg, ROOT, failed)
            result = ns['start_slot_with_retry'](0, *picks[0], *args, cycle_group_usage=usage, cycle_picks=picks)
            self.assertEqual(result[2]['id'], 'h')
            self.assertEqual(usage, {'heavy_cd': 2})
            with self.assertRaises(RuntimeError):
                ns['start_slot_with_retry'](1, *picks[1], *args, cycle_group_usage=usage, cycle_picks=picks)
        self.assertEqual([s['id'] for s,_ in picks], ['h','b','h'])


class WorkspaceOwnership(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows Job integration')
    def test_real_job_accounts_for_orphaned_grandchild_before_file_removal(self):
        import ctypes
        from worker_workspace import active_processes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [ctypes.c_void_p,ctypes.c_wchar_p], ctypes.c_void_p),
            ('SetInformationJobObject', [ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_ulong], ctypes.c_bool),
            ('AssignProcessToJobObject', [ctypes.c_void_p,ctypes.c_void_p], ctypes.c_bool),
            ('TerminateJobObject', [ctypes.c_void_p,ctypes.c_uint], ctypes.c_bool),
            ('CloseHandle', [ctypes.c_void_p], ctypes.c_bool),
        ):
            fn = getattr(kernel,name); fn.argtypes=args; fn.restype=result
        tree = ast.parse((ROOT/'native_saver.py').read_text(encoding='utf-8'))
        names = {'JOBOBJECT_BASIC_LIMIT_INFORMATION','IO_COUNTERS','JOBOBJECT_EXTENDED_LIMIT_INFORMATION',
                 '_create_worker_job_object','_assign_worker_to_job'}
        nodes = [n for n in tree.body if getattr(n,'name','') in names]
        ns = dict(vars(ctypes), ctypes=ctypes, kernel32=kernel,
                  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000, JobObjectExtendedLimitInformation=9)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<Job helpers>','exec'),ns)
        workspace = WorkerWorkspace(); job = ns['_create_worker_job_object']()
        self.assertTrue(job)
        proc = None
        script = ('import sys,subprocess,os; from pathlib import Path; sys.stdin.readline(); '
                  'p=subprocess.Popen([sys.executable,"-c","import time; print(1,flush=True); time.sleep(60)"], '
                  'stdout=subprocess.PIPE,stderr=subprocess.DEVNULL); '
                  'p.stdout.readline(); (Path(sys.argv[1])/"orphan.txt").write_text(str(p.pid)); os._exit(75)')
        try:
            proc = subprocess.Popen([sys.executable,'-c',script,str(workspace.path)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertTrue(ns['_assign_worker_to_job'](job,proc))
            _, error = proc.communicate(b'go\n',timeout=10)
            self.assertEqual(proc.returncode,75,error.decode(errors='replace'))
            self.assertGreaterEqual(active_processes(kernel,job),1)
            self.assertTrue((workspace.path/'orphan.txt').exists())
            workspace.cleanup(kernel,job,proc)
            self.assertEqual(active_processes(kernel,job),0)
            self.assertFalse(workspace.path.exists())
        finally:
            kernel.TerminateJobObject(job,0)
            if proc is not None:
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=5)
                for pipe in (proc.stdin,proc.stdout,proc.stderr): pipe.close()
            workspace.cleanup(kernel,job)
            kernel.CloseHandle(job)

    def test_forced_worker_exit_files_are_owned_and_removed_by_parent(self):
        workspace = WorkerWorkspace()
        script = ('import tempfile,os,sys; from pathlib import Path; '
                  't=tempfile.TemporaryDirectory(dir=sys.argv[1]); '
                  '(Path(t.name)/"dummy.dll").write_bytes(b"test"); os._exit(75)')
        proc = subprocess.run([sys.executable, '-c', script, str(workspace.path)], timeout=10)
        self.assertEqual(proc.returncode, 75)
        self.assertEqual(len(list(workspace.path.rglob('dummy.dll'))), 1)
        workspace.cleanup(None, None, SimpleNamespace(poll=lambda:75))
        self.assertFalse(workspace.path.exists())

    def test_live_or_unverifiable_descendants_keep_their_files(self):
        workspace = WorkerWorkspace(); self.addCleanup(workspace.cleanup, None, None)
        kernel = Mock(); kernel.TerminateJobObject.return_value = False
        with patch('worker_workspace.active_processes', return_value=1):
            with self.assertRaises(OSError): workspace.cleanup(kernel, 1)
        self.assertTrue(workspace.path.exists())
        with patch('worker_workspace.active_processes', side_effect=OSError('query')):
            with self.assertRaises(OSError): workspace.cleanup(kernel, 1)
        self.assertTrue(workspace.path.exists())
        kernel.TerminateJobObject.return_value = True
        with patch('worker_workspace.active_processes', side_effect=[1,1,0]):
            workspace.cleanup(kernel, 1)
        self.assertFalse(workspace.path.exists())


if __name__ == '__main__': unittest.main()
