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

    def test_numbered_set_overrides_secondary_disk_labels(self):
        disks = [self.file(f'Game (Disk {n} of 5)({note}).dim')
                 for n, note in enumerate(('System', 'Disk 1', 'Disk 2', 'Disk 3', 'Disk 4'), 1)]
        self.assertEqual(d.candidates(disks), disks[:1])
        for source in disks:
            self.assertEqual(d.select(source, disks), disks[:2])

    def test_numbered_set_preserves_metadata_and_total(self):
        first = self.file('Game (1991)(Maker)(Disk 1 of 5)(System).dim')
        others = [self.file(name + '.dim') for name in (
            'Other (1991)(Maker)(Disk 2 of 5)(Disk 1)',
            'Game (1992)(Maker)(Disk 2 of 5)(Disk 1)',
            'Game (1991)(Maker)(Disk 2 of 5)(Disk 1)[a]',
            'Game (1991)(Maker)(Disk 2 of 5)(Disk 1)(Rev 2)',
            'Game (1991)(Maker)(Disk 2 of 5)(Unknown)',
            'Game (1991)(Maker)(Disk 2 of 4)(Disk 1)',
        )]
        self.assertEqual(d.select(first, [first, *others]), [first])

    def test_plain_disk_number_and_letter_fallback(self):
        for labels in (('1', '2'), ('A', 'B')):
            disks = [Path(f'Game (Disk {label}).dim') for label in labels]
            self.assertEqual(d.select(disks[1], disks), disks)

    def test_numbered_disc_spelling_case_and_letter_note(self):
        disks = [Path('Game (DISC 1 OF 3)(System).dim'),
                 Path('Game (disc 2 of 3)(Disc A).dim')]
        self.assertEqual(d.select(disks[1], disks), disks)

    def test_role_notes_without_numbered_set_are_preserved(self):
        disks = [Path('Game (Disk 1)(System).dim'), Path('Game (Disk 2)(Data).dim')]
        self.assertEqual(d.select(disks[0], disks), disks[:1])

    def test_numbered_set_duplicate_boot_is_rejected(self):
        disks = [Path('Game (Disk 1 of 3)(System).dim'),
                 Path('Game (Disk 1 of 3)(Disk A).dim'),
                 Path('Game (Disk 2 of 3)(Disk B).dim')]
        with self.assertRaisesRegex(ValueError, 'Ambiguous disk 1'):
            d.select(disks[2], disks)

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
