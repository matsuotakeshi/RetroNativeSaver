"""Normal monitoring stays available without black-screen investigation files."""
import ast
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import startup_timing as timing


class ProductionLoggingTests(unittest.TestCase):
    def setUp(self):
        for key,value in (('_path',None),('_identity',{})):
            p=patch.object(timing,key,value);p.start();self.addCleanup(p.stop)

    def test_normal_start_neither_queries_processes_nor_writes_trace(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),\
             patch.object(timing,'_process_identity') as query,patch.object(Path,'open') as opening:
            timing.start(folder,'version',[])
            timing.point('logging_ready');timing.measure('work',lambda:7)
            query.assert_not_called();opening.assert_not_called()

    def test_explicit_measurement_records_identity_and_points_only(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,RNS_STARTUP_TIMING='1'),\
             patch.object(timing,'_process_identity',side_effect=lambda pid:dict(pid=pid,creation_filetime=123)):
            timing.start(folder,'v0.21.4',['--worker'])
            timing.point('logging_ready')
            paths=list(Path(folder).glob('*'));self.assertEqual(len(paths),1)
            self.assertTrue(paths[0].name.startswith('startup_trace_'))
            rows=[json.loads(line) for line in paths[0].read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['event'] for r in rows],['process_entry','process_context','startup_point'])
            self.assertEqual(rows[0]['version'],'v0.21.4')
            self.assertEqual(rows[0]['role'],'worker')
            self.assertNotIn('immediate_job_flags',rows[1])
            self.assertNotIn('foreground_process',rows[1])

    def test_measurement_excludes_guard_and_does_not_pair_reused_parent(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,RNS_STARTUP_TIMING='1'),\
             patch.object(timing,'_process_identity',side_effect=[dict(pid=1,creation_filetime=100),dict(pid=2,creation_filetime=200)]) as query:
            timing.start(folder,'version',['--supervisor-guard']);query.assert_not_called()
            timing.start(folder,'version',[])
            rows=[json.loads(line) for line in timing._path.read_text(encoding='utf-8').splitlines()]
            self.assertNotIn('creation_filetime',rows[1]['parent'])

    def test_logging_failure_does_not_prevent_forced_exit(self):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if getattr(n,'name','')=='hard_exit_process')
        kernel=Mock();kernel.GetCurrentProcess.return_value=99
        ns=dict(kernel32=kernel,os=Mock(),sys=SimpleNamespace(stdout=Mock(),stderr=Mock()))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<forced exit>','exec'),ns)
        with patch('builtins.print',side_effect=OSError('log unavailable')):
            ns['hard_exit_process'](76)
        kernel.TerminateProcess.assert_called_once_with(99,76)
        ns['os']._exit.assert_called_once_with(76)

    def test_no_black_screen_diagnostic_modules_or_imports(self):
        root=Path(__file__).parent
        removed={'display_diagnostics','display_monitor','process_observer','exit_diagnostics'}
        for name in removed:self.assertFalse((root/(name+'.py')).exists())
        for path in root.glob('*.py'):
            if path.name.startswith('test_'):continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node,ast.ImportFrom):self.assertNotIn(node.module,removed,path.name)


if __name__=='__main__':unittest.main()
