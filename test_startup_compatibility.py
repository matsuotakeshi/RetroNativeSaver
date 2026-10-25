"""Compare complete startup/retry traces and prepared files with v0.20.68."""
import ast
import contextlib
import copy
import io
from pathlib import Path
import random
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import computer_disks
import memory_cards
import resource_policy


def functions(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'resolve_app_relative_path', 'prepare_dolphin_user_config', 'start_slot_with_retry'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    return compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec')


class WorkerExit(BaseException):
    pass


class StartupCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent
        cls.before = functions(root / 'tests_fixtures/legacy_startup_v068.py')
        cls.after = functions(root / 'native_saver.py')

    def run_case(self, code, changes=None, cfg=None, fail=None, recycle=False, worker=False, retry=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            def event(name, *args):
                events.append((name, args))
                if name == fail:
                    raise RuntimeError('injected ' + name)

            def isolate(system, source, slot):
                event('isolate', system, source, slot)
                target = slot / 'isolated-bios'
                target.mkdir()
                return target

            def cards(system, source, slot):
                event('cards', system, source, slot)
                target = slot / 'cards'
                target.mkdir()
                return target / 'system', target / 'save', dict(system.get('core_options') or {}, card='enabled')

            def attach(dll, ports):
                event('attach', dll, ports)

            def copy_core(source, target):
                event('copy', source, target)
                target.write_bytes(source.read_bytes())

            def rom(system, source, slot):
                event('rom', system, source, slot)
                return slot / source.name

            class Core:
                dll = 'fake DLL'
                def __init__(self, *args, **kwargs):
                    event('core', args, kwargs)
                def initialize(self):
                    event('initialize')
                def load_game(self, path):
                    event('load', path)
                    if retry and path.name == 'bad.chd':
                        raise RuntimeError('bad ROM')
                    return 'av'
                def close(self):
                    event('close')

            def hard_exit(code):
                event('exit', code)
                raise WorkerExit(code)

            ns = dict(Path=Path, random=random, shutil=SimpleNamespace(copy2=copy_core), APP_DIR=root,
                      LibretroCore=Core, prepare_rom=rom, is_native_access_violation=lambda exc:False,
                      write_runtime_trace=lambda phase, **kw:event('trace', phase, kw),
                      hard_exit_process=hard_exit, WORKER_RESTART_EXIT_CODE=75,
                      _resource_group_can_add=resource_policy._resource_group_can_add)
            exec(code, ns)
            real_resolve = ns['resolve_app_relative_path']
            def resolve(value, default):
                event('resolve', value, default)
                return real_resolve(value, default)
            ns['resolve_app_relative_path'] = resolve
            system = dict(id='test', name='Test', core=str(root/'core.dll'),
                          resource_group='heavy_cd', resource_weight=1,
                          process_recycle_required=recycle)
            system.update(copy.deepcopy(changes or {}))
            (root/'core.dll').write_bytes(b'fake core')
            cfg = copy.deepcopy(cfg or {})
            initial = copy.deepcopy((system, cfg))
            bad, good = Path('bad.chd'), Path('good.chd')
            failed = set()
            usage = {'heavy_cd':1}
            log = io.StringIO()
            random.seed(69)
            with contextlib.redirect_stdout(log), patch.object(computer_disks, 'isolated_system_dir', side_effect=isolate), patch.object(memory_cards, 'prepare', side_effect=cards), patch.object(memory_cards, 'attach_controller', side_effect=attach):
                try:
                    result = ns['start_slot_with_retry'](2, system, bad, [system], {system['id']:[bad,good]},
                        cfg, root, failed, max_attempts=2 if retry else 1, worker_mode=worker,
                        cycle_number=7, cycle_group_usage=usage,
                        favorite_retries=[(system,bad),(system,good)] if retry else None)
                    core, av, selected, selected_rom = result
                    startup = getattr(core, '_startup_input', None)
                    value = ('ok', av, selected, selected_rom,
                             getattr(core, 'display_aspect', None),
                             None if startup is None else (startup.delay_seconds,startup.count,getattr(core,'_startup_input_label',None)))
                except BaseException as exc:
                    value = ('error', type(exc).__name__, str(exc))
            self.assertEqual((system,cfg),initial)
            files = [(str(p.relative_to(root)), p.read_bytes().hex() if p.is_file() else 'dir')
                     for p in sorted(root.rglob('*'))]
            def normalize(value):
                if isinstance(value, Path): value = str(value)
                if isinstance(value, str): return value.replace(str(root), '<root>')
                if isinstance(value, dict): return {k:normalize(v) for k,v in value.items()}
                if isinstance(value, (list,tuple)): return [normalize(v) for v in value]
                if isinstance(value, set): return sorted(value)
                return value
            # New cleanup-phase telemetry is checked independently; preserve the other startup events.
            events = [e for e in events if not (e[0] == 'trace' and e[1][0] == 'START_CLOSE_ENTER')]
            return normalize((value,events,log.getvalue(),files,failed,usage,random.getstate()))

    def compare(self, **kwargs):
        expected = self.run_case(self.before, **kwargs)
        actual = self.run_case(self.after, **kwargs)
        self.assertEqual(actual, expected)
        return actual

    def test_save_precedence_defaults_and_invalid_settings(self):
        for changes in ({}, {'isolated_save_dir':True}, {'save_dir':'per-system'},
                        {'isolated_save_dir':True,'save_dir':'ignored'}, {'save_dir':''},
                        {'system_dir':None}, {'assets_dir':None}, {'core_options':None},
                        {'force_aspect_ratio':'bad'}, {'hw_context_width':'bad'}):
            for cfg in ({}, {'save_dir':'shared','system_dir':'bios','assets_dir':'assets'}, {'save_dir':None}):
                with self.subTest(changes=changes,cfg=cfg):
                    self.compare(changes=changes,cfg=cfg)
        result = self.compare()
        self.assertEqual([e[0] for e in result[1]], ['trace','copy','rom','resolve','core','initialize','load','trace'])

    def test_computer_bios_dolphin_and_card_preparation_order(self):
        for sid in ('pc88','pc98','x1','x68000','fm7','gamecube','wii','dreamcast','ps2'):
            for enabled in (False,True):
                changes=dict(id=sid,disk_boot_mode='computer_two_drives',isolated_save_dir=enabled,
                             dolphin_ini_core={'CPUThread':'False','SkipIPL':'True'},
                             saver_memory_cards=enabled,core_options={'existing':'value'})
                self.compare(changes=changes)
        result=self.compare(changes=dict(id='ps2',disk_boot_mode='computer_two_drives',dolphin_ini_core={'SkipIPL':'True'}))
        names=[e[0] for e in result[1]]
        self.assertLess(names.index('isolate'),names.index('resolve'))
        self.assertLess(names.index('cards'),names.index('core'))
        self.assertLess(names.index('load'),names.index('attach'))
        self.assertTrue(any('Dolphin.ini' in path for path,_ in result[3]))

    def test_failures_preserve_trace_close_and_worker_exit(self):
        for failure in ('copy','rom','isolate','resolve','cards','core','initialize','load','attach','close'):
            for recycle,worker in ((False,False),(True,False),(True,True)):
                with self.subTest(failure=failure,recycle=recycle,worker=worker):
                    self.compare(changes=dict(id='ps2',disk_boot_mode='computer_two_drives',
                                 force_aspect_ratio='bad' if failure=='close' else 0),
                                 fail=failure,recycle=recycle,worker=worker)

    def test_failed_favorite_retries_keep_resource_usage_and_random_state(self):
        result=self.compare(retry=True,changes=dict(id='megacd',isolated_save_dir=True))
        self.assertEqual(result[0][0],'ok')
        self.assertEqual(result[0][3],'good.chd')
        self.assertEqual(result[4],['bad.chd'])
        self.assertEqual(result[5],{'heavy_cd':1})
        names=[e[0] for e in result[1]]
        self.assertIn('close',names)
        self.assertEqual(names.count('core'),2)

    def test_startup_input_scope_and_disable_are_unchanged(self):
        for sid in ('megacd','pcenginecd','megadrive','pcengine'):
            for enabled in (True,False):
                result=self.compare(changes=dict(id=sid,startup_start_twice=enabled))
                self.assertEqual(result[0][-1], [5.0,0,sid] if enabled and sid in ('megacd','pcenginecd') else None)

    def test_dolphin_file_and_error_behavior(self):
        for values in ({},None,{'CPUThread':False,'SkipIPL':True,'Number':1},['invalid']):
            self.compare(changes=dict(dolphin_ini_core=values,isolated_save_dir=True))


if __name__ == '__main__':
    unittest.main()
