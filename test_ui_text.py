"""Language selection, translated forms and unchanged user data."""
import ast
import json
from pathlib import Path
import re
import string
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import ui_text as ui
from settings_dialog import SettingsDialog
from settings_store import SettingsDocument, GENERAL
from system_settings import FIELDS


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(ui.set_language, ui._language)

    def test_windows_display_language_not_regional_format(self):
        api = Mock(return_value=0x0411)
        with patch.object(ui.ctypes, 'WinDLL', return_value=Mock(GetUserDefaultUILanguage=api), create=True):
            self.assertEqual(ui.configure({}), 'ja')
            api.return_value = 0x0409
            self.assertEqual(ui.configure({'ui_language': 'auto'}), 'en')
            api.return_value = 0x0804
            self.assertEqual(ui.configure({}), 'en')

    def test_explicit_language_and_invalid_legacy_value(self):
        with patch.object(ui, 'windows_language', return_value='en') as detect:
            self.assertEqual(ui.configure({'ui_language': 'ja'}), 'ja')
            detect.assert_not_called()
            for value in ('unknown', None, [], {}):
                self.assertEqual(ui.configure({'ui_language': value}), 'en')

    def test_failed_detection_falls_back_without_crashing(self):
        with patch.object(ui.ctypes, 'WinDLL', side_effect=OSError, create=True), patch.object(ui.locale, 'getlocale', side_effect=ValueError):
            self.assertEqual(ui.windows_language(), 'en')

    def test_translations_preserve_format_fields_and_user_text(self):
        formatter = string.Formatter()
        for source, target in ui.ENGLISH.items():
            self.assertEqual({p[1:] for p in formatter.parse(source) if p[1]},
                             {p[1:] for p in formatter.parse(target) if p[1]}, source)
        ui.set_language('en')
        self.assertEqual(ui.tr('お気に入りに追加 — {v0}', v0='日本語 {title}'), 'Add to Favorites — 日本語 {title}')
        ui.set_language('ja')
        self.assertEqual(ui.tr('お気に入りに追加 — {v0}', v0='日本語 {title}'), 'お気に入りに追加 — 日本語 {title}')

    def test_all_dialog_messages_and_field_labels_have_translations(self):
        modules = ('settings_dialog', 'settings_store', 'system_settings', 'system_settings_editor',
                   'favorites', 'favorite_input', 'favorite_input_editor', 'favorite_titles', 'rom_list_editor', 'native_saver')
        for name in modules:
            tree = ast.parse(Path(__file__).with_name(name + '.py').read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_tr':
                    if isinstance(node.args[0], ast.Constant):
                        self.assertIn(node.args[0].value, ui.ENGLISH, name)
        for field in (*GENERAL, *FIELDS):
            self.assertIn(field.label, ui.ENGLISH)


class LanguageFormTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(ui.set_language, ui._language)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder / 'systems').mkdir()
        self.system = self.folder / 'systems/test.json'
        self.system.write_text(json.dumps({'id': 'gb', 'name': '日本語の機種', 'core': 'core.dll', 'rom_dir': 'roms',
                                          'core_options': {'unchanged': '日本語'}}), encoding='utf-8')
        self.path = self.folder / 'config.json'
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def form(self, language=None):
        config = {'unknown': ['日本語', {'keep': True}]}
        if language is not None:
            config['ui_language'] = language
        self.path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        return SettingsDialog(self.root, self.folder, SettingsDocument(self.path))

    def test_english_form_noop_preserves_json_bytes(self):
        form = self.form('en')
        originals = [p.read_bytes() for p in (self.path, self.system)]
        self.assertEqual([form.notebook.tab(t, 'text') for t in form.notebook.tabs()],
                         ['General', 'Title Display', 'Grouped Display', 'Systems'])
        self.assertEqual(form.system_editor.tabs.tab(0, 'text'), 'Basic')
        self.assertTrue(form.apply())
        self.assertEqual([p.read_bytes() for p in (self.path, self.system)], originals)
        self.assertEqual(form.system_editor.variables[('name',)].get(), '日本語の機種')

    def test_japanese_form_and_auto_noop(self):
        with patch.object(ui, 'windows_language', return_value='ja'):
            form = self.form()
        original = self.path.read_bytes()
        self.assertEqual(form.notebook.tab(0, 'text'), '全般')
        self.assertEqual(form.variables[('ui_language',)].get(), ui.LANGUAGE_LABELS[0])
        self.assertTrue(form.apply())
        self.assertEqual(self.path.read_bytes(), original)

    def test_language_save_keeps_other_edits_and_switches_on_reopen(self):
        form = self.form('ja')
        form.variables[('ui_language',)].set('English')
        form.variables[('cycle_seconds',)].set('210')
        form.system_editor.variables[('cycle_seconds',)].set('330')
        form.system_editor.inherited[('cycle_seconds',)].set(False)
        self.assertTrue(form.apply())
        data = json.loads(self.path.read_bytes())
        self.assertEqual(data['ui_language'], 'en')
        self.assertEqual(data['cycle_seconds'], 210)
        self.assertEqual(json.loads(self.system.read_bytes())['cycle_seconds'], 330)
        self.assertEqual(data['unknown'], ['日本語', {'keep': True}])
        self.assertEqual(form.notebook.tab(0, 'text'), '全般')  # No mid-edit rebuild.
        for child in self.root.winfo_children():
            child.destroy()
        reopened = SettingsDialog(self.root, self.folder, SettingsDocument(self.path))
        self.assertEqual(reopened.notebook.tab(0, 'text'), 'General')
        self.assertEqual(ui.configure_from_path(self.path), 'en')  # Child management processes read this path.

    def test_cancel_does_not_save_language(self):
        form = self.form('ja')
        original = self.path.read_bytes()
        form.variables[('ui_language',)].set('English')
        with patch.object(self.root, 'destroy'):
            form.cancel()
        self.assertEqual(self.path.read_bytes(), original)

    def test_language_validation_and_external_conflict(self):
        form = self.form('en')
        with self.assertRaisesRegex(ValueError, 'Select a language'):
            form.document.save({('ui_language',): 'de'})
        self.path.write_text('{"external":true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
            form.document.save({('ui_language',): 'ja'})

    def test_input_editor_keeps_device_codes_in_both_languages(self):
        from favorite_input_editor import InputEditor
        from favorite_input import input_summary
        value = [{'delay_seconds': 5, 'device': 'joypad', 'key': 'Start'},
                 {'delay_seconds': 6, 'device': 'keyboard', 'key': 'Enter'}]
        for language in ('en', 'ja'):
            ui.set_language(language)
            editor = InputEditor(self.root)
            editor.load(value)
            editor.show_step(1)
            self.assertEqual(editor.value(), value)
            self.assertEqual(editor.device.get(), 'Keyboard' if language == 'en' else 'キーボード')
            self.assertIn('After 5s' if language == 'en' else '5秒後', input_summary(value))
            editor.destroy()

    def test_management_windows_follow_saved_language(self):
        from favorites import show_favorites_editor
        from rom_list_editor import show_rom_list_editor
        self.path.write_text('{"ui_language":"en"}', encoding='utf-8')
        ui.configure_from_path(self.path)
        with patch.object(tk, 'Tk', return_value=self.root), patch.object(self.root, 'mainloop'), patch.object(self.root, 'destroy'):
            show_favorites_editor(self.folder, self.folder / 'systems', self.folder / 'favorites.json')
            self.assertEqual(self.root.title(), 'Retro Native Saver — Favorites')
            for child in self.root.winfo_children():
                child.destroy()
            show_rom_list_editor(self.folder, self.path)
            self.assertEqual(self.root.title(), 'Retro Native Saver — Blacklist / Whitelist')
        self.assertFalse((self.folder / 'favorites.json').exists())
        self.assertFalse((self.folder / 'state').exists())


if __name__ == '__main__':
    unittest.main()
