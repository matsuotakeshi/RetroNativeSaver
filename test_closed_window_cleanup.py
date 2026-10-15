"""Regression: keyboard closes HWND before scheduler cleanup starts."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import process_cleanup


class ClosedWindowCleanupTests(unittest.TestCase):
    def dispose(self, win, slots):
        tree=ast.parse(Path(__file__).with_name('independent_slots.py').read_text(encoding='utf-8'))
        run=next(n for n in tree.body if getattr(n,'name','')=='run_scheduler')
        fn=next(n for n in run.body if getattr(n,'name','')=='dispose')
        remove=Mock()
        ns=dict(win=win,slots=slots,exit_record=Mock(),retain=process_cleanup.retain,
                close_trace=process_cleanup.close_trace,shutil=SimpleNamespace(rmtree=remove))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual dispose>','exec'),ns)
        return ns['dispose'],remove

    def test_closed_window_cleanup_finishes_and_reaps_every_child(self):
        for reason in ('key-down','system-key-down','mouse-move','tile-user-exit','WM_CLOSE'):
            win=SimpleNamespace(should_close=True,exit_reason=reason,
                present=Mock(side_effect=RuntimeError('GetClientRect failed (destroyed HWND)')))
            records=[dict(proc=Mock(),trace=Mock(),content_dir=str(i)) for i in range(3)]
            for r in records:r['proc'].poll.return_value=None
            slots=records.copy();dispose,remove=self.dispose(win,slots)
            kernel=Mock();kernel.CloseHandle.return_value=True;temp=Mock()
            process_cleanup.cleanup_scheduler(SimpleNamespace(kernel32=kernel), 1, slots, dispose, temp)
            self.assertEqual(slots,[None]*3);self.assertEqual(remove.call_count,3)
            win.present.assert_not_called();temp.cleanup.assert_called_once()
            for r in records:
                r['proc'].kill.assert_called_once();r['proc'].wait.assert_called_once_with(timeout=5)
                r['trace'].close.assert_called_once()

    def test_live_replacement_still_repaints_and_propagates_drawing_failure(self):
        for error in (None,RuntimeError('live drawing failure')):
            win=SimpleNamespace(should_close=False,present=Mock(side_effect=error))
            proc=Mock();proc.poll.return_value=75;trace=Mock();slots=[dict(proc=proc,trace=trace,content_dir='tile')]
            dispose,remove=self.dispose(win,slots)
            if error:
                with self.assertRaisesRegex(RuntimeError,'live drawing failure'):dispose(0)
            else:dispose(0)
            win.present.assert_called_once();trace.close.assert_called_once();remove.assert_called_once()
            self.assertEqual(slots,[None])

    def test_real_cleanup_failure_is_not_hidden_by_closed_window(self):
        win=SimpleNamespace(should_close=True,present=Mock())
        proc=Mock();proc.poll.return_value=None;proc.wait.side_effect=TimeoutError('child still alive')
        trace=Mock();record=dict(proc=proc,trace=trace,content_dir='live');slots=[record]
        dispose,remove=self.dispose(win,slots)
        retained=list(process_cleanup._retained)
        try:
            with self.assertRaises(TimeoutError):dispose(0)
            self.assertIs(slots[0],record);trace.close.assert_not_called();remove.assert_not_called()
            win.present.assert_not_called();self.assertIn(record,process_cleanup._retained)
        finally:process_cleanup._retained[:]=retained


if __name__=='__main__':unittest.main()
