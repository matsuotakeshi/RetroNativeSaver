"""Protect the player's backup RAM and reuse the existing CD startup input."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from favorite_input import FavoritePress
from startup_input import StartTwice
from startup_preparation import apply_loaded_core_settings, prepare_environment


class NeoCDTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bios = self.root / 'player_system' / 'neocd'
        self.bios.mkdir(parents=True)
        (self.bios / 'front-sp1.bin').write_bytes(b'firmware')
        (self.bios / '000-lo.lo').write_bytes(b'low rom')
        (self.bios / 'neocd.srm').write_bytes(b'player backup RAM')
        (self.bios / 'game.state').write_bytes(b'player state')
        (self.bios / 'nested').mkdir()
        (self.bios / 'nested' / 'top-sp1.ROM').write_bytes(b'other firmware')
        self.system = dict(id='neocd', system_dir=str(self.bios.parent),
                           isolated_save_dir=True, core_options={'neocd_region': 'Japan'})

    def prepare(self, slot=0, system=None):
        return prepare_environment(self.system if system is None else system, {},
                                   self.root / f'slot_{slot}', slot,
                                   'neocd' if system is None else system['id'],
                                   lambda value, default: Path(value) if value else self.root / default)

    def test_only_firmware_is_copied_and_player_files_are_not_shared(self):
        original = {p: p.read_bytes() for p in self.bios.rglob('*') if p.is_file()}
        system_dir, save_dir, _, options = self.prepare()
        copied = system_dir / 'neocd'
        self.assertEqual({str(p.relative_to(copied)) for p in copied.rglob('*') if p.is_file()},
                         {'front-sp1.bin', '000-lo.lo', str(Path('nested/top-sp1.ROM'))})
        self.assertEqual(options, self.system['core_options'])
        self.assertTrue(save_dir.is_dir())
        self.assertTrue(save_dir.is_relative_to(self.root / 'slot_0'))
        (copied / 'neocd.srm').write_bytes(b'saver shared backup RAM')
        (save_dir / 'game.srm').write_bytes(b'saver per-content backup RAM')
        (copied / 'front-sp1.bin').write_bytes(b'modified copy')
        self.assertEqual({p: p.read_bytes() for p in original}, original)

    def test_slots_have_separate_firmware_and_backup_ram(self):
        first, first_save, _, _ = self.prepare(0)
        second, second_save, _, _ = self.prepare(1)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first_save, second_save)
        (first / 'neocd' / 'neocd.srm').write_bytes(b'first slot')
        self.assertFalse((second / 'neocd' / 'neocd.srm').exists())

    def test_missing_bios_aborts_preparation(self):
        self.system['system_dir'] = str(self.root / 'missing')
        with self.assertRaises(FileNotFoundError):
            self.prepare()

    def test_copy_error_propagates_instead_of_using_player_directory(self):
        with patch('startup_preparation.shutil.copy2', side_effect=OSError('copy failed')):
            with self.assertRaisesRegex(OSError, 'copy failed'):
                self.prepare()
        self.assertEqual((self.bios / 'neocd.srm').read_bytes(), b'player backup RAM')

    def test_existing_software_system_keeps_its_original_bios_path(self):
        other = dict(self.system, id='pcenginecd')
        system_dir, _, _, _ = self.prepare(system=other)
        self.assertEqual(system_dir, self.bios.parent)
        self.assertFalse((self.root / 'slot_0' / 'neocd_system').exists())

    def test_neocd_gets_same_two_start_presses_as_existing_cd_systems(self):
        for sid in ('neocd', 'pcenginecd', 'megacd'):
            core = SimpleNamespace(_startup_input=None)
            apply_loaded_core_settings(core, {}, sid)
            self.assertIsInstance(core._startup_input, StartTwice)
            observed = []
            for now in (0, 4.99, 5, 5.11, 5.99, 6, 6.11, 20):
                core._startup_input.advance(now)
                observed.append(core._startup_input.state(0, 1, 0, 3))
            self.assertEqual(observed, [0, 0, 1, 0, 0, 1, 0, 0])

    def test_automatic_start_can_be_disabled(self):
        core = SimpleNamespace(_startup_input=None)
        apply_loaded_core_settings(core, {'startup_start_twice': False}, 'neocd')
        self.assertIsNone(core._startup_input)

    def test_favorite_sequence_takes_precedence_without_extra_start(self):
        sequence = [{'delay_seconds': 9, 'device': 'joypad', 'key': 'Start'},
                    {'delay_seconds': 12, 'device': 'joypad', 'key': 'A'}]
        core = SimpleNamespace(_startup_input=None)
        apply_loaded_core_settings(core, {'_favorite_startup_input': sequence}, 'neocd')
        self.assertIsInstance(core._startup_input, FavoritePress)
        self.assertEqual(core._startup_input.steps, sequence)


if __name__ == '__main__':
    unittest.main()
