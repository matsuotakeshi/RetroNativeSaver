"""Native shell-parent launch contract, error stages, and ownership."""
import contextlib
import ctypes
from ctypes import wintypes as wt
import io
import unittest
from unittest.mock import Mock, patch
import desktop_launch as desktop


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Mock()
        self.user = Mock()
        k, u = self.kernel, self.user
        u.GetShellWindow.return_value = 101
        def pid(hwnd, result):
            self.assertEqual(hwnd, 101)
            ctypes.cast(result, ctypes.POINTER(wt.DWORD)).contents.value = 55
            return 66
        u.GetWindowThreadProcessId.side_effect = pid
        k.OpenProcess.return_value = 90
        k.GetDllDirectoryW.return_value = 0
        k.SetDllDirectoryW.return_value = 1
        k.CloseHandle.return_value = 1
        def initialize(address, count, flags, size):
            self.assertEqual((count, flags), (1, 0))
            if address is None:
                ctypes.cast(size, ctypes.POINTER(ctypes.c_size_t)).contents.value = 64
                ctypes.set_last_error(122)
                return 0
            return 1
        k.InitializeProcThreadAttributeList.side_effect = initialize
        def update(address, flags, attribute, value, size, old, returned):
            self.assertEqual(attribute, desktop.PROC_THREAD_ATTRIBUTE_PARENT_PROCESS)
            self.assertEqual(ctypes.cast(value, ctypes.POINTER(wt.HANDLE)).contents.value, 90)
            self.assertEqual(size, ctypes.sizeof(wt.HANDLE))
            return 1
        k.UpdateProcThreadAttribute.side_effect = update
        def create(exe, command, sec1, sec2, inherit, flags, env, cwd, startup, info):
            self.assertEqual(exe, 'C:/RA/retroarch.exe')
            self.assertIn('"a b.rom"', command.value)
            self.assertEqual(cwd, 'C:/RA')
            self.assertFalse(inherit)
            self.assertEqual(flags, desktop.EXTENDED_STARTUPINFO_PRESENT | desktop.CREATE_NEW_PROCESS_GROUP)
            self.assertFalse(flags & 0x01000000)
            start = ctypes.cast(startup, ctypes.POINTER(desktop.StartupInfoEx)).contents
            self.assertEqual(start.StartupInfo.cb, ctypes.sizeof(desktop.StartupInfoEx))
            self.assertEqual(start.StartupInfo.lpDesktop, 'winsta0\\default')
            self.assertTrue(start.lpAttributeList)
            result = ctypes.cast(info, ctypes.POINTER(desktop.ProcessInfo)).contents
            result.hProcess, result.hThread, result.dwProcessId = 10, 20, 30
            return 1
        k.CreateProcessW.side_effect = create
        self.patch = patch.object(ctypes, 'WinDLL', side_effect=lambda name, **kw: k if name == 'kernel32' else u)
        self.patch.start();self.addCleanup(self.patch.stop)

    def run_launch(self):
        with contextlib.redirect_stdout(io.StringIO()) as log:
            result = desktop.start_process(['C:/RA/retroarch.exe', 'a b.rom'], 'C:/RA')
        return result, log.getvalue()

    def denied(self, *args):
        ctypes.set_last_error(5)
        return 0

    def test_shell_parent_no_breakaway_no_inherited_handles_and_all_cleanup(self):
        result, log = self.run_launch()
        self.assertEqual(result, 30)
        self.assertIn('desktop parent pid=55; created pid=30', log)
        self.kernel.OpenProcess.assert_called_once_with(0x80, False, 55)
        self.assertEqual([x.args[0] for x in self.kernel.CloseHandle.call_args_list], [20, 10, 90])
        self.kernel.DeleteProcThreadAttributeList.assert_called_once()
        self.assertEqual(self.kernel.SetDllDirectoryW.call_count, 2)

    def test_absent_shell_fails_without_saver_parent_fallback(self):
        self.user.GetShellWindow.return_value = 0
        with self.assertRaisesRegex(RuntimeError, 'normal desktop shell'):
            self.run_launch()
        self.kernel.OpenProcess.assert_not_called()
        self.kernel.CreateProcessW.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_shell_pid_failure_reports_stage(self):
        self.user.GetWindowThreadProcessId.side_effect = self.denied
        with self.assertRaisesRegex(OSError, 'GetWindowThreadProcessId'):
            self.run_launch()
        self.kernel.OpenProcess.assert_not_called()

    def test_parent_open_failure_reports_stage_and_winerror(self):
        self.kernel.OpenProcess.side_effect = self.denied
        with self.assertRaises(OSError) as error:
            self.run_launch()
        self.assertEqual(error.exception.winerror, 5)
        self.assertIn('OpenProcess', str(error.exception))
        self.kernel.CreateProcessW.assert_not_called()

    def test_invalid_sizing_result_closes_parent_without_delete(self):
        self.kernel.InitializeProcThreadAttributeList.side_effect = self.denied
        with self.assertRaisesRegex(OSError, 'InitializeProcThreadAttributeList'):
            self.run_launch()
        self.kernel.CloseHandle.assert_called_once_with(90)
        self.kernel.DeleteProcThreadAttributeList.assert_not_called()

    def test_initialization_failure_does_not_delete_uninitialized_attributes(self):
        original = self.kernel.InitializeProcThreadAttributeList.side_effect
        self.kernel.InitializeProcThreadAttributeList.side_effect = lambda address, *args: original(address, *args) if address is None else self.denied()
        with self.assertRaisesRegex(OSError, 'InitializeProcThreadAttributeList'):
            self.run_launch()
        self.kernel.CloseHandle.assert_called_once_with(90)
        self.kernel.DeleteProcThreadAttributeList.assert_not_called()

    def test_update_failure_releases_attributes_and_parent(self):
        self.kernel.UpdateProcThreadAttribute.side_effect = self.denied
        with self.assertRaisesRegex(OSError, 'UpdateProcThreadAttribute'):
            self.run_launch()
        self.kernel.DeleteProcThreadAttributeList.assert_called_once()
        self.kernel.CloseHandle.assert_called_once_with(90)
        self.kernel.SetDllDirectoryW.assert_not_called()

    def test_dll_clear_failure_releases_parent_without_starting_or_restoring(self):
        self.kernel.SetDllDirectoryW.side_effect = self.denied
        with self.assertRaisesRegex(OSError, 'SetDllDirectoryW'):
            self.run_launch()
        self.kernel.DeleteProcThreadAttributeList.assert_called_once()
        self.kernel.CloseHandle.assert_called_once_with(90)
        self.kernel.CreateProcessW.assert_not_called()
        self.kernel.SetDllDirectoryW.assert_called_once_with(None)

    def test_create_failure_has_stage_and_never_retries_inside_saver_job(self):
        self.kernel.CreateProcessW.side_effect = self.denied
        with self.assertRaises(OSError) as error:
            self.run_launch()
        self.assertEqual(error.exception.winerror, 5)
        self.assertIn('CreateProcessW(desktop parent)', str(error.exception))
        self.kernel.CreateProcessW.assert_called_once()
        self.kernel.DeleteProcThreadAttributeList.assert_called_once()
        self.kernel.CloseHandle.assert_called_once_with(90)
        self.assertEqual(self.kernel.SetDllDirectoryW.call_count, 2)

    def test_private_dll_directory_is_restored(self):
        def previous(size, buffer):
            buffer.value = 'C:/Saver/_internal'
            return len(buffer.value)
        self.kernel.GetDllDirectoryW.side_effect = previous
        self.run_launch()
        self.assertEqual([x.args[0] for x in self.kernel.SetDllDirectoryW.call_args_list], [None, 'C:/Saver/_internal'])

    def test_overlong_dll_directory_releases_parent(self):
        self.kernel.GetDllDirectoryW.return_value = 32768
        with self.assertRaisesRegex(OSError, 'too long'):
            self.run_launch()
        self.kernel.CloseHandle.assert_called_once_with(90)
        self.kernel.SetDllDirectoryW.assert_not_called()

    def test_close_and_restore_failures_do_not_hide_success_or_skip_other_handles(self):
        self.kernel.CloseHandle.return_value = 0
        self.kernel.SetDllDirectoryW.side_effect = [1, 0]
        result, log = self.run_launch()
        self.assertEqual(result, 30)
        self.assertEqual(self.kernel.CloseHandle.call_count, 3)
        self.assertEqual(log.count('process handle close warning'), 3)
        self.assertIn('DLL search path restore warning', log)


if __name__ == '__main__':
    unittest.main()
