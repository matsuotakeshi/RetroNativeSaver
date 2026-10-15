import ast
import contextlib
import copy
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
import computer_disks
import pc88_disks
from tests_fixtures import legacy_prepare_rom_v073 as legacy


class PrepareRomCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_rom')
        cls.ns=dict(Path=Path,shutil=shutil,zipfile=zipfile)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<prepare>','exec'),cls.ns)

    def run_case(self,fn,system,entries=None,raw=None,suffix='.zip',failure=None,output_exists=True):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rom=root/('game'+suffix); out=root/'output'
            if output_exists: out.mkdir()
            if raw is not None: rom.write_bytes(raw)
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',UserWarning)
                    with zipfile.ZipFile(rom,'w') as archive:
                        for name,data in entries or []: archive.writestr(name,data)
            original=rom.read_bytes(); cfg=copy.deepcopy(system)
            calls=[]; log=io.StringIO()
            def pc88(*args):
                calls.append(('pc88',args)); return out/'pc88.d88'
            def computers(*args):
                calls.append(('computer',args)); return out/'computer.cmd'
            def partial(src,dst):
                dst.write(b'partial')
                raise zipfile.BadZipFile('CRC failed') if failure=='crc' else OSError('copy failed')
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(log))
                stack.enter_context(patch.object(pc88_disks,'prepare',side_effect=pc88))
                stack.enter_context(patch.object(computer_disks,'prepare',side_effect=computers))
                if failure in ('copy','crc'): stack.enter_context(patch.object(shutil,'copyfileobj',side_effect=partial))
                if failure=='open': stack.enter_context(patch.object(zipfile,'ZipFile',side_effect=OSError('open denied')))
                try: result=('ok',fn(cfg,rom,out))
                except Exception as exc: result=('error',type(exc).__name__,str(exc))
            self.assertEqual(rom.read_bytes(),original)
            self.assertEqual(cfg,system)
            files=[(str(p.relative_to(root)),p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file()]
            def norm(value):
                if isinstance(value,Path):value=str(value)
                if isinstance(value,str):return value.replace(repr(str(root))[1:-1],'<root>').replace(str(root),'<root>')
                if isinstance(value,(tuple,list)):return [norm(v) for v in value]
                if isinstance(value,dict):return {k:norm(v) for k,v in value.items()}
                return value
            return norm((result,files,calls,log.getvalue()))

    def compare(self,system,**kwargs):
        before=self.run_case(legacy.prepare_rom,system,**kwargs)
        after=self.run_case(self.ns['prepare_rom'],system,**kwargs)
        self.assertEqual(after,before)
        return after

    def test_modes_extensions_largest_and_equal_size_order(self):
        entries=[('folder/',b''),('first.ROM',b'111'),('second.rom',b'222'),('bigger.txt',b'123456')]
        for mode in ('auto','extract','passthrough','EXTRACT','unknown',None):
            for exts in (['.rom'],[],['.zip'],['.missing']):
                self.compare(dict(archive_mode=mode,content_extensions=exts),entries=entries)
        result=self.compare(dict(archive_mode='extract',content_extensions=['.rom']),entries=entries)
        self.assertEqual(result[1],[['output\\first.ROM',b'111']])
        result=self.compare(dict(archive_mode='extract'),entries=entries)
        self.assertEqual(result[1],[['output\\bigger.txt',b'123456']])

    def test_flattened_names_duplicates_and_extension_fallback(self):
        for entries in ([('nested/game.rom',b'data')],[('../game.rom',b'data')],
                        [('same.rom',b'first'),('same.rom',b'last')], [('directory.rom/',b'')]):
            self.compare(dict(archive_mode='extract',extensions=['.ROM']),entries=entries,suffix='.ZIP')
        for exts in (None,[1]):
            self.compare(dict(content_extensions=exts),entries=[('game.rom',b'data')])

    def test_empty_corrupt_and_non_zip_passthrough(self):
        for mode in ('auto','extract','passthrough'):
            self.compare(dict(archive_mode=mode),entries=[])
            self.compare(dict(archive_mode=mode),raw=b'corrupt')
            self.compare(dict(archive_mode=mode),raw=b'content',suffix='.chd')
        self.assertEqual(self.compare({},raw=b'corrupt')[0],['ok','<root>\\game.zip'])

    def test_partial_output_and_exception_boundaries(self):
        for mode in ('auto','extract'):
            for failure in ('copy','crc','open'):
                result=self.compare(dict(archive_mode=mode),entries=[('game.rom',b'data')],failure=failure)
                if failure in ('copy','crc'): self.assertEqual(result[1],[['output\\game.rom',b'partial']])
                self.assertEqual(result[0][0],'ok' if failure=='crc' and mode=='auto' else 'error')
            self.compare(dict(archive_mode=mode),entries=[('game.rom',b'data')],output_exists=False)

    def test_computer_dispatch_precedes_archive_validation(self):
        for mode,expected in [('pc88_two_drives','pc88'),('computer_two_drives','computer')]:
            for archive_mode in ('auto','extract','passthrough'):
                result=self.compare(dict(disk_boot_mode=mode,archive_mode=archive_mode,content_extensions=None),raw=b'broken',failure='open')
                self.assertEqual(result[0][0],'ok')
                self.assertEqual(result[2][0][0],expected)
                self.assertEqual(len(result[2][0][1]),2 if expected=='pc88' else 3)


if __name__=='__main__': unittest.main()
