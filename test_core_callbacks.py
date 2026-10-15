import ast
import ctypes as C
import io
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import core_callbacks as callbacks
import core_lifecycle as lifecycle


class CoreCallbackTests(unittest.TestCase):
    def setUp(self):
        self.owner = SimpleNamespace(_callback_error=None)
        self.addCleanup(lifecycle._retained.pop, id(self.owner), None)

    def test_real_ctypes_callback_returns_safe_value_and_reports_on_python_side(self):
        @C.CFUNCTYPE(C.c_int)
        @callbacks.protect(self.owner, 'input', 0)
        def broken(): raise ValueError('bad input')
        with patch('sys.stderr', new_callable=io.StringIO) as errors:
            self.assertEqual(broken(), 0)
            self.assertEqual(errors.getvalue(), '')
        self.assertTrue(self.owner._cleanup_requires_recycle)
        with self.assertRaisesRegex(callbacks.CoreCallbackError, 'input: ValueError'):
            callbacks.raise_pending(self.owner)

    def test_first_error_preserved_and_later_callbacks_short_circuit(self):
        @callbacks.protect(self.owner, 'first', False)
        def first(): raise RuntimeError('first error')
        first()
        @callbacks.protect(self.owner, 'second', 0)
        def second(): self.fail('must not run after callback failure')
        self.assertEqual(second(), 0)
        self.assertIn('first error', self.owner._callback_error)

    def test_logging_failure_still_returns_fallback(self):
        @callbacks.protect(self.owner, 'video')
        def broken(): raise OSError('video error')
        with patch('builtins.print', side_effect=OSError('log unavailable')):
            self.assertIsNone(broken())
        self.assertIs(lifecycle._retained[id(self.owner)], self.owner)

    def test_base_exception_and_unprintable_exception_do_not_escape(self):
        class Unprintable(BaseException):
            def __str__(self): raise ValueError('str failure')
        @callbacks.protect(self.owner, 'environment', False)
        def broken(): raise Unprintable()
        self.assertFalse(broken())
        self.assertIn('unprintable', self.owner._callback_error)

    def test_success_preserves_values_and_does_not_retain(self):
        @callbacks.protect(self.owner, 'input', 0)
        def good(value): return value + 1
        self.assertEqual(good(4), 5)
        callbacks.raise_pending(self.owner)
        self.assertNotIn(id(self.owner), lifecycle._retained)

    def test_real_environment_and_video_registration_guarded(self):
        from test_frame_boundaries import TYPES, new_core
        core = new_core(TYPES[1])
        self.addCleanup(lifecycle._retained.pop, id(core), None)
        core.dll = SimpleNamespace(**{name:lambda value:None for name in (
            'retro_set_environment','retro_set_video_refresh','retro_set_audio_sample',
            'retro_set_audio_sample_batch','retro_set_input_poll','retro_set_input_state')})
        def broken(*args): raise ValueError('callback failed')
        core._handle_environment = broken
        core._install_callbacks()
        self.assertFalse(core._env(99, None))
        with self.assertRaises(callbacks.CoreCallbackError): core.run_frame()
        self.assertEqual(core._run_frame_index, 0)

    def test_callback_failure_during_unload_prevents_further_native_calls(self):
        from test_core_lifecycle import CoreLifecycleTests
        case = CoreLifecycleTests(); case.setUp()
        self.addCleanup(case.doCleanups)
        @callbacks.protect(case.core, 'env', False)
        def broken(): raise ValueError('unload callback')
        case.core.dll.retro_unload_game = broken
        case.close()
        self.assertNotIn('deinit', case.events)
        self.assertNotIn('free', case.events)

    def test_retained_resources_stop_next_start(self):
        lifecycle.retain_uncertain(self.owner, 'test')
        with self.assertRaises(lifecycle.IncompleteCleanup): lifecycle.ensure_no_retained_resources()

    def test_standalone_entry_exits_without_dll_teardown_when_retained(self):
        # Execute the actual entry block with a harmless stub and no core/window.
        program = '''
import ast, os, sys
from pathlib import Path
import core_lifecycle
tree=ast.parse(Path('native_saver.py').read_text(encoding='utf-8'))
entry=tree.body[-1]
if sys.argv[1]=='retained': core_lifecycle._retained[1]=object()
namespace=dict(__name__='__main__',sys=sys,os=os,supervisor_main=lambda:0,
               hard_exit_process=os._exit,WORKER_RESTART_EXIT_CODE=75)
exec(compile(ast.Module(body=[entry],type_ignores=[]),'<entry>','exec'),namespace)
'''
        for mode, expected in (('normal',0),('retained',76)):
            result = subprocess.run([sys.executable, '-c', program, mode], cwd=Path(__file__).parent,
                capture_output=True, timeout=10, creationflags=0x08000000 if os.name=='nt' else 0)
            self.assertEqual(result.returncode, expected, result.stderr)


if __name__ == '__main__': unittest.main()
