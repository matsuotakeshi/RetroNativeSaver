import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import fixed_rom_catalog as fixed
import rom_catalog
import favorites
from startup_preparation import prepare_rom


class FixedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roms = self.root/'roms'; self.roms.mkdir()
        self.file = self.root/'state/rom_catalog.json'
        self.system = dict(id='a',name='A',rom_dir=str(self.roms),extensions=['.rom'])
        self.a = self.roms/'a.rom'; self.a.touch()
        self.b = self.roms/'b.rom'; self.b.touch()
        self.output = io.StringIO()
        self.quiet = contextlib.redirect_stdout(self.output); self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__,None,None,None)

    def write(self):
        return fixed.write_catalog(self.file,[self.system])

    def build(self, system=None, **kw):
        return rom_catalog.build_catalogs([system or self.system],kw.get('titles',{}),
            kw.get('worker',True),kw.get('quarantine',{}),lambda *a,**k:None,
            catalog_path=self.file)

    def test_hit_preserves_order_without_scan_and_fresh_safety_filters(self):
        self.system['require_title_db_match'] = True
        expected = rom_catalog.scan_roms(self.system)
        self.write()
        with patch('rom_catalog.scan_roms',side_effect=AssertionError('cache must avoid scanning')):
            loaded = self.build()
            self.assertEqual(loaded['a'],expected)
            self.assertEqual(self.build(titles={'a':{'a':'A'}})['a'],[self.a])
            self.assertEqual(self.build(quarantine={'A':{'a.rom'}})['a'],[self.b])
            self.assertEqual(self.build(quarantine={'A':{'a.rom','b.rom'}}),{})
        self.assertTrue(self.system['_fixed_rom_catalog'])

    def test_fixed_list_requires_manual_refresh_for_additions_and_deletions(self):
        self.write();self.a.unlink();new=self.roms/'new.rom';new.touch()
        self.assertEqual(self.build()['a'],[self.a,self.b])
        with self.assertRaises(FileNotFoundError):prepare_rom(self.system,self.a,self.root)
        self.write()
        self.assertEqual(self.build()['a'],rom_catalog.scan_roms(self.system))
        self.assertIn(new,self.build()['a']);self.assertNotIn(self.a,self.build()['a'])

    def test_empty_hit_does_not_rescan(self):
        self.a.unlink();self.b.unlink();self.write()
        with patch('rom_catalog.scan_roms',side_effect=AssertionError('empty is still a hit')):
            self.assertEqual(self.build(),{})

    def test_missing_corrupt_wrong_version_and_checksum_fall_back(self):
        self.assertEqual(self.build()['a'],[self.a,self.b])
        self.write();good=json.loads(self.file.read_text())
        cases=['{','[]',json.dumps(dict(good,format=999)),json.dumps(dict(good,sha256='wrong'))]
        for text in cases:
            self.file.write_text(text)
            self.assertEqual(self.build()['a'],[self.a,self.b])
            self.assertNotIn('_fixed_rom_catalog',self.system)

    def test_malformed_entries_are_rejected_even_with_matching_digest(self):
        for entry in (None,{'signature':{},'roms':[None]}, {'signature':{},'roms':[['a','']]},
                      {'signature':{},'roms':[['a',123]]}):
            systems={'a':entry}
            self.file.parent.mkdir(exist_ok=True)
            self.file.write_text(json.dumps(dict(format=fixed.FORMAT,systems=systems,sha256=fixed.digest(systems))))
            self.assertEqual(fixed.read_catalog(self.file),{})

    def test_each_scan_setting_invalidates_only_its_system(self):
        self.write()
        changes=dict(rom_dir=str(self.root/'other'),extensions=['.zip'],recursive=True,
            validate_archive_contents=True,disk_boot_mode='pc88_two_drives',archive_mode='extract',
            content_extensions=['.d88'],exclude_name_contains=['a'])
        for key,value in changes.items():
            changed=dict(self.system,**{key:value})
            with patch('rom_catalog.scan_roms',return_value=[self.b]) as scan:
                self.assertEqual(self.build(changed)['a'],[self.b]);scan.assert_called_once()
        changed=dict(self.system,resource_group='heavy_cd',resource_weight=1,max_concurrent=2)
        with patch('rom_catalog.scan_roms',side_effect=AssertionError('unrelated setting')):
            self.assertEqual(self.build(changed)['a'],[self.a,self.b])

    def test_root_unavailable_is_not_eligible(self):
        self.write();self.a.unlink();self.b.unlink();self.roms.rmdir()
        self.assertEqual(self.build(),{})

    def test_saved_canonical_paths_cannot_restore_filtered_favorites(self):
        self.write();loaded=self.build()
        alias=self.roms/'../roms/a.rom'
        data={'items':[{'system':'a','rom':str(alias)}]}
        expected=favorites.favorite_candidates([self.system],dict(loaded),data)
        from catalog_paths import CatalogPaths
        original=CatalogPaths.canonical
        def canonical(obj,path):
            self.assertEqual(str(path),str(alias))
            return original(obj,path)
        with patch.object(CatalogPaths,'canonical',canonical):
            self.assertEqual(favorites.favorite_candidates([self.system],loaded,data),expected)
        filtered=fixed.filtered_catalogs(loaded,{'a':[self.b]})
        self.assertEqual(favorites.favorite_candidates([self.system],filtered,data),[])
        self.assertIs(filtered.canonical_paths,loaded.canonical_paths)

    def test_atomic_write_failure_preserves_old_file(self):
        self.write();before=self.file.read_bytes()
        with patch('fixed_rom_catalog.os.replace',side_effect=OSError('locked')):
            with self.assertRaises(OSError):self.write()
        self.assertEqual(self.file.read_bytes(),before)
        self.assertEqual(list(self.file.parent.glob('*.tmp')),[])

    def test_scheduler_blacklist_keeps_metadata_without_reintroducing_roms(self):
        from independent_slots import _load_scheduler_state
        self.write();loaded=self.build()
        api=SimpleNamespace(
            resolve_app_relative_path=lambda value,default:self.root/default,
            _load_persistent_rom_state=lambda path:{},
            _load_persistent_rom_whitelist=lambda path:{},
            _persistent_whitelisted_roms=lambda state:{},
            _persistent_blacklisted_roms=lambda state:{'A':{'a.rom'}},
            _apply_persistent_whitelist=lambda black,white:(black,{}),
            _rom_in_name_map=lambda values,system,name:name in values.get(system,set()))
        *_,filtered=_load_scheduler_state(api,[self.system],loaded,{})
        self.assertEqual(filtered['a'],[self.b])
        self.assertIs(filtered.canonical_paths,loaded.canonical_paths)
        data={'items':[{'system':'a','rom':str(self.a)}]}
        self.assertEqual(favorites.favorite_candidates([self.system],filtered,data),[])

    def test_relative_rom_directory_signature_includes_working_directory(self):
        system=dict(self.system,rom_dir='roms')
        with patch('fixed_rom_catalog.os.getcwd',return_value='C:/one'):
            one=fixed.signature(system)
        with patch('fixed_rom_catalog.os.getcwd',return_value='C:/two'):
            two=fixed.signature(system)
        self.assertNotEqual(one,two)

    def test_scan_failure_preserves_old_file(self):
        self.write();before=self.file.read_bytes()
        with patch('rom_catalog.scan_roms',side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):self.write()
        self.assertEqual(self.file.read_bytes(),before)

    def test_update_rejects_bad_system_json_without_replacing_file(self):
        self.write();before=self.file.read_bytes();folder=self.root/'systems';folder.mkdir()
        (folder/'bad.json').write_text('{')
        with self.assertRaises(ValueError):fixed.update_from_config(self.root,{})
        self.assertEqual(self.file.read_bytes(),before)

    def test_replaced_zip_is_revalidated_when_selected(self):
        self.system.update(extensions=['.zip'],content_extensions=['.rom'],
                           archive_mode='extract',validate_archive_contents=True)
        path=self.roms/'game.zip'
        with zipfile.ZipFile(path,'w') as z:z.writestr('game.rom',b'game')
        self.write();self.assertEqual(self.build()['a'],[path])
        with zipfile.ZipFile(path,'w') as z:z.writestr('game.txt',b'not a rom')
        with self.assertRaises(RuntimeError):prepare_rom(self.system,path,self.root)

    def test_disk_candidates_and_playlists_preserved_in_snapshot(self):
        self.system.update(extensions=['.d88','.m3u'],disk_boot_mode='pc88_two_drives')
        disk=self.roms/'Game (Disk 1).d88';disk.touch()
        (self.roms/'Game (Disk 2).d88').touch()
        (self.roms/'boot.m3u').write_text(disk.name,encoding='utf-8')
        expected=rom_catalog.scan_roms(self.system)
        self.write();self.assertEqual(self.build()['a'],expected)

    def test_update_command_success_and_failure(self):
        folder=self.root/'systems';folder.mkdir()
        (folder/'a.json').write_text(json.dumps(self.system))
        config=self.root/'custom.json';config.write_text('{}')
        args=['--update-rom-catalog','--config',str(config)]
        self.assertEqual(fixed.run_update_command(self.root,args),0)
        self.assertTrue(self.file.is_file());before=self.file.read_bytes()
        config.write_text('{')
        self.assertEqual(fixed.run_update_command(self.root,args),1)
        self.assertEqual(before,self.file.read_bytes())


if __name__=='__main__':unittest.main()
