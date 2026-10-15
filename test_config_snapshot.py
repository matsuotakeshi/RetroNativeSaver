import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from config_snapshot import ConfigSnapshot, load_worker_config, ENV_KEY, MAX_BYTES


@unittest.skipUnless(os.name == 'nt', 'Windows named mappings')
class ConfigSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'config.json'
        self.path.write_text('{"cycle_seconds":999}', encoding='utf-8')

    def snapshot(self, config):
        result = ConfigSnapshot(config)
        self.addCleanup(result.close)
        environment = {}; result.apply(environment)
        return result, environment

    def test_file_change_and_deletion_do_not_change_snapshot(self):
        config = {'cycle_seconds': 180, 'text': '日本語', 'nested': [1, False, None]}
        snapshot, environment = self.snapshot(config)
        config['cycle_seconds'] = 1
        self.path.unlink()
        self.assertEqual(load_worker_config(self.path, environment)['cycle_seconds'], 180)

    def test_separate_worker_process_can_read_parent_snapshot(self):
        snapshot, values = self.snapshot({'cycle_seconds': 180})
        self.path.unlink()
        environment = os.environ.copy(); environment.update(values)
        result = subprocess.run([sys.executable, '-c',
            'import os,sys; from config_snapshot import load_worker_config; assert load_worker_config(sys.argv[1],os.environ)=={"cycle_seconds":180}',
            str(self.path)], cwd=Path(__file__).parent, env=environment,
            capture_output=True, timeout=10, creationflags=0x08000000)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_descriptor_never_falls_back_to_valid_file(self):
        for value in ('', '[]', '{}', 'null', '{', json.dumps({'tag':'wrong', 'size':1,'sha256':'0'*64})):
            with self.assertRaises(ValueError): load_worker_config(self.path, {ENV_KEY:value})

    def test_tampered_and_closed_mapping_rejected(self):
        snapshot, environment = self.snapshot({'value': 1})
        snapshot.mapping[0] = ord('[')
        with self.assertRaisesRegex(ValueError, 'integrity'): load_worker_config(self.path, environment)
        snapshot.close(); snapshot.close()
        with self.assertRaises(ValueError): load_worker_config(self.path, environment)

    def test_direct_worker_without_descriptor_uses_file(self):
        self.assertEqual(load_worker_config(self.path, {}), {'cycle_seconds':999})

    def test_failed_write_closes_mapping(self):
        from unittest.mock import Mock
        mapping = Mock(); mapping.write.side_effect = OSError('write failure')
        with patch('config_snapshot.mmap.mmap', return_value=mapping):
            with self.assertRaises(OSError): ConfigSnapshot({})
        mapping.close.assert_called_once()

    def test_large_config_uses_short_environment_descriptor(self):
        config = {'text':'a' * 100000}
        snapshot, values = self.snapshot(config)
        self.assertLess(len(values[ENV_KEY]), 512)
        self.assertEqual(load_worker_config(self.path, values), config)

    def test_size_and_type_validation_before_mapping(self):
        with patch('config_snapshot.mmap.mmap') as opening:
            with self.assertRaises(ValueError): ConfigSnapshot([])
            with patch('config_snapshot.MAX_BYTES', 3):
                with self.assertRaises(ValueError): ConfigSnapshot({'x':1})
            opening.assert_not_called()


if __name__ == '__main__': unittest.main()
