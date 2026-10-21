"""Configuration round trips and the real Tk form, without starting emulators."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from settings_store import (SettingsDocument, display_values, group_rows, updated_config,
                            FIELDS, WEIGHTS, DISABLED)
from settings_dialog import parse_config_args, management_command, SettingsDialog


class SettingsDocumentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / '設定.json'
        self.config = {'cycle_seconds': 180, 'other': {'preserve': [1, '日本語', None]},
                       'overlay': {'custom': 9}, 'single_system_mode': {'normal_weight': 15, 'grouped_weight': 85,
                       'groups': [['pcengine', 'pcenginecd']], 'disabled_systems': ['fbneo'],
                       'resource_groups': {'heavy_cd': {'max_weight': 64}}}}
        self.path.write_bytes((json.dumps(self.config, ensure_ascii=False, indent=4) + '\r\n').encode('utf-8'))
        self.original = self.path.read_bytes()
        self.document = SettingsDocument(self.path)

    def test_noop_does_not_reformat_create_keys_or_backup(self):
        self.assertIsNone(self.document.save({}))
        self.assertIsNone(self.document.save({('cycle_seconds',): '180'}))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_nested_delta_preserves_unknown_values_membership_and_resources(self):
        backup = self.document.save({('overlay', 'enabled'): False, ('log_output_enabled',): True})
        expected = dict(self.config, overlay={'custom': 9, 'enabled': False}, log_output_enabled=True)
        self.assertEqual(json.loads(self.path.read_bytes()), expected)
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertNotIn(b'\n', self.path.read_bytes().replace(b'\r\n', b''))
        self.assertIsNone(self.document.save({('log_output_enabled',): True}))

    def test_external_change_is_not_overwritten(self):
        self.path.write_text('{"outside": true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '別の操作'):
            self.document.save({('cycle_seconds',): 200})
        self.assertEqual(json.loads(self.path.read_bytes()), {'outside': True})

    def test_replace_failure_leaves_original_and_no_tempfile(self):
        with patch('settings_store.os.replace', side_effect=OSError('readonly')):
            with self.assertRaises(OSError):
                self.document.save({('cycle_seconds',): 200})
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))
        self.assertEqual(next(self.path.parent.glob('*.bak-*')).read_bytes(), self.original)

    def test_repeat_apply_backs_up_each_saved_version(self):
        self.document.save({('cycle_seconds',): 200})
        intermediate = self.path.read_bytes()
        backup = self.document.save({('cycle_seconds',): 250})
        self.assertEqual(backup.read_bytes(), intermediate)

    def test_invalid_root_and_missing_config_never_create_defaults(self):
        for content in ('[]', '{bad', 'null'):
            self.path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                SettingsDocument(self.path)
            self.assertEqual(self.path.read_text(encoding='utf-8'), content)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            SettingsDocument(self.path)
        self.assertFalse(self.path.exists())

    def test_invalid_values_rejected_without_write(self):
        cases = [(('cycle_seconds',), 'nan'), (('cycle_seconds',), 0),
                 (('independent_max_fps',), 'inf'), (('fade_duration_ms',), '1.2'),
                 (('overlay', 'background_alpha'), 256), (('overlay', 'system_color'), '#xyz'),
                 (('log_output_enabled',), 'false'), (('max_slots_per_monitor',), True)]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.document.save({key: value})
            self.assertEqual(self.path.read_bytes(), self.original)

    def test_zero_both_weights_rejected(self):
        with self.assertRaises(ValueError):
            self.document.save({WEIGHTS[0]: 0, WEIGHTS[1]: 0})
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_legacy_probability_and_systems_remain_unmodified(self):
        cfg = {'single_system_mode': {'probability': .75, 'systems': ['gb', 'gbc']}}
        values = display_values(cfg)
        self.assertEqual((values[WEIGHTS[0]], values[WEIGHTS[1]]), (25, 75))
        self.assertEqual(group_rows(cfg), [['gb'], ['gbc']])
        changed = updated_config(cfg, {('log_output_enabled',): True})
        self.assertEqual(changed['single_system_mode'], cfg['single_system_mode'])

    def test_invalid_nested_parent_is_not_replaced(self):
        with self.assertRaises(ValueError):
            updated_config({'overlay': 'legacy'}, {('overlay', 'enabled'): True})
        self.assertEqual(updated_config({'overlay': 'legacy'}, {('log_output_enabled',): True}),
                         {'overlay': 'legacy', 'log_output_enabled': True})

    def test_group_list_retains_disabled_members_and_alias(self):
        cfg = {'single_system_mode': {'groups': [['pcengine', 'cdrom2'], ['fbneo']], 'disabled_systems': ['fbneo']}}
        self.assertEqual(group_rows(cfg), [['pcengine', 'cdrom2'], ['fbneo']])
        self.assertEqual(updated_config(cfg, {DISABLED: []})['single_system_mode']['groups'], cfg['single_system_mode']['groups'])

    def test_missing_defaults_match_runtime_without_creating_keys(self):
        values = display_values({})
        self.assertEqual(values[('cycle_seconds',)], 240)
        self.assertEqual(values[('independent_jitter_seconds',)], 60)
        self.assertFalse(values[('independent_slots_enabled',)])
        self.assertFalse(values[('saver_controls_enabled',)])
        self.assertFalse(values[('log_output_enabled',)])


class SettingsLaunchTests(unittest.TestCase):
    def test_config_switch_handles_decimal_hex_and_invalid_owner(self):
        for args, expected in [(['/c'], None), (['/c:123'], 123), (['-C', '000123'], 123),
                               (['/C:0x123456789'], 0x123456789), (['/c', '--config', 'a.json'], None),
                               (['/c:garbage'], None), (['/c:-1'], None), (['/c:0'], None)]:
            self.assertEqual(parse_config_args(args, Path.cwd())[1], expected)

    def test_custom_config_path_with_owner(self):
        path, owner = parse_config_args(['/c:123', '--config', 'custom.json'], Path.cwd())
        self.assertEqual(path, (Path.cwd() / 'custom.json').resolve())
        self.assertEqual(owner, 123)

    def test_source_and_frozen_management_keep_custom_config(self):
        for frozen in (False, True):
            with patch('settings_dialog.sys.frozen', frozen, create=True):
                for action, flag in [('favorites', '--favorites'), ('rom_lists', '--rom-lists'), ('catalog', '--update-rom-catalog')]:
                    command = management_command(Path.cwd(), 'custom.json', action)
                    self.assertEqual(command[-3:], [flag, '--config', 'custom.json'])
                    self.assertEqual(len(command), 4 if frozen else 5)

    def test_main_config_route_returns_without_runtime_preparation(self):
        tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body if getattr(node, 'name', '') == 'main')
        import sys
        namespace = {'sys': sys, 'parse_screensaver_args': lambda a: ('config', None, []), 'show_config_dialog': Mock(return_value=7)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<config route>', 'exec'), namespace)
        self.assertEqual(namespace['main'](), 7)
        namespace['show_config_dialog'].assert_called_once_with()


class SettingsTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'config.json'
        self.path.write_text(json.dumps({'single_system_mode': {'probability': .75, 'groups': [['gb', 'gbc']], 'disabled_systems': ['fbneo']}, 'custom': 7}), encoding='utf-8')
        self.original = self.path.read_bytes()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy)
        self.form = SettingsDialog(self.root, Path(self.folder.name), SettingsDocument(self.path))

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_open_cancel_preserves_exact_file(self):
        self.form.variables[('cycle_seconds',)].set('180')
        self.form.cancel()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_noop_apply_has_no_side_effects(self):
        self.assertTrue(self.form.apply())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_edit_log_only_leaves_legacy_and_unknowns_untouched(self):
        self.form.variables[('log_output_enabled',)].set(True)
        self.assertTrue(self.form.apply())
        expected = dict(json.loads(self.original), log_output_enabled=True)
        self.assertEqual(json.loads(self.path.read_bytes()), expected)
        self.assertEqual(self.form.changes(), {})

    def test_strict_boolean_display_matches_runtime_without_rewriting_legacy(self):
        self.path.write_text('{"log_output_enabled":"true","single_system_mode":{"enabled":"true"}}', encoding='utf-8')
        original = self.path.read_bytes()
        form = SettingsDialog(self.root, self.path.parent, SettingsDocument(self.path))
        self.assertFalse(form.variables[('log_output_enabled',)].get())
        self.assertFalse(form.variables[('single_system_mode', 'enabled')].get())
        self.assertTrue(form.apply())
        self.assertEqual(self.path.read_bytes(), original)

    def test_legacy_ratio_edit_saves_both_weights(self):
        self.form.variables[WEIGHTS[0]].set('50')
        self.assertTrue(self.form.apply())
        cfg = json.loads(self.path.read_bytes())['single_system_mode']
        self.assertEqual((cfg['normal_weight'], cfg['grouped_weight']), (50, 75))
        self.assertEqual(cfg['probability'], .75)

    def test_group_enable_does_not_remove_unlisted_disabled_system(self):
        self.form.member_variables[0][1].set(False)
        self.assertTrue(self.form.apply())
        self.assertEqual(json.loads(self.path.read_bytes())['single_system_mode']['disabled_systems'], ['fbneo', 'gb'])

    def test_invalid_apply_keeps_file_and_form_open(self):
        self.form.variables[('cycle_seconds',)].set('nonsense')
        with patch('tkinter.messagebox.showerror') as error:
            self.assertFalse(self.form.apply())
        error.assert_called_once()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(self.root.winfo_exists())

    def test_management_uses_saved_config_and_cleans_worker_environment(self):
        with patch('settings_dialog.subprocess.Popen') as popen, patch.dict(os.environ, RNS_LOG_OUTPUT='1', RNS_WORKER_CONFIG_SNAPSHOT='old'):
            self.form.launch_management('favorites')
        kwargs = popen.call_args.kwargs
        self.assertNotIn('RNS_LOG_OUTPUT', kwargs['env'])
        self.assertNotIn('RNS_WORKER_CONFIG_SNAPSHOT', kwargs['env'])
        self.assertEqual(popen.call_args.args[0][-1], str(self.path.resolve()))

    @unittest.skipUnless(os.name == 'nt', 'Windows external owner')
    def test_external_owner_survives_first_show(self):
        import ctypes as C
        from ctypes import wintypes as W
        import tkinter as tk
        from settings_dialog import show_settings_dialog
        user = C.WinDLL('user32')
        user.GetAncestor.argtypes, user.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
        user.GetWindow.argtypes, user.GetWindow.restype = [W.HWND, W.UINT], W.HWND
        self.root.update_idletasks()
        owner = user.GetAncestor(self.root.winfo_id(), 2)
        child = tk.Tk()
        observed = []
        def observe():
            observed.append(user.GetWindow(user.GetAncestor(child.winfo_id(), 2), 4))
            child.quit()
        child.after(100, observe)
        with patch('tkinter.Tk', return_value=child):
            show_settings_dialog(self.path.parent, self.path, owner)
        self.assertEqual(observed, [owner])


if __name__ == '__main__':
    unittest.main()
