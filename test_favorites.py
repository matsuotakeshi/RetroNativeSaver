from __future__ import annotations
import ast
import contextlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock, patch

from favorites import load_favorites, save_favorites, favorite_candidates


class FavoriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
                 (n.name.startswith('_resource_group_') or n.name in ('choose_slots', 'start_slot_with_retry'))]
        cls.ns = dict(random=random, Path=Path)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<selector>', 'exec'), cls.ns)

    def setUp(self):
        self.a = {'id': 'a', 'name': 'A', 'max_concurrent': 1}
        self.b = {'id': 'b', 'name': 'B', 'max_concurrent': 3}
        self.catalogs = {'a': [Path('one.zip'), Path('two.zip')], 'b': [Path('three.zip')]}

    def choose(self, favorites=None, cfg=None, count=4):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.ns['choose_slots']([self.a, self.b], self.catalogs, cfg or {}, count, favorites)

    def test_reserves_random_favorite_and_respects_system_cap(self):
        favorites = [(self.a, rom) for rom in self.catalogs['a']]
        seen = set()
        with patch.object(random, 'choice', side_effect=lambda seq: seq[0]):
            first = self.choose(favorites)
        with patch.object(random, 'choice', side_effect=lambda seq: seq[-1]):
            last = self.choose(favorites)
        for picks in (first, last):
            self.assertEqual(len(picks), 4)
            self.assertIn(picks[0], favorites)
            self.assertEqual(sum(s['id'] == 'a' for s, _ in picks), 1)
            seen.add(picks[0][1])
        self.assertEqual(seen, set(self.catalogs['a']))

    def test_favorite_reserves_resource_budget_before_random_picks(self):
        self.a.update(resource_group='heavy', resource_weight=2)
        self.b.update(resource_group='heavy', resource_weight=1)
        picks = self.choose([(self.a, Path('one.zip'))], {'resource_groups': {'heavy': {'max_weight': 3}}})
        self.assertEqual(picks[0][0]['id'], 'a')
        self.assertLessEqual(sum(s['resource_weight'] for s, _ in picks), 3)

    def test_impossible_favorite_keeps_limits_and_normal_selection(self):
        self.a['max_concurrent'] = 0
        self.assertTrue(all(s['id'] == 'b' for s, _ in self.choose([(self.a, Path('one.zip'))])))
        self.assertEqual(len(self.choose(count=1)), 1)
        self.assertEqual(self.choose(count=0), [])

    def test_matching_deduplication_missing_and_filtered_entries(self):
        data = {'items': [{'system': 'A', 'rom': 'ONE.ZIP'}, {'system': 'a', 'rom': 'one.zip'},
                          {'system': 'a', 'rom': 'missing.zip'}, {'system': 'disabled', 'rom': 'one.zip'}]}
        messages = []
        self.assertEqual(favorite_candidates([self.a], self.catalogs, data, messages.append), [(self.a, Path('one.zip'))])
        self.assertEqual(len(messages), 2)
        self.assertEqual(favorite_candidates([self.a], {}, data, lambda _: None), [])
        self.assertEqual(favorite_candidates([self.a], self.catalogs, dict(data, enabled=False)), [])

    def test_ambiguous_basename_requires_full_path(self):
        catalog = {'a': [Path('folder1/one.zip'), Path('folder2/one.zip')]}
        self.assertEqual(favorite_candidates([self.a], catalog, {'items': [{'system': 'a', 'rom': 'one.zip'}]}, lambda _: None), [])
        result = favorite_candidates([self.a], catalog, {'items': [{'system': 'a', 'rom': 'folder2/one.zip'}]})
        self.assertEqual(result[0][1], Path('folder2/one.zip'))

    def test_junction_alias_matches_only_filtered_catalog(self):
        catalog_rom = Path('alias/one.zip')
        favorite_rom = Path('target/one.zip')
        data = {'items': [{'system': 'a', 'rom': str(favorite_rom)},
                          {'system': 'a', 'rom': str(catalog_rom)}]}
        def resolved(path, *args, **kwargs):
            return Path('target') / path.name
        with patch.object(Path, 'resolve', resolved):
            result = favorite_candidates([self.a], {'a': [catalog_rom]}, data)
            self.assertEqual(result, [(self.a, catalog_rom)])
            # Canonical matching cannot resurrect a quarantined/filtered ROM.
            result = favorite_candidates([self.a], {'a': []}, data, lambda _: None)
            self.assertEqual(result, [])

    def test_distinct_same_named_files_do_not_match(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name in ('one', 'two'):
                (base / name).mkdir()
                (base / name / 'game.zip').touch()
            result = favorite_candidates([self.a], {'a': [base / 'one/game.zip']},
                                         {'items': [{'system': 'a', 'rom': str(base / 'two/game.zip')}]},
                                         lambda _: None)
            self.assertEqual(result, [])

    def test_save_reload_and_validation_preserve_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'favorites.json'
            self.assertEqual(load_favorites(path)['items'], [])
            data = {'enabled': True, 'items': [{'system': 'a', 'rom': '日本語.zip'}]}
            save_favorites(path, data)
            self.assertEqual(load_favorites(path), data)
            with self.assertRaises(ValueError):
                save_favorites(path, {'items': [{'rom': 'bad'}]})
            self.assertEqual(load_favorites(path), data)
            with patch('favorites.os.replace', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    save_favorites(path, {'items': []})
            self.assertEqual(load_favorites(path), data)
            self.assertEqual(len([p for p in Path(folder).iterdir() if p.suffix != ".lock"]), 1)
            path.write_text('{bad', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_favorites(path)

    def test_startup_failure_tries_another_favorite_before_normal_rom(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core_path = root / 'core.dll'
            core_path.touch()
            self.a['core'] = str(core_path)
            bad, good = Mock(), Mock()
            bad.load_game.side_effect = RuntimeError('bad ROM')
            factory = Mock(side_effect=[bad, good])
            ns = self.ns.copy()
            ns.update(shutil=Mock(), LibretroCore=factory, APP_DIR=root,
                      prepare_rom=lambda s, r, t: r,
                      resolve_app_relative_path=lambda v, default: root / default,
                      write_runtime_trace=Mock(), is_native_access_violation=lambda e: False)
            tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'start_slot_with_retry')
            exec(compile(ast.Module(body=[fn], type_ignores=[]), '<retry>', 'exec'), ns)
            favorites = [(self.a, Path('one.zip')), (self.a, Path('two.zip'))]
            failed = set()
            with contextlib.redirect_stdout(io.StringIO()):
                result = ns['start_slot_with_retry'](0, *favorites[0], [self.a], self.catalogs, {}, root,
                                                     failed, favorite_retries=favorites, cycle_group_usage={})
            self.assertEqual(result[3], Path('two.zip'))
            self.assertIn('one.zip', failed)
            bad.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
