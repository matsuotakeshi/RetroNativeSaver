import ast
import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from independent_slots import run_scheduler

class ParentStandbyTests(unittest.TestCase):
    def helper(self):
        source=Path(__file__).with_name('native_saver.py')
        tree=ast.parse(source.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='wait_for_scheduler_standby')
        ns=dict(time=Mock(),kernel32=Mock(),read_runtime_trace=Mock(),wait_for_display_resume=Mock(return_value=0))
        ns['time'].monotonic.return_value=0
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        return ns

    def test_ack_keeps_outer_job_and_window(self):
        ns=self.helper()
        ns['read_runtime_trace'].return_value={'phase':'SLOT_POWER_IDLE'}
        win=Mock(should_close=False)
        proc=Mock(); proc.poll.side_effect=[None,0]
        self.assertEqual(ns['wait_for_scheduler_standby'](win,123,proc,456),0)
        ns['kernel32'].TerminateJobObject.assert_not_called()
        ns['wait_for_display_resume'].assert_not_called()
        win.close.assert_not_called()

    def test_missing_ack_stops_group_without_closing_handle_twice(self):
        ns=self.helper()
        ns['time'].monotonic.side_effect=[0,6]
        ns['read_runtime_trace'].return_value={'phase':'SLOT_SCHEDULER'}
        win=Mock(should_close=False)
        proc=Mock(); proc.poll.return_value=None
        ns['wait_for_scheduler_standby'](win,123,proc,456)
        ns['kernel32'].TerminateJobObject.assert_called_once_with(123,0)
        ns['wait_for_display_resume'].assert_called_once_with(win,None)

    def test_scheduler_initial_dim_starts_no_games_and_retains_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=Mock()
            api.resolve_app_relative_path.return_value=Path(tmp)/'state.json'
            api._persistent_whitelisted_roms.return_value={}
            api._create_worker_job_object.return_value=123
            api.kernel32.CloseHandle.return_value=True
            win=Mock(should_close=False,power_idle=True,hwnd=987)
            calls=[]
            def pump():
                calls.append(1)
                if len(calls)>1:
                    win.should_close=True
            win.pump.side_effect=pump
            with patch('independent_slots.subprocess.Popen') as spawn:
                self.assertEqual(run_scheduler(api,win,[],[],{}, {'persistent_rom_blacklist_enabled':False},Path(tmp)/'favorites.json',{}),0)
                spawn.assert_not_called()
            api.kernel32.CloseHandle.assert_called_once_with(123)
            api.write_runtime_trace.assert_called_once_with('SLOT_POWER_IDLE')
            win.close.assert_not_called()

if __name__=='__main__': unittest.main()
