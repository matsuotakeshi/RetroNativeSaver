import ast
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from independent_slots import run_slot, select_slot
from runtime_policy import FramePacer, persistent_failure, watchdog_timeout


class RuntimePolicyTests(unittest.TestCase):
    def test_only_runtime_native_faults_are_durable(self):
        for phase in ('START_ENTER', 'START_FAILED', 'START_NATIVE_FAULT', 'SLOT_START', ''):
            self.assertFalse(persistent_failure({'phase': phase}, 0xC0000005))
        for code in (None, 0, 76, 1):
            self.assertFalse(persistent_failure({'phase': 'RUN_ENTER'}, code))
        self.assertTrue(persistent_failure({'phase': 'RUN_ENTER'}, -1073741819))
        self.assertTrue(persistent_failure({'phase': 'SLOT_RUNNING'}, 0xC0000374))

    def test_scheduler_keeps_transient_failures_session_only(self):
        tree = ast.parse(Path(__file__).with_name('independent_slots.py').read_text(encoding='utf-8'))
        scheduler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_scheduler')
        node = next(n for n in scheduler.body if isinstance(n, ast.FunctionDef) and n.name == 'fail')
        api = Mock()
        api._rom_in_name_map.return_value = False
        ns = dict(api=api, cfg={}, banned=set(), failures={}, suspended=set(),
                  persistent_failure=persistent_failure, white={}, state={}, state_path='unused', session='test')
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<fail>', 'exec'), ns)
        record = dict(index=0, pick=({'id': 'pc98', 'name': 'PC98'}, Path('game.zip')))
        ns['fail'](record, {'phase': 'START_FAILED'}, 'exit=76', 76)
        ns['fail'](record, {'phase': 'RUN_ENTER'}, 'hang')
        api._record_persistent_rom_failure.assert_not_called()
        self.assertIn(('pc98', 'game.zip'), ns['banned'])
        ns['fail'](record, {'phase': 'RUN_ENTER'}, 'native', 0xC0000005)
        api._record_persistent_rom_failure.assert_called_once()

    def test_reservation_survives_many_independent_replacements(self):
        a = dict(id='a', name='A', max_concurrent=1, resource_group='heavy_cd', resource_weight=2)
        b = dict(id='b', name='B', max_concurrent=2, resource_group='heavy_cd', resource_weight=1)
        c = dict(id='c', name='C', max_concurrent=8)
        systems = [a, b, c]
        catalogs = {s['id']: [Path(s['id'])] for s in systems}
        favorites = [(a, Path('a')), (b, Path('b'))]
        cfg = {'resource_groups': {'heavy_cd': {'max_weight': 3}}}
        slots = [None] * 5
        rng = random.Random(92)
        for turn in range(500):
            index = 0 if turn % 4 == 0 else rng.randrange(1, 5)
            slots[index] = None
            pick = select_slot(index, systems, catalogs, cfg, [r for r in slots if r],
                               favorites, set(), set(), rng,
                               normal_occupied=[r for i, r in enumerate(slots) if i and r])
            slots[index] = pick
            if index == 0:
                self.assertIn(pick, favorites)
            running = [s for s, _ in filter(None, slots)]
            self.assertLessEqual(sum(s.get('resource_weight', 0) for s in running), 3)
            for s in systems:
                self.assertLessEqual(sum(r['id'] == s['id'] for r in running), s['max_concurrent'])

    def test_no_favorites_does_not_reserve_capacity(self):
        s = dict(id='a', name='A', max_concurrent=1)
        pick = select_slot(1, [s], {'a': [Path('a')]}, {}, [], [], set(), set(), normal_occupied=[])
        self.assertEqual(pick, (s, Path('a')))

    def test_preparation_and_scheduler_are_monitored_but_standby_is_not(self):
        for phase in ('WORKER_STARTING', 'CONFIG_LOAD', 'TITLE_CATALOG', 'ROM_CATALOG'):
            self.assertEqual(watchdog_timeout(phase, {}), 120)
        self.assertEqual(watchdog_timeout('ROM_CATALOG', {'worker_prepare_hang_timeout_seconds': 180}), 180)
        self.assertEqual(watchdog_timeout('SLOT_SCHEDULER', {}), 15)
        self.assertIsNone(watchdog_timeout('SLOT_POWER_IDLE', {}))

    def test_pacer_runs_sixty_frames_and_presents_twenty_five(self):
        pacer = FramePacer(60, 25, 0)
        now, presentations = 0., 0
        for _ in range(600):
            presentations += pacer.should_present(now)
            now += pacer.delay(now)
        self.assertAlmostEqual(now, 10)
        self.assertEqual(presentations, 250)

    def test_pacer_does_not_catch_up_after_long_stall(self):
        pacer = FramePacer(60, 25, 0)
        self.assertEqual(pacer.delay(20), 0)
        self.assertAlmostEqual(pacer.delay(20), 1 / 60)
        for bad in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                FramePacer(bad, 25, 0)

    def test_actual_tile_loop_separates_emulation_and_presentation(self):
        class ExitTile(Exception):
            pass
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / 'gate'
            gate.touch()
            spec = dict(system={'id': 'test', 'name': 'Test'}, rom='test.rom', index=0,
                        cfg={'independent_max_fps': 25, 'overlay': {'enabled': False}},
                        gate=str(gate), parent=1, hide_cursor=False, rect=[0, 0, 100, 100],
                        content_dir=tmp, duration=1, title='Test')
            path = root / 'spec.json'
            path.write_text(json.dumps(spec), encoding='utf-8')
            api = Mock()
            win = Mock(should_close=False, _startup_unfaded_slots=set(), _startup_presented_slots=set())
            win.client_size.return_value = (100, 100)
            api.GDIWindow.return_value = win
            core = Mock(frame_bytes=b'frame')
            av = SimpleNamespace(timing=SimpleNamespace(fps=60))
            api.start_slot_with_retry.return_value = (core, av, None, None)
            api.hard_exit_process.side_effect = ExitTile
            clock = [0.]
            def sleep(delay):
                clock[0] += delay
            with patch('independent_slots.time.monotonic', side_effect=lambda: clock[0]), patch('independent_slots.time.sleep', side_effect=sleep):
                with self.assertRaises(ExitTile):
                    run_slot(api, str(path))
            self.assertGreaterEqual(core.run_frame.call_count, 60)
            self.assertLessEqual(core.run_frame.call_count, 62)
            self.assertGreaterEqual(win.present.call_count, 25)
            self.assertLessEqual(win.present.call_count, 28)
            api.hard_exit_process.assert_called_once_with(75)


if __name__ == '__main__':
    unittest.main()
