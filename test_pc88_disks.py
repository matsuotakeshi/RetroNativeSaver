from pathlib import Path
import tempfile
import unittest
import pc88_disks as d


class PC88Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def files(self, *names):
        paths = [self.root / name for name in names]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(path.name.encode())
        return paths

    def test_numbers_and_secondary_selection(self):
        a, b, c = self.files('Game (Disk 1).d88', 'Game (Disk 2).d88', 'Game (Disk 3).d88')
        self.assertEqual(d.select_disks(b), [a, b])
        self.assertEqual(d.boot_candidates([c, b, a]), [a])

    def test_letters_and_case(self):
        a, b = self.files('GAME (DISK A).D88', 'game (disk b).d88')
        self.assertEqual(d.select_disks(a), [a, b])

    def test_different_title_and_revision_not_mixed(self):
        a, _, _ = self.files('Game (Disk A).d88', 'Other (Disk B).d88', 'Game (Disk B) [Alt 1].d88')
        self.assertEqual(d.select_disks(a), [a])

    def test_different_folder_not_mixed(self):
        a, _ = self.files('set1/Game (Disk 1).d88', 'set2/Game (Disk 2).d88')
        self.assertEqual(d.select_disks(a), [a])

    def test_single_disk_copy_and_playlist(self):
        a, = self.files('日本語.d88')
        playlist = d.prepare(a, self.root / 'out')
        self.assertEqual(playlist.read_text(), 'pc88_drive1.d88\n')
        (playlist.parent / 'pc88_drive1.d88').write_bytes(b'changed')
        self.assertEqual(a.read_bytes(), '日本語.d88'.encode())

    def test_two_copies_in_order(self):
        a, b = self.files('Game (Disk 1).d88', 'Game (Disk 2).d88')
        out = d.prepare(a, self.root / 'out')
        self.assertEqual(out.read_text().splitlines(), ['pc88_drive1.d88', 'pc88_drive2.d88'])
        self.assertEqual((out.parent / 'pc88_drive2.d88').read_bytes(), b.read_bytes())

    def test_missing_first_and_ambiguous_second(self):
        b, = self.files('Game (Disk 2).d88')
        with self.assertRaises(ValueError):
            d.select_disks(b)
        a, _ = self.files('Game (Disk 1).d88', 'Game (Disk 2).88d')
        with self.assertRaises(ValueError):
            d.select_disks(a)

    def test_playlist_overrides_order_and_hides_members(self):
        a, b = self.files('Game (Disk A).d88', 'Game (Disk B).d88')
        playlist = self.root / 'Game.m3u'
        playlist.write_text(f'# explicit order\n{b.name}\n{a.name}\n', encoding='utf-8-sig')
        self.assertEqual(d.select_disks(playlist), [b, a])
        self.assertEqual(d.boot_candidates([a, b, playlist]), [playlist])

    def test_user_disk_not_boot_candidate(self):
        a, b = self.files('Game.d88', 'Game (User disk).d88')
        self.assertEqual(d.boot_candidates([a, b]), [a])

    def test_disk_word_in_title(self):
        a, b = self.files('Music Disk 2 (Disk A).d88', 'Music Disk 2 (Disk B).d88')
        self.assertEqual(d.select_disks(a), [a, b])

    def test_invalid_playlist_excluded(self):
        playlist = self.root / 'missing.m3u'
        playlist.write_text('missing.d88\n')
        self.assertEqual(d.boot_candidates([playlist]), [])


if __name__ == '__main__':
    unittest.main()
