from pathlib import Path
import tempfile, unittest, zipfile
import computer_disks as d


class ComputerDiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def file(self,name):
        path=self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(name.encode())
        return path

    def test_combined_labels(self):
        a=self.file('Game (Disk 1 of 3)(Disk A).dim')
        b=self.file('Game (Disk 2 of 3)(Disk B).dim')
        c=self.file('Game (Disk 3 of 3)(Disk C).dim')
        self.assertEqual(d.select(a,[a,b,c]),[a,b])
        self.assertEqual(d.candidates([a,b,c]),[a])

    def test_revisions_not_mixed(self):
        a=self.file('Game (Disk 1 of 2).dim')
        b=self.file('Game (Disk 2 of 2)[a].dim')
        self.assertEqual(d.select(a,[a,b]),[a])

    def test_zip_two_disks(self):
        source=self.root/'game.zip'
        with zipfile.ZipFile(source,'w') as z:
            for n in (1,2,3): z.writestr(f'Game (Disk {n}).hdm',bytes([n]))
        result=d.prepare({'id':'pc98'},source,self.root/'out')
        self.assertTrue(result.read_text().startswith('np2kai "'))
        self.assertEqual((result.parent/'drive2.hdm').read_bytes(),b'\x02')
        self.assertFalse((result.parent/'drive3.hdm').exists())

    def test_zip_ambiguous_rejected(self):
        source=self.root/'game.zip'
        with zipfile.ZipFile(source,'w') as z:
            z.writestr('Game (Disk A).hdm',b'a')
            z.writestr('Other (Disk A).hdm',b'b')
        with self.assertRaises(ValueError): d.prepare({'id':'pc98'},source,self.root/'out')

    def test_zip_paths_cannot_escape(self):
        source=self.root/'game.zip'
        with zipfile.ZipFile(source,'w') as z: z.writestr('../../outside.hdm',b'a')
        result=d.prepare({'id':'pc98'},source,self.root/'out')
        self.assertEqual((result.parent/'drive1.hdm').read_bytes(),b'a')
        self.assertFalse((self.root/'outside.hdm').exists())

    def test_hard_disk_standalone(self):
        source=self.file('Game.hdi')
        result=d.prepare({'id':'pc98'},source,self.root/'out')
        self.assertEqual(result.suffix,'.hdi')
        result.write_bytes(b'changed')
        self.assertEqual(source.read_bytes(),b'Game.hdi')

    def test_x1_and_x68000_playlists(self):
        for sid,ext in [('x1','.d88'),('x68000','.dim')]:
            folder=self.root/sid
            a=self.file(f'{sid}/Game (Disk A){ext}')
            self.file(f'{sid}/Game (Disk B){ext}')
            result=d.prepare({'id':sid},a,folder/'out')
            self.assertEqual(len(result.read_text().splitlines()),2)
            self.assertTrue(all(Path(line).exists() for line in result.read_text().splitlines()))

    def test_firmware_isolation(self):
        self.file('bios/np2kai/bios.rom')
        self.file('bios/np2kai/np2kai.cfg')
        self.file('bios/np2kai/d8000.rom')
        target=d.isolated_system_dir({'id':'pc98'},self.root/'bios',self.root/'out')
        self.assertTrue((target/'np2kai/bios.rom').exists())
        self.assertFalse((target/'np2kai/np2kai.cfg').exists())
        self.assertFalse((target/'np2kai/d8000.rom').exists())

    def test_duplicate_formats_prefer_nfd(self):
        source=self.root/'game.zip'
        with zipfile.ZipFile(source,'w') as z:
            for ext in ('.d88','.nfd'):
                for letter in ('A','B'): z.writestr(f'Game (Disk {letter}){ext}',ext.encode())
        result=d.prepare({'id':'pc98'},source,self.root/'out')
        self.assertEqual((result.parent/'drive1.nfd').read_bytes(),b'.nfd')

    def test_archive_alts_do_not_replace_primary(self):
        source=self.root/'game.zip'
        with zipfile.ZipFile(source,'w') as z:
            z.writestr('Game (Disk 1).hdm',b'primary')
            z.writestr('Game (Disk 2).hdm',b'second')
            z.writestr('alts/Game (Disk 1) [Alt].hdm',b'alternate')
        result=d.prepare({'id':'pc98'},source,self.root/'out')
        self.assertEqual((result.parent/'drive1.hdm').read_bytes(),b'primary')
