import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import computer_disks as disks
from fm7_disks import command_file, machine_for, quote


class FM7Tests(unittest.TestCase):
    def test_two_drives_are_copies_and_state_is_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roms = root / 'games with spaces'
            roms.mkdir()
            (roms/'fm7.zip').write_bytes(b'bios')
            one = roms/'Game (Disk A).d77'
            two = roms/'Game (Disk B).d77'
            one.write_bytes(b'disk1')
            two.write_bytes(b'disk2')
            slot = root/'slot'
            cfg = dict(id='fm7', rom_dir=str(roms))
            with contextlib.redirect_stdout(io.StringIO()):
                result = disks.prepare(cfg, one, slot)
            self.assertEqual(result.suffix, '.cmd')
            command = result.read_text()
            self.assertTrue(command.startswith('fm7 '))
            self.assertIn('-flop1 '+quote(slot/'drive1.d77'), command)
            self.assertIn('-flop2 '+quote(slot/'drive2.d77'), command)
            self.assertIn('-cfg_directory '+quote(slot/'cfg'), command)
            self.assertEqual((slot/'system/mame/roms/fm7.zip').read_bytes(), b'bios')
            (slot/'drive1.d77').write_bytes(b'changed')
            (slot/'drive2.d77').write_bytes(b'changed')
            self.assertEqual(one.read_bytes(), b'disk1')
            self.assertEqual(two.read_bytes(), b'disk2')

    def test_single_disk_has_no_second_drive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'fm7.zip').touch()
            source = root/'game.d88'
            source.touch()
            with contextlib.redirect_stdout(io.StringIO()):
                path = disks.prepare(dict(id='fm7', rom_dir=tmp), source, root/'slot')
            self.assertNotIn('-flop2', path.read_text())

    def test_machine_selection_and_missing_bios(self):
        self.assertEqual(machine_for({}, Path('Game (FM77AV)/Disk A.d77')), 'fm77av')
        self.assertEqual(machine_for({}, Path('ordinary.d77')), 'fm7')
        self.assertEqual(machine_for({'mame_machine':'fm7'}, Path('FM77AV.d77')), 'fm7')
        with self.assertRaises(ValueError):
            machine_for({'mame_machine':'other'}, Path('game.d77'))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                command_file(dict(rom_dir=tmp), Path('game.d77'), [], Path(tmp)/'slot')

    def test_catalog_excludes_tapes_bios_and_secondary_disks(self):
        tree = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('scan_roms','should_exclude_rom')]
        ns = dict(Path=Path, zipfile=Mock())
        exec(compile(ast.Module(body=functions,type_ignores=[]), '<catalog>', 'exec'), ns)
        cfg = json.loads(Path(__file__).with_name('systems').joinpath('fm7.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            for name in ['Game (Disk 1).d77','Game (Disk 2).d77','Game (Disk 3).d77','Other.d88','Tape.t77','Save.xm7','fm7.zip']:
                (Path(tmp)/name).touch()
            cfg['rom_dir'] = tmp
            with contextlib.redirect_stdout(io.StringIO()):
                result = ns['scan_roms'](cfg)
            self.assertEqual({p.name for p in result}, {'Game (Disk 1).d77','Other.d88'})
            ns['zipfile'].ZipFile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
