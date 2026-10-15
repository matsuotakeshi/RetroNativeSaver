from pathlib import Path
import struct
import io
from contextlib import redirect_stdout
import tempfile
import unittest
from unittest.mock import Mock, patch
import supervisor_guard as g


class GuardTests(unittest.TestCase):
    def test_heartbeat_and_timeout(self):
        tracker = g.StallTracker(0, 30)
        for t in range(40):
            self.assertFalse(tracker.stalled(t+1, t))
        for t in range(40, 69):
            self.assertFalse(tracker.stalled(40, t))
        self.assertTrue(tracker.stalled(40, 69))

    def test_resume_gap_gives_parent_a_fresh_grace_period(self):
        tracker = g.StallTracker(0, 30)
        tracker.stalled(5, 0)
        self.assertFalse(tracker.stalled(5, 3600))
        for t in range(3601, 3630):
            self.assertFalse(tracker.stalled(5, t))
        self.assertTrue(tracker.stalled(5, 3630))

    def watch(self, creation=123, sequence=(0x102,), value=0):
        kernel = Mock()
        kernel.OpenProcess.return_value = 17
        kernel.WaitForSingleObject.side_effect = sequence
        shared = Mock()
        shared.__enter__ = Mock(return_value=shared)
        shared.__exit__ = Mock(return_value=False)
        shared.read.return_value = struct.pack('<Q', value)
        clock = [0]
        captured = io.StringIO()
        with redirect_stdout(captured), tempfile.TemporaryDirectory() as tmp, patch.object(g, 'bind', return_value=kernel), \
                patch.object(g, 'created_at', return_value=creation), patch.object(g.mmap, 'mmap', return_value=shared), \
                patch.object(g.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(g.time, 'sleep', side_effect=lambda s: clock.__setitem__(0, clock[0]+s)):
            g.watch(77, 123, 'tag', tmp, timeout=2)
            self.assertFalse(list(Path(tmp).glob('*.jsonl')))
            log = captured.getvalue()
        return kernel, log

    def test_creation_mismatch_never_terminates_reused_pid(self):
        kernel, log = self.watch(creation=124)
        kernel.TerminateProcess.assert_not_called()
        self.assertIn('identity_mismatch', log)

    def test_normal_completion_and_process_exit_never_terminate(self):
        for sequence in ((0,), (0x102,)):
            kernel, _ = self.watch(sequence=sequence)
            kernel.TerminateProcess.assert_not_called()

    def test_stall_terminates_only_opened_parent_handle(self):
        kernel, log = self.watch(sequence=(0x102,)*3, value=10)
        kernel.TerminateProcess.assert_called_once_with(17, 77)
        self.assertIn('supervisor_stalled', log)

    def test_wait_error_is_not_a_stall(self):
        kernel, log = self.watch(sequence=(0xffffffff,))
        kernel.TerminateProcess.assert_not_called()
        self.assertIn('wait_failed', log)


if __name__ == '__main__':
    unittest.main()
