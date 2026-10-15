from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, call

from memory_cards import attach_controller, ecc128, empty_ps2_card, prepare


class MemoryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = empty_ps2_card()

    def test_ps2_geometry_fat_and_empty_directory(self):
        image = self.image
        self.assertEqual(len(image), 8 * 1024 * 1024 // 512 * 528)
        data = b''.join(image[i:i+512] for i in range(0, len(image), 528))
        self.assertTrue(data.startswith(b'Sony PS2 Memory Card Format 1.2.0.0'))
        self.assertEqual(struct.unpack_from('<HHH', data, 40), (512, 2, 16))
        self.assertEqual(struct.unpack_from('<III', data, 48), (8192, 41, 8135))
        self.assertEqual(struct.unpack_from('<I', data, 80)[0], 8)
        self.assertEqual(struct.unpack_from('<32I', data, 8*1024), tuple(range(9, 41)))
        fat = struct.unpack_from('<8192I', data, 9*1024)
        self.assertEqual(fat.count(0x7fffffff), 8134)
        self.assertEqual(fat[0], 0xffffffff)
        root = 41*1024
        self.assertEqual(struct.unpack_from('<I', data, root+4)[0], 2)
        self.assertEqual(data[root+64:root+66], b'.\0')
        self.assertEqual(data[root+512+64:root+512+67], b'..\0')
        self.assertEqual(data[42*1024:8176*1024], bytes((8176-42)*1024))

    def test_ecc_known_vectors(self):
        self.assertEqual(ecc128(bytes(128)), bytes.fromhex('777f7f'))
        self.assertEqual(ecc128(b'\x01'+bytes(127)), bytes.fromhex('70007f'))
        self.assertEqual(ecc128(bytes(127)+b'\x80'), bytes.fromhex('077f00'))

    def test_ps2_written_page_ecc(self):
        # Every distinct stored page must have matching spare ECC; backup erase block excepted.
        pages = {self.image[i:i+528] for i in range(0, len(self.image), 528)}
        for page in pages:
            if page == b'\xff'*528:
                continue
            expected = b''.join(ecc128(page[j:j+128]) for j in range(0, 512, 128))
            self.assertEqual(page[512:524], expected)

    def test_dreamcast_never_copies_user_cards_or_precreates_zero_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dc = root/'original/dc'
            dc.mkdir(parents=True)
            for name, value in [('dc_boot.bin', b'bios'), ('dc_flash.bin', b'flash'),
                                ('vmu_save_A1.bin', b'player save'), ('dc_nvmem.bin', b'player settings')]:
                (dc/name).write_bytes(value)
            (root/'slot').mkdir()
            settings = {'id': 'dreamcast', 'core_options': {'reicast_per_content_vmus': 'All VMUs'}}
            system, save, options = prepare(settings, root/'original', root/'slot')
            self.assertEqual((system/'dc/dc_boot.bin').read_bytes(), b'bios')
            self.assertFalse(list((system/'dc').glob('vmu*')))
            self.assertFalse((system/'dc/dc_nvmem.bin').exists())
            self.assertEqual(options['reicast_device_port1_slot1'], 'VMU')
            self.assertEqual(options['reicast_per_content_vmus'], 'disabled')
            self.assertEqual(settings['core_options']['reicast_per_content_vmus'], 'All VMUs')
            self.assertEqual((dc/'vmu_save_A1.bin').read_bytes(), b'player save')

    def test_ps2_sessions_use_independent_fresh_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root/'original/pcsx2'
            (original/'bios').mkdir(parents=True)
            (original/'bios/bios.bin').write_bytes(b'bios')
            (original/'memcards').mkdir()
            (original/'memcards/Mcd001.ps2').write_bytes(b'player save')
            (original/'inis').mkdir()
            (original/'inis/PCSX2.ini').write_text('MemoryCards=external/path')
            results = []
            for index in range(2):
                slot = root/str(index)
                slot.mkdir()
                results.append(prepare({'id': 'ps2'}, root/'original', slot))
            first, second = (r[0]/'pcsx2/memcards/Mcd001.ps2' for r in results)
            self.assertEqual(first.read_bytes(), self.image)
            first.write_bytes(b'changed during game')
            self.assertEqual(second.read_bytes(), self.image)
            self.assertEqual((original/'memcards/Mcd001.ps2').read_bytes(), b'player save')
            self.assertFalse((results[0][0]/'pcsx2/inis').exists())
            self.assertEqual(results[0][2]['pcsx2_shared_memory_cards'], 'enabled')
            with self.assertRaises(FileExistsError):
                prepare({'id': 'ps2'}, root/'original', root/'0')

    def test_flycast_initializes_all_ports_to_activate_vmu(self):
        dll = Mock()
        attach_controller(dll)
        self.assertEqual(dll.retro_set_controller_port_device.call_args_list,
                         [call(0, 1), call(1, 0), call(2, 0), call(3, 0)])

    def test_ps2_uses_only_two_ports(self):
        dll = Mock()
        attach_controller(dll, 2)
        self.assertEqual(dll.retro_set_controller_port_device.call_args_list, [call(0, 1), call(1, 0)])


if __name__ == '__main__':
    unittest.main()
