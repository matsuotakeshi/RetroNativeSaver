import ast
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tests_fixtures import legacy_catalog_v072 as legacy


class CatalogCompatibilityTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('scan_roms','should_exclude_rom')]
        self.ns=dict(Path=Path,zipfile=zipfile)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<catalog>','exec'),self.ns)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def compare(self,system,fail_progress=False):
        before=copy.deepcopy(system)
        def run(fn):
            progress=[]; log=io.StringIO()
            def callback(count):
                progress.append(count)
                if fail_progress: raise RuntimeError('progress callback failed')
            with contextlib.redirect_stdout(log):
                try: result=('ok',fn(system,callback))
                except Exception as exc: result=('error',type(exc).__name__,str(exc))
            self.assertEqual(system,before)
            return result,progress,log.getvalue()
        expected=run(legacy.scan_roms); actual=run(self.ns['scan_roms'])
        self.assertEqual(actual,expected)
        return actual

    def system(self,**changes):
        value=dict(id='test',name='Test',rom_dir=str(self.root),extensions=['.zip','.chd','.rom'])
        value.update(changes)
        return value

    def test_filters_recursion_and_output_order(self):
        (self.root/'sub').mkdir()
        for name in ('z.ROM','a.chd','[BIOS] boot.rom','Game (BIOS).zip','BootRom.zip','exclude.rom','a.txt','no-extension','sub/nested.rom'):
            (self.root/name).touch()
        (self.root/'directory.rom').mkdir()
        for recursive in (True,False):
            for extensions in ([],['.ROM'],['.zip','.chd','.rom'],['.missing']):
                for excludes in ([],['EXCLUDE'],['',None]):
                    self.compare(self.system(recursive=recursive,extensions=extensions,exclude_name_contains=excludes))

    def test_optional_zip_validation_and_error_boundaries(self):
        for name,entries in [('valid.zip',{'a.ROM':b'yes'}),('wrong.zip',{'a.txt':b'no'}),
                             ('dir.zip',{'a.rom/':b''}),('mixed.zip',{'a.txt':b'no','sub/game.ROM':b'yes'})]:
            with zipfile.ZipFile(self.root/name,'w') as z:
                for key,value in entries.items(): z.writestr(key,value)
        (self.root/'broken.zip').write_bytes(b'broken')
        for validate in (True,False):
            for mode in ('extract','auto','passthrough','EXTRACT'):
                for content in (['.rom'],['.zip'],[]):
                    self.compare(self.system(validate_archive_contents=validate,archive_mode=mode,content_extensions=content))
        system=self.system(validate_archive_contents=True,archive_mode='extract',content_extensions=['.rom'])
        for error in (OSError('read denied'),RuntimeError('unexpected ZIP error')):
            with patch.object(zipfile,'ZipFile',side_effect=error):
                result=self.compare(system)
                self.assertEqual(result[0][0],'error' if isinstance(error,RuntimeError) else 'ok')

    def test_computer_and_pc88_candidates_and_deferred_zip_open(self):
        for name in ('Game (Disk 1).d88','Game (Disk 2).d88','Other (Disk A).d88',
                     'Other (Disk B).d88','Game (User Disk).d88','Game.zip','[BIOS].zip'):
            (self.root/name).write_bytes(b'not an archive')
        for mode in ('computer_two_drives','pc88_two_drives'):
            self.compare(self.system(disk_boot_mode=mode,extensions=['.d88','.zip'],archive_mode='extract',
                                     content_extensions=['.d88'],validate_archive_contents=True))
        with patch.object(zipfile,'ZipFile',side_effect=AssertionError('must defer ZIP opening')) as opened:
            self.compare(self.system(disk_boot_mode='computer_two_drives',archive_mode='extract',
                                     content_extensions=['.d88'],validate_archive_contents=True))
            opened.assert_not_called()

    def test_progress_count_and_callback_failure(self):
        for i in range(300): (self.root/f'{i:03}.rom').touch()
        result=self.compare(self.system())
        self.assertEqual(result[1],[128,256])
        self.assertEqual(len(result[0][1]),300)
        result=self.compare(self.system(),fail_progress=True)
        self.assertEqual(result[1],[128])
        self.assertEqual(result[0],('error','RuntimeError','progress callback failed'))

    def test_empty_diagnostic_top_extensions_and_failure(self):
        for index in range(16):
            for count in range(index%3+1): (self.root/f'{count}.ext{index:02}').touch()
        (self.root/'plain').touch()
        self.compare(self.system(extensions=['.unsupported']))
        # The first directory traversal succeeds; the diagnostic's second one fails.
        real=Path.iterdir
        calls=[0]
        def iterate(path):
            calls[0]+=1
            if calls[0]%2==0: raise OSError('diagnostic failed')
            return real(path)
        with patch.object(Path,'iterdir',new=iterate):
            result=self.compare(self.system(extensions=['.unsupported']))
            self.assertIn('extension diagnostic warning',result[2])

    def test_missing_directory_and_invalid_config(self):
        self.compare(self.system(rom_dir=str(self.root/'missing')))
        for changes in ({'extensions':None},{'extensions':[1]}, {'content_extensions':None},
                        {'exclude_name_contains':None}):
            (self.root/'game.rom').touch(exist_ok=True)
            self.compare(self.system(**changes))
        with patch.object(Path,'iterdir',side_effect=OSError('scan denied')):
            result=self.compare(self.system())
            self.assertEqual(result[0],('error','OSError','scan denied'))


if __name__=='__main__': unittest.main()
