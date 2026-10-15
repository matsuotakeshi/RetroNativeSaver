import contextlib
import io
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from catalog_paths import CatalogPaths
import favorites
import pc88_disks
import rom_catalog
from tests_fixtures import startup_lookup_v107 as old


class CatalogPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.system={'id':'a','name':'A'}

    def compare_favorites(self, paths, items):
        results=[]
        for function in (old.favorite_candidates,favorites.favorite_candidates):
            messages=[]
            result=function([self.system],{'a':paths},{'items':items},messages.append)
            results.append((result,messages))
        self.assertEqual(*results)
        return results[-1][0]

    def test_lexical_duplicates_ambiguity_missing_and_order(self):
        paths=[self.root/'one.zip',self.root/'sub/one.zip',self.root/'two.zip']
        for path in paths:path.parent.mkdir(exist_ok=True);path.touch()
        paths.append(paths[-1])  # Duplicate catalog entry must remain ambiguous.
        items=[{'system':'a','rom':x} for x in ('one.zip',str(paths[0]),str(paths[2]),'missing.zip',str(paths[0]))]
        result=self.compare_favorites(paths,items)
        self.assertEqual(result,[(self.system,paths[0])])
        self.compare_favorites([],items)

    @unittest.skipUnless(os.name=='nt','Windows enumeration optimization')
    def test_alias_lookup_resolves_parents_not_every_file(self):
        folder=self.root/'roms';folder.mkdir();(self.root/'detour').mkdir()
        paths=[folder/f'{i}.rom' for i in range(80)]
        for path in paths:path.touch()
        wanted=self.root/'detour/../roms/5.rom'
        original=Path.resolve;calls=[]
        # The tool sandbox may deny GetFinalPathNameByHandle even for readable
        # directories. Supply its non-strict result to exercise the fast path.
        def resolve(path,*args,**kwargs):
            calls.append(path)
            return original(path)
        with patch.object(Path,'resolve',resolve):
            result=favorites.favorite_candidates([self.system],{'a':paths},
                {'items':[{'system':'a','rom':str(wanted)}]})
        self.assertEqual(result,[(self.system,paths[5])])
        self.assertEqual(len(calls),2)
        self.assertTrue(all(p.name != '5.rom' for p in calls))

    def test_reparse_or_unreadable_metadata_uses_original_resolution(self):
        path=self.root/'link.rom'
        fake=SimpleNamespace(stat=lambda **kw:SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT))
        cache=CatalogPaths();cache.directories[path.parent]={path.name:fake}
        target=self.root/'target.rom'
        with patch.object(Path,'resolve',return_value=target) as resolve:
            self.assertEqual(cache.canonical(path),str(target).replace('\\','/').casefold())
            resolve.assert_called_once_with()
        with patch.object(Path,'resolve',side_effect=OSError('denied')):
            self.assertEqual(cache.canonical(path),str(path).replace('\\','/').casefold())

    @unittest.skipUnless(os.name=='nt','Windows enumeration optimization')
    def test_parent_resolution_failure_is_cached_but_file_fallback_is_kept(self):
        files=[self.root/'a.rom',self.root/'b.rom']
        for p in files:p.touch()
        calls=[]
        def resolve(path,**kw):
            calls.append((path,kw))
            if kw.get('strict'):raise OSError('parent denied')
            return path
        cache=CatalogPaths()
        with patch.object(Path,'resolve',resolve):
            for p in files:self.assertEqual(cache.canonical(p),str(p).replace('\\','/').casefold())
        self.assertEqual(sum(bool(kw.get('strict')) for _,kw in calls),1)
        self.assertEqual([p for p,kw in calls if not kw],files)

    def test_directory_lookup_denied_falls_back_without_changing_eligibility(self):
        path=self.root/'game.rom';path.touch()
        with patch('catalog_paths.os.scandir',side_effect=PermissionError('no enumeration')):
            self.assertTrue(CatalogPaths().is_file(path))
            self.assertFalse(CatalogPaths().is_file(self.root/'missing.rom'))

    def test_scan_refreshes_add_delete_and_zip_contents(self):
        import zipfile
        system=dict(self.system,rom_dir=str(self.root),extensions=['.zip'],
                    content_extensions=['.rom'],archive_mode='extract',validate_archive_contents=True)
        path=self.root/'game.zip'
        def scan():
            with contextlib.redirect_stdout(io.StringIO()):return rom_catalog.scan_roms(system)
        self.assertEqual(scan(),[])
        with zipfile.ZipFile(path,'w') as z:z.writestr('game.rom',b'data')
        self.assertEqual(scan(),[path])
        with zipfile.ZipFile(path,'w') as z:z.writestr('game.txt',b'data')
        self.assertEqual(scan(),[])
        path.unlink();self.assertEqual(scan(),[])

    def test_favorite_refresh_rechecks_missing_then_created_file(self):
        alias=self.root/'extra/../game.rom';(self.root/'extra').mkdir()
        path=self.root/'game.rom'
        for create in (False,True):
            if create:path.touch()
            self.compare_favorites([path],[{'system':'a','rom':str(alias)}])

    def test_pc88_no_references_avoids_resolution_and_preserves_candidates(self):
        paths=[self.root/x for x in ('A (Disk 1).d88','A (Disk 2).d88','B (Disk A).d88','B (Disk B).d88','User Disk.d88','plain.d88')]
        expected=old.boot_candidates(paths)
        with patch.object(Path,'resolve',side_effect=AssertionError('unnecessary resolution')):
            self.assertEqual(pc88_disks.boot_candidates(paths),expected)

    def test_pc88_playlist_references_and_invalid_playlists_preserved(self):
        disk=self.root/'A (Disk 1).d88';disk.touch()
        playlist=self.root/'boot.m3u';playlist.write_text(disk.name,encoding='utf-8')
        invalid=self.root/'bad.m3u';invalid.write_text('missing.d88',encoding='utf-8')
        for paths in ([disk,playlist],[disk,invalid],[disk,playlist,invalid]):
            values=[]
            for function in (old.boot_candidates,pc88_disks.boot_candidates):
                log=io.StringIO()
                with contextlib.redirect_stdout(log): result=function(paths)
                values.append((result,log.getvalue()))
            self.assertEqual(*values)


if __name__=='__main__':unittest.main()
