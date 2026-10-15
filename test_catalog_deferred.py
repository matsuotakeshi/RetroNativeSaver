import ast
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


class DeferredCatalogTests(unittest.TestCase):
    def test_computer_catalog_never_opens_zip(self):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('scan_roms','should_exclude_rom')]
        zips=Mock()
        zips.ZipFile.side_effect=AssertionError('Catalog must not open archives')
        ns=dict(Path=Path,zipfile=zips)
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<catalog>','exec'),ns)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(30): (root/f'Game {i}.zip').write_bytes(b'not inspected yet')
            with contextlib.redirect_stdout(io.StringIO()):
                found=ns['scan_roms'](dict(id='pc98',name='PC98',rom_dir=tmp,extensions=['.zip'],
                    content_extensions=['.hdm'],archive_mode='extract',validate_archive_contents=True,
                    disk_boot_mode='computer_two_drives',recursive=True))
            self.assertEqual(len(found),30)
            zips.ZipFile.assert_not_called()

    def test_catalog_reports_progress_without_opening_roms(self):
        tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('scan_roms', 'should_exclude_rom')]
        ns = dict(Path=Path)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<catalog>', 'exec'), ns)
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(300):
                (Path(tmp) / f'{index}.rom').touch()
            progress = Mock()
            with contextlib.redirect_stdout(io.StringIO()):
                result = ns['scan_roms'](dict(id='test', name='Test', rom_dir=tmp, extensions=['.rom']), progress)
            self.assertEqual(len(result), 300)
            self.assertEqual([call.args[0] for call in progress.call_args_list], [128, 256])
