import json
from pathlib import Path
import tempfile
import unittest

from favorite_titles import load_titles, display_title, rom_rows
from favorites import save_favorites, load_favorites


class FavoriteTitleTests(unittest.TestCase):
    def test_databases_and_windows_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'metadata').mkdir()
            for sid, db in [('arcade', 'fbneo'), ('fbneo', 'fbneo'), ('mame', 'mame')]:
                (root / f'metadata/{db}_titles.json').write_text(
                    json.dumps({'titles': {'SF2.zip': 'ストリートファイターII'}}), encoding='utf-8-sig')
                titles = load_titles(root, {'id': sid})
                self.assertEqual(display_title(r'C:\ROMs\SF2.ZIP', titles), 'ストリートファイターII')
                self.assertEqual(display_title(r'C:\ROMs\unknown.zip', titles), 'unknown.zip')

    def test_custom_plain_database_and_invalid_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'custom.json'
            system = {'id': 'arcade', 'title_db': str(db)}
            self.assertEqual(load_titles(root, system), {})
            db.write_text('{invalid', encoding='utf-8')
            self.assertEqual(load_titles(root, system), {})
            db.write_text(json.dumps({'sf2': 'SF II', 'invalid': None}), encoding='utf-8')
            self.assertEqual(load_titles(root, system), {'sf2': 'SF II'})

    def test_scan_and_saved_rom_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'roms/sub').mkdir(parents=True)
            for name in ['sf2.zip', 'unknown.7z', 'ignored.txt', 'sub/sf2.zip']:
                (root / 'roms' / name).touch()
            system = {'id': 'mame', 'rom_dir': 'roms', 'extensions': ['.zip', '.7z'], 'recursive': False}
            rows = rom_rows(root, system, {'sf2': 'Street Fighter II'})
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], 'Street Fighter II')
            system['recursive'] = True
            self.assertEqual(len(rom_rows(root, system, {})), 3)
            path = root / 'favorites.json'
            item = {'system': 'mame', 'rom': rows[0][2]}
            save_favorites(path, {'items': [item, item]})
            self.assertEqual(load_favorites(path)['items'], [item])


if __name__ == '__main__':
    unittest.main()
