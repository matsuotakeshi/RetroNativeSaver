"""Characterize both existing title policies before changing their placement."""
import ast
import contextlib
import copy
import glob
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import favorite_titles
from title_metadata import display_system_name
from tests_fixtures import legacy_titles_v067 as legacy


def outcome(function, *args):
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        try:
            value = ('ok', function(*args))
        except Exception as exc:
            value = ('error', type(exc).__name__, str(exc))
    return value, log.getvalue()


class TitleCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        legacy.APP_DIR = self.root
        tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        names = {'_title_key', '_load_title_json', '_load_retroarch_playlist_titles',
                 'build_title_maps', 'resolve_display_title'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.runtime = dict(Path=Path, glob=glob, json=json, os=os, APP_DIR=self.root)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<runtime titles>', 'exec'), self.runtime)

    def compare_runtime(self, name, *args):
        expected = outcome(getattr(legacy, name), *args)
        self.assertEqual(outcome(self.runtime[name], *args), expected)
        return expected[0]

    def compare_favorites(self, name, *args):
        expected = outcome(getattr(legacy, name), *args)
        self.assertEqual(outcome(getattr(favorite_titles, name), *args), expected)
        return expected[0]

    def test_overlay_system_names_omit_known_core_annotations(self):
        for configured, expected in (
                ('PC-8801 (QUASI88)', 'PC-8801'),
                ('PC-9801 (Neko Project II Kai)', 'PC-9801'),
                ('Sharp X68000 (PX68k)', 'Sharp X68000'),
                ('FM-7 (MAME Current)', 'FM-7'),
                ('MAME Current', 'MAME'),
                ('FinalBurn Neo', 'FinalBurn Neo')):
            with self.subTest(configured=configured):
                self.assertEqual(display_system_name(configured), expected)

    def test_overlay_names_preserve_hardware_notes_and_custom_names(self):
        for name in ('', 'Super Famicom / SNES', 'MSX / MSX2', 'System (Japan)',
                     'My custom name', 'System (unknown core)', '保存失敗：ログを確認'):
            self.assertEqual(display_system_name(name), name)

    def test_key_normalization_keeps_runtime_and_editor_differences(self):
        values = [None, '', ' ', 0, False, ' SF2.ZIP ', r'C:\ROMs\SF2.zip#member.bin',
                  'folder\\', 'a/b.tar.gz', '.hidden', 'Straße.zip', 'ΟΣ.zip',
                  ' 日本語.ZIP ', 'a.zip#x#y', Path('folder/Game.chd')]
        for value in values:
            with self.subTest(value=value):
                self.compare_runtime('_title_key', value)
                self.compare_favorites('title_key', value)
        self.assertEqual(self.runtime['_title_key'](None), '')
        self.assertEqual(favorite_titles.title_key(None), 'none')
        self.assertEqual(self.runtime['_title_key']('Straße.zip'), 'straße')
        self.assertEqual(favorite_titles.title_key('Straße.zip'), 'strasse')

    def test_json_shapes_values_collisions_bom_and_invalid_input(self):
        db = self.root / 'titles.json'
        payloads = [None, [], 1, 'text', {}, {'titles': []},
                    {'SF2.zip': ' First ', 'sf2': 'Second', '': 'Empty key', 'null': None,
                     'number': 3, 'bool': False, 'list': ['x'], 'blank': '  '},
                    {'titles': {'SF2': '日本語', 'sf2.zip': 'Last'}, 'extra': 'Ignored'}]
        for payload in payloads:
            for encoding in ('utf-8', 'utf-8-sig'):
                db.write_text(json.dumps(payload, ensure_ascii=False), encoding=encoding)
                self.compare_runtime('_load_title_json', db)
                self.compare_favorites('load_titles', self.root, {'title_db': str(db)})
        for raw in (b'{invalid', b'\xff\xfe\x00'):
            db.write_bytes(raw)
            self.compare_runtime('_load_title_json', db)
            self.compare_favorites('load_titles', self.root, {'title_db': str(db)})
        db.unlink()
        self.compare_runtime('_load_title_json', db)
        self.compare_favorites('load_titles', self.root, {'title_db': str(db)})

    def test_read_failures_keep_logging_and_exception_boundaries(self):
        db = self.root / 'titles.json'
        db.touch()
        for error in (PermissionError('denied'), RuntimeError('unexpected')):
            with patch.object(Path, 'read_text', side_effect=error):
                self.compare_runtime('_load_title_json', db)
                result = self.compare_favorites('load_titles', self.root, {'title_db': str(db)})
                self.assertEqual(result[0], 'error' if isinstance(error, RuntimeError) else 'ok')

    def test_playlist_filters_roots_order_and_deduplication(self):
        first, second = self.root / 'first.lpl', self.root / 'second.lpl'
        items = [dict(path=r'C:\ROMs\arcade\SF2.zip#member', label='First', core_name='FBNeo'),
                 dict(path=r'C:\ROMs\arcade\other.zip', label='By root', core_name='Other'),
                 dict(path=r'C:\ROMs\arcade_extra\outside.zip', label='Outside', core_name='Other'),
                 dict(path='path/core.zip', label='By DLL', core_path='fbneo_libretro.dll'),
                 dict(path='detect.zip', label='DETECT'), dict(path='', label='Empty'),
                 dict(path='null.zip', label=None), dict(path='zero.zip', label=0),
                 dict(path='none.zip', core_name=None), 'invalid item', None]
        first.write_text(json.dumps({'items': items}), encoding='utf-8-sig')
        second.write_text(json.dumps({'items': [dict(path='sf2.zip', label='Second')]}), encoding='utf-8')
        with patch.dict(os.environ, {'RNS_TEST_ROOT': r'C:\ROMs\arcade'}):
            for filters in (None, [], ['fbneo'], [' fbneo '], [None], ['unmatched']):
                for roots in (None, [], [r'C:\ROMs\arcade'], ['%RNS_TEST_ROOT%'], [None]):
                    for files in ([first, second, first], [second, first]):
                        with patch.object(glob, 'glob', return_value=[str(p) for p in files]):
                            self.compare_runtime('_load_retroarch_playlist_titles', ['*.lpl', '*.lpl'], filters, roots)

    def test_playlist_invalid_files_and_item_shapes(self):
        p = self.root / 'test.lpl'
        for data in [None, [], {'items': None}, {'items': {}}, {'items': [[], 3, {}]}]:
            p.write_text(json.dumps(data), encoding='utf-8')
            self.compare_runtime('_load_retroarch_playlist_titles', [str(p)])
        p.write_text('{broken', encoding='utf-8')
        self.compare_runtime('_load_retroarch_playlist_titles', [str(p), str(self.root)])
        with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            self.compare_runtime('_load_retroarch_playlist_titles', [str(p)])

    def test_generated_playlist_cases(self):
        rng = random.Random(67)
        p = self.root / 'random.lpl'
        choices = [None, '', 'DETECT', ' Game ', 1, False, ['value']]
        for _ in range(60):
            items = [dict(path=rng.choice(['sf2.zip', 'SF2.ZIP#member', 'other.zip', None]),
                          label=rng.choice(choices), core_name=rng.choice(choices),
                          core_path=rng.choice(choices)) for _ in range(20)]
            p.write_text(json.dumps({'items': items}), encoding='utf-8')
            self.compare_runtime('_load_retroarch_playlist_titles', [str(p)], rng.choice([[], ['game'], [1]]))

    def test_merge_priority_relative_paths_duplicate_ids_and_logs(self):
        (self.root / 'db.json').write_text(json.dumps({'sf2': 'JSON wins'}), encoding='utf-8')
        p = self.root / 'list.lpl'
        p.write_text(json.dumps({'items': [dict(path='sf2.zip', label='Playlist'),
                                          dict(path='extra.zip', label='Extra')]}), encoding='utf-8')
        systems = [dict(id=' arcade ', name='Arcade', title_db='db.json', title_sources=[str(p)]),
                   dict(id='missing', title_db='absent.json'), dict(id=''), dict(id=None),
                   dict(id='arcade', name='Repeated', title_sources=[str(p)])]
        before = copy.deepcopy(systems)
        self.compare_runtime('build_title_maps', systems)
        self.assertEqual(systems, before)
        result = self.compare_runtime('build_title_maps', systems[:1])[1]
        self.assertEqual(result['arcade'], {'sf2': 'JSON wins', 'extra': 'Extra'})
        for db_name in [str(self.root / 'db.json'), '%RNS_TITLE_HOME%/db.json']:
            with patch.dict(os.environ, {'RNS_TITLE_HOME': str(self.root)}):
                self.compare_runtime('build_title_maps', [dict(id='x', title_db=db_name)])

    def test_editor_defaults_environment_paths_and_fallbacks(self):
        (self.root / 'metadata').mkdir()
        for name in ('fbneo', 'mame'):
            (self.root / f'metadata/{name}_titles.json').write_text('{"sf2":"Readable"}', encoding='utf-8')
        for system in [dict(id=sid) for sid in ['arcade', 'ARCADE', 'fbneo', 'mame', 'pcengine', None]]:
            self.compare_favorites('title_database', system)
            self.compare_favorites('load_titles', self.root, system)
        with patch.dict(os.environ, {'RNS_TITLE_HOME': str(self.root)}):
            self.compare_favorites('load_titles', self.root, {'id':'mame', 'title_db':'%RNS_TITLE_HOME%/metadata/fbneo_titles.json'})
        for rom in [Path('SF2.zip'), Path('missing.zip'), Path('Straße.zip')]:
            self.compare_runtime('resolve_display_title', {'id':'arcade'}, rom, {'arcade':{'sf2':'Readable'}})
            self.compare_favorites('display_title', rom, {'sf2':'Readable'})
        self.assertEqual(self.runtime['resolve_display_title']({'id':'x'}, Path('missing.zip'), {}), 'missing')
        self.assertEqual(favorite_titles.display_title(Path('missing.zip'), {}), 'missing.zip')


if __name__ == '__main__':
    unittest.main()
