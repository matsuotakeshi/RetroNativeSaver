from pathlib import Path
import tempfile,unittest,zipfile
import computer_disks as d

class SplitDiskZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def archive(self,stem,entries):
        p=self.root/(stem+'.zip')
        with zipfile.ZipFile(p,'w') as z:
            for name,data in entries:z.writestr(name,data)
        return p
    def disk(self,label,ext='.dim',suffix=''):
        stem=f'Game (Disk {label}){suffix}'
        return self.archive(stem,[(stem+ext,label.encode())])
    def test_two_separate_archives_for_all_common_computer_modes(self):
        for sid,ext in [('pc98','.hdm'),('x1','.d88'),('x68000','.dim'),('fm7','.d77')]:
            for first,second in [('1','2'),('A','B')]:
                with self.subTest(sid=sid,labels=first+second):
                    a=self.disk(first,ext,suffix=sid+first);b=self.disk(second,ext,suffix=sid+first)
                    cfg=dict(id=sid,rom_dir=str(self.root));(self.root/'fm7.zip').touch()
                    before=(a.read_bytes(),b.read_bytes())
                    out=self.root/(sid+first)
                    boot=d.prepare(cfg,a,out)
                    self.assertEqual((out/('drive1'+ext)).read_bytes(),first.encode())
                    self.assertEqual((out/('drive2'+ext)).read_bytes(),second.encode())
                    self.assertEqual(before,(a.read_bytes(),b.read_bytes()))
                    self.assertTrue(boot.is_file())
    def test_combined_labels_and_secondary_fixed_catalog_entry(self):
        a=self.disk('1 of 3)(Disk A');b=self.disk('2 of 3)(Disk B');self.disk('3 of 3)(Disk C')
        for source in (a,b):
            selected=d.zip_disks(source,d.FORMATS['x68000'],'x68000')
            self.assertEqual([p for p,m in selected],[a,b])
    def test_alt_revision_not_mixed(self):
        a=self.disk('A',suffix='[a]');self.disk('B')
        self.assertEqual(len(d.zip_disks(a,d.FORMATS['x68000'],'x68000')),1)
    def test_pair_inside_archive_has_precedence(self):
        a=self.archive('Game (Disk 1)',[('Game (Disk 1).dim',b'1'),('Game (Disk 2).dim',b'2')])
        self.disk('2')
        self.assertEqual([p for p,m in d.zip_disks(a,d.FORMATS['x68000'],'x68000')],[a,a])
    def test_archive_label_does_not_override_valid_inside_pair(self):
        a=self.archive('Game (Disk 2)',[('Game (Disk 1).dim',b'1'),('Game (Disk 2).dim',b'2')])
        self.assertEqual([p for p,m in d.zip_disks(a,d.FORMATS['x68000'],'x68000')],[a,a])
    def test_wrong_companion_content_rejected(self):
        a=self.disk('A');self.archive('Game (Disk B)',[('Other (Disk B).dim',b'wrong')])
        with self.assertRaises(ValueError):d.zip_disks(a,d.FORMATS['x68000'],'x68000')
    def test_multiple_companion_images_rejected(self):
        a=self.disk('A');self.archive('Game (Disk B)',[('one/Game (Disk B).dim',b'b'),('two/Game (Disk B).dim',b'b')])
        with self.assertRaises(ValueError):d.zip_disks(a,d.FORMATS['x68000'],'x68000')
    def test_missing_boot_rejected_and_single_disk_unchanged(self):
        b=self.disk('B')
        with self.assertRaises(ValueError):d.zip_disks(b,d.FORMATS['x68000'],'x68000')
        solo=self.archive('Single',[('Single.dim',b'single')])
        self.assertEqual(d.zip_disks(solo,d.FORMATS['x68000'],'x68000'),[(solo,Path('Single.dim'))])
    def test_multiple_companion_archives_rejected(self):
        a=self.disk('A');self.disk('2');self.disk('B')
        with self.assertRaises(ValueError):d.zip_disks(a,d.FORMATS['x68000'],'x68000')
    def test_companion_duplicate_members_rejected(self):
        import warnings
        a=self.disk('A')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.archive('Game (Disk B)',[('Game (Disk B).dim',b'1'),('Game (Disk B).dim',b'2')])
        with self.assertRaises(ValueError):d.zip_disks(a,d.FORMATS['x68000'],'x68000')

if __name__=='__main__':unittest.main()

