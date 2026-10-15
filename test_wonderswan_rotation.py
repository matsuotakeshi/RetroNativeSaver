from pathlib import Path
import tempfile
import unittest
from wonderswan_rotation import orientation_from_rom


class OrientationTests(unittest.TestCase):
    def test_vertical_flag_and_unrelated_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'game.ws'
            for flag in (0, 1, 2, 3, 254, 255):
                with self.subTest(flag=flag):
                    data = bytes(65532) + bytes([flag, 0, 0, 0])
                    path.write_bytes(data)
                    self.assertEqual(orientation_from_rom(path), 'portrait' if flag & 1 else 'landscape')
                    self.assertEqual(path.read_bytes(), data)

    def test_truncated_rom_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'game.wsc'
            path.write_bytes(bytes(9))
            with self.assertRaises(ValueError):
                orientation_from_rom(path)
