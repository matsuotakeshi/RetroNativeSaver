import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import favorites
import fixed_rom_catalog as fixed
import rom_catalog
from startup_preparation import prepare_rom


class MsxBootCandidateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.roms = self.root / 'roms'
        self.roms.mkdir()
        self.output = self.root / 'output'
        self.output.mkdir()
        self.system = dict(id='msx', name='MSX / MSX2', rom_dir=str(self.roms),
                           extensions=['.dsk', '.zip', '.rom', '.mx1'], recursive=True,
                           archive_mode='extract', content_extensions=['.dsk', '.rom', '.mx1'])
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_numbered_disk_labels_and_overall_number_priority(self):
        keep = ['Game (Disk 1 of 4).dsk', 'Game (Disk 1 of 4)[a].dsk',
                'Game (Disk 1 of 4)(Disk 2).dsk', 'Game (Disk A).DSK',
                'Game (Disc 01).dsk', 'Game disk_1.dsk', 'Game (Disk A).zip']
        omit = ['Game (Disk 2 of 4)[a].dsk', 'Game (Disk 4 of 4).dsk',
                'Game (Disk 2 of 4)(Disk 1).dsk', 'Game (Disk B).dsk',
                'Game (Disc 02).dsk', 'Game disk-b.dsk', 'Game (Disk B).ZIP']
        for expected, names in ((True, keep), (False, omit)):
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(rom_catalog.is_msx_boot_candidate(self.system, Path(name)), expected)

    def test_unnumbered_cartridges_and_other_systems_are_unchanged(self):
        for name in ('Game 2.dsk', 'Disk Warrior.dsk', 'Game [a].dsk', 'Game.zip',
                     'Game (Disk 2).rom', 'Game (Disk B).mx1', 'Game.m3u'):
            self.assertTrue(rom_catalog.is_msx_boot_candidate(self.system, Path(name)), name)
        for sid in ('pc88', 'x68000', 'fm7', 'snes', None):
            self.assertTrue(rom_catalog.is_msx_boot_candidate(dict(id=sid), Path('Game (Disk 2).dsk')))

    def test_live_scan_filters_secondary_disks_but_keeps_dump_variants(self):
        for name in ('Game (Disk 1 of 4).dsk', 'Game (Disk 1 of 4)[a].dsk',
                     'Game (Disk 2 of 4)[a].dsk', 'Other (Disk B).zip',
                     'Game 2.rom', 'Single.dsk', '[BIOS].rom'):
            (self.roms / name).touch()
        before = copy.deepcopy(self.system)
        with patch('zipfile.ZipFile', side_effect=AssertionError('filename scan only')):
            actual = rom_catalog.scan_roms(self.system)
        self.assertEqual({p.name for p in actual}, {'Game (Disk 1 of 4).dsk',
                         'Game (Disk 1 of 4)[a].dsk', 'Game 2.rom', 'Single.dsk'})
        self.assertEqual(self.system, before)

    def test_missing_disk_one_does_not_promote_disk_two(self):
        (self.roms / 'Game (Disk 2).dsk').touch()
        self.assertEqual(rom_catalog.scan_roms(self.system), [])

    def write_old_catalog(self, names):
        paths = [self.roms / name for name in names]
        for path in paths:
            path.touch()
        saved = {'msx': dict(signature=fixed.signature(self.system),
                            roms=[[str(p), str(p.resolve()).casefold()] for p in paths])}
        catalog = self.root / 'old_catalog.json'
        catalog.write_text(json.dumps(dict(format=fixed.FORMAT, systems=saved, sha256=fixed.digest(saved))))
        return catalog, paths

    def build(self, catalog, worker):
        return rom_catalog.build_catalogs([self.system], {}, worker, {}, lambda *a, **k: None,
                                          catalog_path=catalog)

    def test_old_cache_filters_in_both_runtime_paths_without_scan_or_zip_reads(self):
        catalog, paths = self.write_old_catalog(['Game (Disk 2).dsk', 'Game (Disk 1).dsk',
                                                'Other (Disk B).zip', 'Game.rom'])
        before = catalog.read_bytes()
        with patch('rom_catalog.scan_roms', side_effect=AssertionError('must not rescan')), \
             patch('zipfile.ZipFile', side_effect=AssertionError('must not open archives')):
            for worker in (False, True):
                loaded = self.build(catalog, worker)
                self.assertEqual(loaded['msx'], [paths[1], paths[3]])
                self.assertTrue(self.system['_fixed_rom_catalog'])
        self.assertEqual(catalog.read_bytes(), before)

    def test_cache_containing_only_secondary_disks_stays_empty_without_rescan(self):
        catalog, _ = self.write_old_catalog(['Game (Disk 2).dsk'])
        with patch('rom_catalog.scan_roms', side_effect=AssertionError('valid empty catalog')):
            self.assertEqual(self.build(catalog, True), {})

    def test_filtered_disk_cannot_return_through_favorites_or_canonical_cache(self):
        catalog, paths = self.write_old_catalog(['Game (Disk 1).dsk', 'Game (Disk 2).dsk'])
        data = {'items': [{'system': 'msx', 'rom': str(p)} for p in paths]}
        before = copy.deepcopy(data)
        loaded = self.build(catalog, True)
        self.assertEqual([p for _, p in favorites.favorite_candidates([self.system], loaded, data)], [paths[0]])
        self.assertEqual(data, before)

    def test_new_catalog_records_only_boot_candidates(self):
        (self.roms / 'Game (Disk 1).dsk').touch()
        (self.roms / 'Game (Disk 2).dsk').touch()
        catalog = self.root / 'new_catalog.json'
        self.assertEqual(fixed.write_catalog(catalog, [self.system]), 1)
        self.assertEqual(len(fixed.read_catalog(catalog)['msx']['roms']), 1)
        self.assertEqual(len(self.build(catalog, False)['msx']), 1)

    def archive(self, entries):
        path = self.roms / 'Game.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def test_zip_selects_disk_one_even_when_disk_two_is_larger(self):
        for labels in (('Disk 1 of 4', 'Disk 2 of 4'), ('Disk A', 'Disk B')):
            with self.subTest(labels=labels):
                first, second = (f'Game ({label}).dsk' for label in labels)
                archive = self.archive([('sub/' + second, b'other' * 20), ('sub/' + first, b'boot')])
                before = archive.read_bytes()
                result = prepare_rom(self.system, archive, self.output)
                self.assertEqual(result.name, first)
                self.assertEqual(result.read_bytes(), b'boot')
                self.assertEqual(archive.read_bytes(), before)

    def test_zip_without_boot_disk_is_rejected_even_in_auto_mode(self):
        archive = self.archive([('Game (Disk B).dsk', b'other')])
        for mode in ('extract', 'auto'):
            with self.assertRaisesRegex(RuntimeError, 'No MSX boot disk'):
                prepare_rom(dict(self.system, archive_mode=mode), archive, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_zip_unnumbered_cartridge_and_non_msx_selection_are_unchanged(self):
        archive = self.archive([('Game (Disk 1).dsk', b'1'), ('Game (Disk 2).dsk', b'222')])
        self.assertEqual(prepare_rom(dict(self.system, id='other'), archive, self.output).read_bytes(), b'222')
        archive = self.archive([('small.dsk', b'1'), ('Game (Disk 2).rom', b'222')])
        self.assertEqual(prepare_rom(self.system, archive, self.output).read_bytes(), b'222')
        self.assertEqual(prepare_rom(dict(self.system, archive_mode='passthrough'), archive, self.output), archive)

    def test_optional_zip_validation_rejects_secondary_only_archive(self):
        archive = self.archive([('Game (Disk 2).dsk', b'data')])
        self.system['validate_archive_contents'] = True
        self.assertEqual(rom_catalog.scan_roms(self.system), [])
        self.archive([('Game (Disk 1).dsk', b'boot'), ('Game (Disk 2).dsk', b'data')])
        self.assertEqual(rom_catalog.scan_roms(self.system), [archive])


if __name__ == '__main__':
    unittest.main()
