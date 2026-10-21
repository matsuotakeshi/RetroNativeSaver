"""Machine selection, inheritance and multi-file save failure coverage."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch, Mock

from settings_store import SettingsDocument, updated_config
from system_settings import SystemDraft, update_system, load_drafts, REMOVE


class SystemDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'ps2.json'
        self.data = dict(id='ps2', name='PS2', core='core.dll', rom_dir='roms', enabled=True,
                         cycle_seconds=240, independent_jitter_seconds=24, system_dir='bios',
                         resource_group='heavy_cd', resource_weight=2, disk_boot_mode='special-old-mode',
                         core_options={'one': 'old', 'legacy': 123, 'unknown': {'keep': True}},
                         unknown={'value': ['日本語', False]})
        self.path.write_bytes((json.dumps(self.data, ensure_ascii=False, indent=2) + '\r\n').encode('utf-8'))
        self.raw = self.path.read_bytes()
        self.draft = SystemDraft(self.path, {'cycle_seconds': 150})

    def test_unedited_roundtrip_preserves_unknowns_and_special_modes(self):
        self.assertEqual(self.draft.changes(), {})
        self.assertIsNone(self.draft.document.save(self.draft.changes()))
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertNotIn('_config_path', self.draft.document.data)

    def test_inherited_values_remove_keys_instead_of_writing_null(self):
        self.draft.inherited[('cycle_seconds',)] = True
        self.draft.inherited[('system_dir',)] = True
        backup = self.draft.document.save(self.draft.changes())
        result = json.loads(self.path.read_bytes())
        expected = deepcopy(self.data)
        del expected['cycle_seconds'], expected['system_dir']
        self.assertEqual(result, expected)
        self.assertEqual(backup.read_bytes(), self.raw)

    def test_explicit_same_as_common_is_still_an_override(self):
        draft = SystemDraft(self.path, {'save_dir': 'shared'})
        draft.inherited[('save_dir',)] = False
        self.assertEqual(draft.changes(), {('save_dir',): 'shared'})
        draft.document.save(draft.changes())
        self.assertEqual(json.loads(self.path.read_bytes())['save_dir'], 'shared')

    def test_only_one_core_option_changes_preserving_original_types(self):
        self.draft.options['one'] = 'new'
        self.draft.options['added'] = 'yes'
        del self.draft.options['legacy']
        self.draft.document.save(self.draft.changes())
        result = json.loads(self.path.read_bytes())
        self.assertEqual(result['core_options'], {'one': 'new', 'added': 'yes', 'unknown': {'keep': True}})
        self.assertEqual(result['unknown'], self.data['unknown'])
        self.assertEqual(result['disk_boot_mode'], self.data['disk_boot_mode'])

    def test_list_edit_keeps_spaces_inside_exclusion_strings(self):
        result = update_system(self.data, {('extensions',): '.zip, chd; .cue', ('exclude_name_contains',): '[BIOS]\nBoot ROM\n日本語'})
        self.assertEqual(result['extensions'], ['.zip', '.chd', '.cue'])
        self.assertEqual(result['exclude_name_contains'], ['[BIOS]', 'Boot ROM', '日本語'])

    def test_invalid_edits_and_identity_change_rejected(self):
        cases = [(('resource_weight',), '1.5'), (('cycle_seconds',), 'nan'), (('max_concurrent',), -1),
                 (('core',), ''), (('system_dir',), ''), (('extensions',), '*.zip'),
                 (('render_backend',), 'unknown'), (('core_options', 'bad\nname'), 'x'),
                 (('core_options', 'one'), 'bad\nvalue'), (('enabled',), REMOVE)]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                update_system(self.data, {key: value})
        with self.assertRaises(KeyError):
            update_system(self.data, {('id',): 'different'})

    def test_broken_file_is_listed_without_hiding_valid_machine(self):
        (self.root / 'broken.json').write_text('{invalid', encoding='utf-8')
        folder, entries = load_drafts(self.root, {'systems_dir': str(self.root)})
        self.assertEqual(len(entries), 2)
        self.assertEqual(sum(draft is not None for _, draft, _ in entries), 1)
        self.assertTrue(any('broken.json' in label and error for label, _, error in entries))

    def test_all_38_examples_open_without_inserting_defaults(self):
        examples = Path(__file__).with_name('systems.example')
        paths = list(examples.glob('*.json'))
        self.assertEqual(len(paths), 38)
        for path in paths:
            target = self.root / path.name
            shutil.copy2(path, target)
            draft = SystemDraft(target, {})
            self.assertEqual(draft.changes(), {}, path.name)
            draft.document.save(draft.changes())
            self.assertEqual(target.read_bytes(), path.read_bytes(), path.name)

    def test_retroarch_path_is_a_text_path_and_empty_retains_auto_detection(self):
        for value in ('C:/Retro Arch/retroarch.exe', ''):
            self.assertEqual(updated_config({}, {('retroarch_path',): value}), {'retroarch_path': value})
        with self.assertRaisesRegex(ValueError, 'パス'):
            updated_config({}, {('retroarch_path',): 'bad\npath'})


class SystemEditorTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from settings_dialog import SettingsDialog
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root_dir = Path(self.temp.name)
        systems = self.root_dir / 'machines'
        systems.mkdir()
        self.files = [systems / 'a.json', systems / 'b.json']
        for sid, path in zip(('gb', 'ps2'), self.files):
            path.write_text(json.dumps(dict(id=sid, name=sid, core='core.dll', rom_dir='roms',
                cycle_seconds=180, core_options={'option': 'old'}, other=['keep'])), encoding='utf-8')
        self.config = self.root_dir / 'custom.json'
        self.config.write_text(json.dumps({'systems_dir': 'machines', 'cycle_seconds': 150, 'unknown': 9}), encoding='utf-8')
        self.originals = {p: p.read_bytes() for p in [self.config, *self.files]}
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy)
        self.form = SettingsDialog(self.root, self.root_dir, SettingsDocument(self.config))
        self.editor = self.form.system_editor

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def select(self, index):
        self.editor.choice.current(index)
        self.editor.select()

    def assert_originals(self):
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw, path.name)

    def test_switching_preserves_unsaved_edits_and_does_not_write(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.select(1)
        self.editor.variables[('cycle_seconds',)].set('330')
        self.select(0)
        self.assertEqual(self.editor.variables[('cycle_seconds',)].get(), '210')
        self.assert_originals()
        self.form.cancel()
        self.assert_originals()

    def test_apply_saves_both_machines_and_retroarch_only_edited_values(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.select(1)
        self.editor.variables[('cycle_seconds',)].set('330')
        self.form.variables[('retroarch_path',)].set('C:/Retro Arch/retroarch.exe')
        self.assertTrue(self.form.apply())
        for path, value in zip(self.files, (210, 330)):
            expected = dict(json.loads(self.originals[path]), cycle_seconds=value)
            self.assertEqual(json.loads(path.read_bytes()), expected)
            self.assertEqual(next(path.parent.glob(path.name + '.bak-*')).read_bytes(), self.originals[path])
        self.assertEqual(json.loads(self.config.read_bytes())['retroarch_path'], 'C:/Retro Arch/retroarch.exe')
        self.assertFalse(self.editor.plans())
        self.assertFalse(self.form.changes())

    def test_invalid_later_machine_prevents_all_writes(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.select(1)
        self.editor.variables[('cycle_seconds',)].set('invalid')
        self.form.variables[('retroarch_path',)].set('other.exe')
        with patch('tkinter.messagebox.showerror') as error:
            self.assertFalse(self.form.apply())
        self.assertIn('b.json', error.call_args.args[1])
        self.assert_originals()
        self.assertFalse(list(self.root_dir.rglob('*.bak-*')))

    def test_external_edit_to_later_file_prevents_all_our_writes(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.select(1)
        self.editor.variables[('cycle_seconds',)].set('330')
        self.files[1].write_text('{"external":true}', encoding='utf-8')
        with patch('tkinter.messagebox.showerror'):
            self.assertFalse(self.form.apply())
        self.assertEqual(self.files[0].read_bytes(), self.originals[self.files[0]])
        self.assertEqual(json.loads(self.files[1].read_bytes()), {'external': True})

    def test_write_failure_reports_partial_save_and_keeps_pending_draft(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.select(1)
        self.editor.variables[('cycle_seconds',)].set('330')
        real_replace = os.replace
        def replace(src, dst):
            if Path(dst) == self.files[1]:
                raise OSError('simulated disk error')
            return real_replace(src, dst)
        with patch('settings_store.os.replace', side_effect=replace), patch('tkinter.messagebox.showerror') as error:
            self.assertFalse(self.form.apply())
        self.assertIn('保存済み', error.call_args.args[1])
        self.assertEqual(json.loads(self.files[0].read_bytes())['cycle_seconds'], 210)
        self.assertEqual(self.files[1].read_bytes(), self.originals[self.files[1]])
        self.assertEqual(len(self.editor.plans()), 1)
        self.assertTrue(self.form.apply())
        self.assertEqual(json.loads(self.files[1].read_bytes())['cycle_seconds'], 330)

    def test_return_to_common_removes_only_override(self):
        self.editor.inherited[('cycle_seconds',)].set(True)
        self.assertTrue(self.form.apply())
        data = json.loads(self.files[0].read_bytes())
        self.assertNotIn('cycle_seconds', data)
        self.assertEqual(data['id'], 'gb')
        self.assertEqual(self.editor.variables[('cycle_seconds',)].get(), '150')
        self.form.variables[('cycle_seconds',)].set('200')
        self.assertTrue(self.form.apply())
        self.assertEqual(self.editor.variables[('cycle_seconds',)].get(), '200')

    def test_core_option_edits_survive_switch_and_save(self):
        self.editor.options.selection_set('0')
        with patch('tkinter.simpledialog.askstring', return_value='new'):
            self.editor.edit_option()
        with patch('tkinter.simpledialog.askstring', side_effect=['added', 'yes']):
            self.editor.add_option()
        self.select(1)
        self.select(0)
        self.assertEqual(self.editor.current.options, {'option': 'new', 'added': 'yes'})
        self.assertTrue(self.form.apply())
        self.assertEqual(json.loads(self.files[0].read_bytes())['core_options'], {'option': 'new', 'added': 'yes'})

    def test_rom_changes_show_catalog_reminder_but_time_edits_do_not(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.assertTrue(self.form.apply())
        self.assertFalse(self.form.catalog_needs_update)
        self.editor.variables[('rom_dir',)].set('new rom folder')
        self.assertTrue(self.form.apply())
        self.assertTrue(self.form.catalog_needs_update)
        self.assertIn('ROM一覧を更新', self.form.status.get())

    def test_catalog_update_blocks_saving_until_completion_is_collected(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        self.form.processes['catalog'] = Mock(poll=Mock(return_value=None))
        with patch('tkinter.messagebox.showinfo'):
            self.assertFalse(self.form.apply())
        self.assert_originals()

    def test_system_only_changes_trigger_save_prompt_for_management(self):
        self.editor.variables[('cycle_seconds',)].set('210')
        with patch('tkinter.messagebox.askyesnocancel', return_value=None) as prompt, patch('settings_dialog.subprocess.Popen') as launch:
            self.form.launch_management('favorites')
        prompt.assert_called_once()
        launch.assert_not_called()
        self.assert_originals()

    def test_exe_browse_is_available_and_saved_path_drives_existing_handoff(self):
        from system_settings_editor import browse_path
        from retroarch_launch import validate_pick
        exe = self.root_dir / 'My RetroArch.exe'
        core = self.root_dir / 'core.dll'
        rom = self.root_dir / 'game.rom'
        for path in (exe, core, rom):
            path.touch()
        var = self.form.variables[('retroarch_path',)]
        with patch('tkinter.filedialog.askopenfilename', return_value=str(exe)) as chooser:
            browse_path(self.root, var, 'exe', self.root_dir)
        self.assertIn(('実行ファイル', '*.exe'), chooser.call_args.kwargs['filetypes'])
        self.assertTrue(self.form.apply())
        cfg = json.loads(self.config.read_bytes())
        self.assertEqual(validate_pick({'id': 'gb', 'core': str(core)}, rom, cfg, self.root_dir)['exe'], exe)


if __name__ == '__main__':
    unittest.main()
