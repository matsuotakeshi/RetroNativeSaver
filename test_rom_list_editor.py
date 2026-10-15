import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rom_list_editor import add_to_whitelist, read_state, blacklist_rows


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'white.json'

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')

    def test_merge_case_duplicate_and_backup(self):
        self.write({'systems': {'Nintendo 64': ['a.zip']}, 'custom': 17})
        original = self.path.read_bytes()
        count, backup = add_to_whitelist(self.path, [('nintendo 64', 'A.ZIP'), ('NINTENDO 64', 'b.zip'), ('Nintendo 64', 'b.zip')])
        self.assertEqual(count, 1)
        data, _ = read_state(self.path, 'white')
        self.assertEqual(data, {'systems': {'Nintendo 64': ['a.zip', 'b.zip']}, 'custom': 17})
        self.assertEqual(backup.read_bytes(), original)

    def test_seed_is_preserved(self):
        seed = self.path.with_name('seed.json')
        seed.write_text('{"systems":{"S":["old.zip"]}}')
        add_to_whitelist(self.path, [('S', 'new.zip')], seed)
        self.assertEqual(read_state(self.path, 'white')[0]['systems']['S'], ['old.zip', 'new.zip'])

    def test_invalid_file_not_overwritten(self):
        self.write({'systems': {'S': {'wrong': True}}})
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            add_to_whitelist(self.path, [('S', 'new.zip')])
        self.assertEqual(self.path.read_bytes(), original)

    def test_replace_failure_keeps_original(self):
        self.write({'systems': {'S': ['old.zip']}})
        original = self.path.read_bytes()
        with patch('rom_list_editor.os.replace', side_effect=OSError('denied')):
            with self.assertRaises(OSError):
                add_to_whitelist(self.path, [('S', 'new.zip')])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_listing_includes_history_and_registered_state(self):
        black = {'systems': {'S': {'a.zip': {'blacklisted': True, 'failure_sessions': 3}, 'b.zip': {'blacklisted': False}}}}
        rows = blacklist_rows(black, {'systems': {'s': ['A.ZIP']}})
        self.assertTrue(rows[0]['registered'])
        self.assertTrue(rows[0]['blocked'])
        self.assertFalse(rows[1]['blocked'])

    def test_reload_preserves_external_additions(self):
        self.write({'systems': {'S': ['external.zip']}})
        add_to_whitelist(self.path, [('S', 'new.zip')])
        self.assertIn('external.zip', read_state(self.path, 'white')[0]['systems']['S'])


if __name__ == '__main__':
    unittest.main()
