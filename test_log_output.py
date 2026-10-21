"""Log opt-in never disables in-memory monitoring or changes runtime policy."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import log_output


class LogOutputTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_missing_legacy_and_invalid_config_default_off(self):
        self.assertFalse(log_output.enabled([], self.root, {}))
        for content in ('{}', '{"log_output_enabled": false}', '[]', '{bad', '{"log_output_enabled": "true"}'):
            (self.root / 'config.json').write_text(content, encoding='utf-8')
            self.assertFalse(log_output.enabled([], self.root, {}))

    def test_custom_config_true(self):
        path = self.root / 'custom.json'
        path.write_text('{"log_output_enabled":true}', encoding='utf-8')
        for args in (['--config', str(path)], ['--config=' + str(path)]):
            self.assertTrue(log_output.enabled(args, self.root, {}))

    def test_children_keep_parent_choice_all_three_roles(self):
        (self.root / 'config.json').write_text('{"log_output_enabled":true}', encoding='utf-8')
        for flag in log_output.CHILD_FLAGS:
            self.assertFalse(log_output.enabled([flag], self.root, {log_output.ENV_KEY: '0'}))
            self.assertTrue(log_output.enabled([flag], self.root, {log_output.ENV_KEY: '1'}))

    def test_host_ignores_stale_inherited_setting(self):
        self.assertFalse(log_output.enabled([], self.root, {log_output.ENV_KEY: '1'}))

    def test_off_creates_no_files_and_discards_prints(self):
        with patch.dict(os.environ, {}, clear=True), patch('log_output.sys.stdout'), patch('log_output.sys.stderr'), patch('log_output.open_log') as opening:
            _, path, handle = log_output.install(self.root, [])
            import sys
            sys.stdout.write('ordinary output')
            sys.stderr.write('error output')
            sys.stdout.flush()
            self.assertEqual(os.environ[log_output.ENV_KEY], '0')
        opening.assert_not_called()
        self.assertIsNone(path)
        self.assertIsNone(handle)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_on_records_normal_output(self):
        (self.root / 'config.json').write_text('{"log_output_enabled":true}', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True), patch('log_output.sys.stdout', None), patch('log_output.sys.stderr', None):
            _, path, handle = log_output.install(self.root, [])
            try:
                import sys
                sys.stdout.write('normal monitoring\n')
                sys.stderr.write('error\n')
            finally:
                handle.close()
        self.assertIn('normal monitoring', path.read_text(encoding='utf-8'))
        self.assertIn('ERR error', path.read_text(encoding='utf-8'))

    def test_file_unavailable_does_not_abort_startup(self):
        with patch('log_output.Path.mkdir', side_effect=PermissionError()):
            _, path, handle = log_output.open_log(self.root)
        self.assertIsNone(path)
        self.assertIsNone(handle)

    def test_explicit_measurement_only_creates_its_directory(self):
        with patch.dict(os.environ, RNS_STARTUP_TIMING='1'), patch('log_output.sys.stdout'), patch('log_output.sys.stderr'):
            directory, path, handle = log_output.install(self.root, [])
        self.assertTrue(directory.exists())
        self.assertEqual(list(directory.iterdir()), [])
        self.assertIsNone(path)


if __name__ == '__main__':
    unittest.main()
