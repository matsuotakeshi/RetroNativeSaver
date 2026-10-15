import ast
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock
import core_lifecycle as lifecycle
from launch_options import load_config, load_supervisor_config
from runtime_policy import DEFAULT_CYCLE_SECONDS
from independent_slots import duration_seconds
from system_config import cycle_settings


class CoreLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.kernel = SimpleNamespace(FreeLibrary=lambda handle: self.events.append('free') or True)
        self.core = SimpleNamespace(
            dll=SimpleNamespace(_handle=10,
                retro_unload_game=lambda: self.events.append('unload'),
                retro_deinit=lambda: self.events.append('deinit')),
            hw_context=None, _initialized=True, _game_loaded=True,
            _cleanup_uncertain=False, _native_fault_during_close=False,
            destroy_hw_before_unload=False, hw_context_reset_done=False,
            hw_context_destroy_addr=0, _game_data_buffer=b'ROM', frame_bytes=b'frame')
        self.addCleanup(lifecycle._retained.pop, id(self.core), None)

    def close(self):
        lifecycle.close_core(self.core, self.kernel,
                             lambda address: lambda: self.events.append('destroy_callback'))

    def hw(self):
        self.core.hw_context = SimpleNamespace(
            make_current=lambda: self.events.append('current') or True,
            close=lambda: self.events.append('wgl_close') or True)
        self.core.hw_context_reset_done = True
        self.core.hw_context_destroy_addr = 20

    def test_normal_and_dolphin_order_preserved(self):
        for early in (False, True):
            self.setUp(); self.hw(); self.core.destroy_hw_before_unload = early
            self.close()
            expected = ['current', 'destroy_callback', 'current', 'unload'] if early else ['current', 'unload', 'current', 'destroy_callback']
            self.assertEqual(self.events, expected + ['deinit', 'wgl_close', 'free'])
            self.assertIsNone(self.core.dll)

    def test_uninitialized_core_never_unloads_or_deinitializes(self):
        self.core._game_loaded = self.core._initialized = False
        self.close(); self.assertEqual(self.events, ['free'])

    def test_failed_load_only_deinitializes(self):
        self.core._game_loaded = False
        self.close(); self.assertEqual(self.events, ['deinit', 'free'])

    def test_close_twice_never_repeats_native_calls(self):
        self.close(); self.close()
        self.assertEqual(self.events, ['unload', 'deinit', 'free'])
        self.assertIsNone(self.core._game_data_buffer)

    def test_free_failure_keeps_dll_callbacks_and_retries_only_free(self):
        self.kernel.FreeLibrary = lambda handle: self.events.append('free_fail') or False
        self.close()
        self.assertIs(lifecycle._retained[id(self.core)], self.core)
        self.assertIsNotNone(self.core.dll)
        self.assertEqual(self.core._game_data_buffer, b'ROM')
        self.kernel.FreeLibrary = lambda handle: self.events.append('free') or True
        self.close()
        self.assertEqual(self.events, ['unload', 'deinit', 'free_fail', 'free'])
        self.assertNotIn(id(self.core), lifecycle._retained)

    def test_native_cleanup_failure_keeps_callback_lifetime_and_no_retry(self):
        for phase in ('retro_unload_game', 'retro_deinit'):
            self.setUp(); self.hw()
            def fail(): raise OSError('native fault')
            setattr(self.core.dll, phase, fail)
            self.close(); count = len(self.events); self.close()
            self.assertEqual(len(self.events), count)
            self.assertTrue(self.core._cleanup_requires_recycle)
            self.assertIsNotNone(self.core.dll)
            self.assertIsNotNone(self.core.hw_context)
            self.assertNotIn('free', self.events)

    def test_wgl_failure_keeps_ownership_and_retry_does_not_repeat_native(self):
        self.hw(); self.core.hw_context.close = lambda: False
        self.close()
        self.assertIsNotNone(self.core.hw_context)
        self.assertIsNotNone(self.core.dll)
        self.core.hw_context.close = lambda: True
        self.close()
        self.assertEqual(self.events.count('unload'), 1)
        self.assertEqual(self.events.count('deinit'), 1)
        self.assertEqual(self.events.count('destroy_callback'), 1)
        self.assertIsNone(self.core.dll)

    def test_failed_context_activation_never_calls_destroy_callback(self):
        self.hw(); self.core.destroy_hw_before_unload = True
        self.core.hw_context.make_current = lambda: False
        self.close()
        self.assertEqual(self.events, [])
        self.assertTrue(self.core._cleanup_uncertain)

    def test_uncertain_native_initialization_retains_until_process_exit(self):
        lifecycle.retain_uncertain(self.core, 'init raised')
        self.close()
        self.assertEqual(self.events, [])
        self.assertIs(lifecycle._retained[id(self.core)], self.core)

    def test_native_load_exception_marks_real_wrapper_uncertain(self):
        from test_frame_boundaries import TYPES, new_core
        core = new_core(TYPES[1])
        self.addCleanup(lifecycle._retained.pop, id(core), None)
        core._prepare_game_info = lambda path: __import__('libretro_abi').RetroGameInfo()
        def fail(pointer): raise OSError('load exception')
        core.dll = SimpleNamespace(retro_load_game=fail)
        with self.assertRaisesRegex(OSError, 'load exception'):
            core.load_game(Path('unused'))
        self.assertFalse(core._in_load_game)
        self.assertTrue(core._cleanup_uncertain)
        self.assertTrue(core._cleanup_requires_recycle)

    def test_free_exception_retains_dll(self):
        def fail(handle): raise OSError('unload error')
        self.kernel.FreeLibrary = fail
        self.close()
        self.assertIsNotNone(self.core.dll)
        self.assertIs(lifecycle._retained[id(self.core)], self.core)


class ConfigSafetyTests(unittest.TestCase):
    def test_parent_and_child_agree_on_failures_and_valid_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'config.json'
            for value in ('{}', '{"cycle_seconds":180}', '[]', 'null', '"text"', '{'):
                path.write_text(value, encoding='utf-8')
                result = []
                for call in (lambda: load_config(path), lambda: load_supervisor_config([], root)):
                    try: result.append(('value', call()))
                    except Exception as exc: result.append(('error', type(exc)))
                self.assertEqual(result[0], result[1])
                if value in ('[]', 'null', '"text"', '{'):
                    self.assertEqual(result[0][0], 'error')

    def test_cycle_default_uses_parent_and_explicit_values_unchanged(self):
        self.assertEqual(DEFAULT_CYCLE_SECONDS, 240)
        self.assertEqual(duration_seconds({'independent_jitter_seconds': 0}), 240)
        self.assertEqual(cycle_settings({}, SimpleNamespace(cycle_seconds=None), False)[1], 240)
        self.assertEqual(duration_seconds({'cycle_seconds': 180, 'independent_jitter_seconds': 0}), 180)

    def test_parent_config_load_precedes_backdrop_and_worker_creation(self):
        tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        fn = next(node for node in tree.body if getattr(node, 'name', '') == 'supervisor_main')
        calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call)]
        load = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'load_supervisor_config')
        create = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'create_supervisor_backdrop')
        self.assertLess(load.lineno, create.lineno)


if __name__ == '__main__': unittest.main()
