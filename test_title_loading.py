"""Keep title precedence, filesystem failures and observable ordering stable."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import title_metadata as current
from tests_fixtures import legacy_titles_v077 as old


class TitleLoadingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding='utf-8-sig')
        return str(path)

    def compare(self, name, *args):
        results = []
        for module in (old, current):
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                try:
                    result = ('ok', getattr(module, name)(*copy.deepcopy(args)))
                except Exception as exc:
                    result = ('error', type(exc).__name__, str(exc))
            results.append((result, log.getvalue()))
        self.assertEqual(*results)
        return results[1][0]

    def test_database_precedence_and_playlist_first_match(self):
        self.write('db.json', {'titles': {'game': 'Database'}})
        a = self.write('a.lpl', {'items': [{'path': 'game.zip', 'label': 'Playlist'},
                                         {'path': 'other.zip', 'label': 'First'}]})
        b = self.write('b.lpl', {'items': [{'path': 'other.zip', 'label': 'Second'}]})
        systems = [{'id': ' arcade ', 'title_db': 'db.json', 'title_sources': [a, a, b]}]
        actual = self.compare('build_title_maps', systems, self.root)
        self.assertEqual(actual[1]['arcade'], {'game': 'Database', 'other': 'First'})

    def test_empty_duplicate_and_disabled_systems(self):
        self.write('db.json', {'game': 'Title'})
        self.write('db2.json', {'other': 'Other'})
        cases = [[], [{'id': ''}, {'id': '  '}],
                 [{'id': 'x', 'enabled': False, 'title_db': 'db.json'}],
                 [{'id': 'x', 'title_db': 'db.json'}, {'id': 'x'}],
                 [{'id': 'x', 'title_db': 'db.json'}, {'id': 'x', 'title_db': 'db2.json'}]]
        for systems in cases:
            with self.subTest(systems=systems):
                self.compare('build_title_maps', systems, self.root)

    def test_invalid_playlist_shapes_and_json(self):
        bad = self.root / 'invalid.lpl'
        bad.write_text('{invalid', encoding='utf-8')
        good = self.write('good.lpl', {'items': [{'path': 'good.zip', 'label': 'Good'}]})
        for data in (None, [], 1, {}, {'items': None}, {'items': {}},
                     {'items': [None, 3, {}, {'path': 'x.zip', 'label': 'DETECT'}]}):
            p = self.write('shape.lpl', data)
            self.compare('_load_retroarch_playlist_titles', [str(bad), p, good])

    def test_read_error_is_skipped_but_stat_error_propagates(self):
        path = self.write('a.lpl', {'items': []})
        with patch.object(Path, 'read_text', side_effect=PermissionError('read blocked')):
            self.assertEqual(self.compare('_load_retroarch_playlist_titles', [path]), ('ok', {}))
        with patch.object(Path, 'is_file', side_effect=OSError('stat failed')):
            self.assertEqual(self.compare('_load_retroarch_playlist_titles', [path])[0], 'error')

    def test_core_or_path_filters(self):
        p = self.write('a.lpl', {'items': [
            {'path': str(self.root / 'roms/a.zip'), 'label': 'A', 'core_name': 'Different'},
            {'path': 'b.zip', 'label': 'B', 'core_name': 'FBNeo'},
            {'path': 'c.zip', 'label': 'C', 'core_name': 'Other'}]})
        for filters, roots in (([], []), (['fbneo'], []), (['fbneo'], [str(self.root/'roms')]),
                               ([' FBNeo '], []), (None, None)):
            self.compare('_load_retroarch_playlist_titles', [p], filters, roots)

    def test_bad_system_inputs_and_database_errors(self):
        for systems in ([None], [{'id': 'x', 'title_sources': 3}],
                        [{'id': 'x', 'title_db': 'missing.json'}],
                        [{'id': 'x', 'title_core_names': 1}], [{'id': None}]):
            self.compare('build_title_maps', systems, self.root)

    def test_loader_call_order_and_error_propagation(self):
        for fail in (None, 'json', 'playlist'):
            outcomes = []
            for module in (old, current):
                events = []; log = io.StringIO()
                def database(path):
                    events.append(('json', str(path)))
                    if fail == 'json': raise RuntimeError('json failed')
                    return {'x': 'DB'}
                def playlist(*args):
                    events.append(('playlist', args))
                    if fail == 'playlist': raise RuntimeError('playlist failed')
                    return {'x': 'Playlist', 'y': 'Y'}
                with patch.object(module, '_load_title_json', database), patch.object(module, '_load_retroarch_playlist_titles', playlist), contextlib.redirect_stdout(log):
                    try:
                        result = module.build_title_maps([{'id': 'x', 'title_db': 'db.json'}], self.root)
                    except Exception as exc:
                        result = (type(exc).__name__, str(exc))
                outcomes.append((result, events, log.getvalue()))
            self.assertEqual(*outcomes)
