"""Regression checks without creating windows, loading cores or changing displays."""
from __future__ import annotations
import ast
import ctypes
from pathlib import Path
import unittest
from unittest.mock import Mock
import uuid

SOURCE = Path(__file__).with_name('native_saver.py')


class DisplayRecoveryTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
        names = {'POINT', 'PowerBroadcastSetting', 'GDIDrawingSurface', 'GDIWindow', 'restore_windows_desktop', 'wait_for_display_resume'}
        nodes = []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names:
                nodes.append(node)
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and (
                    target.id.startswith(('WM_', 'PBT_', 'RDW_'))
                    or target.id in ('SW_HIDE', 'SESSION_DISPLAY_GUID')
                ):
                    nodes.append(node)
        self.api = Mock()
        self.api.DefWindowProcW.return_value = 99
        self.ns = dict(ctypes=ctypes, Structure=ctypes.Structure,
                       POINTER=ctypes.POINTER, c_long=ctypes.c_long, byref=ctypes.byref, uuid=uuid, user32=self.api,
                       dwmapi=Mock(), kernel32=Mock(), time=Mock())
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), self.ns)
        cls = self.ns['GDIWindow']
        self.win = cls.__new__(cls)
        self.win.fullscreen = True
        self.win.preview_mode = False
        self.win.should_close = False
        self.win.display_was_off = False
        self.win.display_was_dimmed = False
        self.win.exit_on_display_off = False
        self.win.hold_on_display_power = False
        self.win.power_idle = False
        self.win.power_notification = None
        self.win.exit_reason = 'input'
        self.win.first_mouse = None
        self.win.mouse_exit_threshold = 12

    def power(self, state, length=4, matching=True):
        event = self.ns['PowerBroadcastSetting']()
        event.guid[:] = self.ns['SESSION_DISPLAY_GUID'] if matching else bytes(16)
        event.length = length
        event.state = state
        return self.win._proc(123, self.ns['WM_POWERBROADCAST'],
                              self.ns['PBT_POWERSETTINGCHANGE'], ctypes.addressof(event))

    def test_mouse_exit_logs_reason_only_and_preserves_origin(self):
        import io
        from contextlib import redirect_stdout
        self.win.first_mouse = None
        self.win.mouse_exit_threshold = 12
        self.cursor_positions([(10, 20), (30, 20)])
        capture = io.StringIO()
        with redirect_stdout(capture):
            self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, (20 << 16) | 10)
            self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, (20 << 16) | 30)
            self.win._proc(123, self.ns['WM_CLOSE'], 0, 0)
        self.assertTrue(self.win.should_close)
        self.assertEqual(self.win.exit_reason, 'mouse-move')
        self.assertEqual(capture.getvalue().strip(), '[exit] reason=mouse-move')
        self.assertNotIn('distance=', capture.getvalue())

    def cursor_positions(self, positions):
        positions = iter(positions)
        def read(pointer):
            position = next(positions)
            if position is None:
                return 0
            point = ctypes.cast(pointer, ctypes.POINTER(self.ns['POINT'])).contents
            point.x, point.y = position
            return 1
        self.api.GetCursorPos.side_effect = read

    def test_reported_zero_jump_without_cursor_movement_is_ignored(self):
        self.win.fullscreen = False  # The child tile which caused the recorded exit.
        self.cursor_positions([(907, 325), (907, 325)])
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, (325 << 16) | 907)
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.assertFalse(self.win.should_close)
        self.api.PostMessageW.assert_not_called()

    def test_real_move_to_screen_origin_still_exits(self):
        self.cursor_positions([(20, 0), (0, 0)])
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.assertTrue(self.win.should_close)

    def test_failed_cursor_read_keeps_baseline_and_does_not_exit(self):
        self.cursor_positions([None, (-1900, -200), None, (-1899, -200)])
        for _ in range(4):
            self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.assertEqual(self.win.first_mouse, (-1900, -200))
        self.assertFalse(self.win.should_close)

    def test_negative_monitor_coordinates_and_threshold_boundary(self):
        self.cursor_positions([(-1900, -200), (-1889, -200), (-1888, -200)])
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.assertFalse(self.win.should_close)
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.assertTrue(self.win.should_close)

    def test_preview_ignores_mouse_without_querying_cursor(self):
        self.win.preview_mode = True
        self.win._proc(123, self.ns['WM_MOUSEMOVE'], 0, 0)
        self.api.GetCursorPos.assert_not_called()
        self.assertFalse(self.win.should_close)

    def test_key_log_does_not_include_key_value(self):
        import io
        from contextlib import redirect_stdout
        capture = io.StringIO()
        with redirect_stdout(capture):
            self.win._proc(123, self.ns['WM_KEYDOWN'], 987654, 0)
        self.assertEqual(self.win.exit_reason, 'key-down')
        self.assertNotIn('987654', capture.getvalue())

    def test_initial_on_and_dimming_do_not_exit(self):
        for state in (1, 2, 1):
            self.power(state)
        self.assertFalse(self.win.should_close)
        self.api.ShowWindow.assert_not_called()

    def test_standby_holds_window_through_dim_off_and_topology_change(self):
        self.win.hold_on_display_power = True
        for state in (1, 2, 2, 0):
            self.power(state)
        self.win._proc(123, self.ns['WM_DISPLAYCHANGE'], 0, 0)
        self.assertTrue(self.win.power_idle)
        self.assertFalse(self.win.should_close)
        self.api.ShowWindow.assert_not_called()
        self.api.PostMessageW.assert_not_called()
        self.power(1)
        self.assertTrue(self.win.should_close)
        self.assertEqual(self.win.exit_reason, 'display-resumed-from-standby')

    def test_initial_off_enters_standby_without_closing(self):
        self.win.hold_on_display_power = True
        self.power(0)
        self.assertTrue(self.win.power_idle)
        self.assertFalse(self.win.should_close)

    def test_standby_input_exits(self):
        self.win.hold_on_display_power = True
        self.power(2)
        self.win._proc(123, self.ns['WM_KEYDOWN'], 0, 0)
        self.assertTrue(self.win.should_close)

    def test_wait_closes_job_once_and_pumps_until_input(self):
        backdrop = Mock(should_close=False, exit_reason='input')
        def finish():
            self.ns['kernel32'].CloseHandle.assert_called_once_with(1234)
            backdrop.should_close = True
        backdrop.pump.side_effect = finish
        self.assertEqual(self.ns['wait_for_display_resume'](backdrop, 1234), 0)
        self.ns['kernel32'].CloseHandle.assert_called_once_with(1234)
        backdrop.close.assert_not_called()
        self.ns['time'].sleep.assert_not_called()

    def test_supervisor_exits_on_off_without_waiting_for_resume(self):
        self.win.exit_on_display_off = True
        self.power(1)
        self.assertFalse(self.win.should_close)
        self.power(0)
        self.assertTrue(self.win.should_close)
        self.assertEqual(self.win.exit_reason, 'display-off')
        self.api.PostMessageW.assert_called_once_with(123, self.ns['WM_CLOSE'], 0, 0)

    def test_supervisor_exits_at_dim_before_off(self):
        self.win.exit_on_display_off = True
        self.power(1)
        self.assertFalse(self.win.should_close)
        self.power(2)
        self.assertTrue(self.win.should_close)
        self.assertTrue(self.win.display_was_dimmed)
        self.assertFalse(self.win.display_was_off)
        self.assertEqual(self.win.exit_reason, 'display-dimmed')
        self.api.ShowWindow.assert_called_once_with(123, 0)
        self.power(2)
        self.power(0)
        self.assertEqual(self.win.exit_reason, 'display-dimmed')
        self.api.PostMessageW.assert_called_once()

    def test_dim_cleanup_does_not_redraw_or_flush(self):
        backdrop = Mock(hwnd=123, display_was_off=False, display_was_dimmed=True)
        self.ns['restore_windows_desktop'](backdrop)
        backdrop.close.assert_called_once()
        self.api.RedrawWindow.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()
        self.ns['dwmapi'].DwmFlush.assert_not_called()

    def test_dim_then_on_clears_dim_state_for_regular_window(self):
        self.power(2)
        self.power(1)
        self.assertFalse(self.win.display_was_dimmed)
        self.assertFalse(self.win.should_close)

    def test_sleeping_display_cleanup_does_not_redraw_or_flush(self):
        backdrop = Mock(hwnd=123, display_was_off=True)
        self.ns['restore_windows_desktop'](backdrop)
        backdrop.close.assert_called_once()
        self.api.RedrawWindow.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()
        self.ns['dwmapi'].DwmFlush.assert_not_called()
        self.api.ChangeDisplaySettingsExW.assert_not_called()

    def test_off_then_on_exits_and_hides(self):
        self.power(0)
        self.assertFalse(self.win.should_close)
        self.power(1)
        self.assertTrue(self.win.should_close)
        self.assertEqual(self.win.exit_reason, 'display-resumed')
        self.api.ShowWindow.assert_called_once_with(123, 0)
        self.api.PostMessageW.assert_called_once_with(123, self.ns['WM_CLOSE'], 0, 0)
        self.power(1)
        self.api.PostMessageW.assert_called_once()

    def test_invalid_notification_ignored(self):
        self.power(0, length=0)
        self.power(0, matching=False)
        self.power(1)
        self.assertFalse(self.win.should_close)

    def test_display_change_and_system_resume(self):
        for msg, param in ((self.ns['WM_DISPLAYCHANGE'], 0),
                           (self.ns['WM_POWERBROADCAST'], self.ns['PBT_APMRESUMEAUTOMATIC']),
                           (self.ns['WM_POWERBROADCAST'], self.ns['PBT_APMRESUMESUSPEND'])):
            self.win.should_close = False
            self.win._proc(123, msg, param, 0)
            self.assertTrue(self.win.should_close)

    def test_preview_and_windowed_are_unchanged(self):
        for fullscreen, preview in ((False, False), (True, True)):
            self.win.fullscreen, self.win.preview_mode = fullscreen, preview
            self.win.exit_on_display_off = True
            self.power(2)
            self.power(0)
            self.power(1)
            self.win._proc(123, self.ns['WM_DISPLAYCHANGE'], 0, 0)
            self.assertFalse(self.win.should_close)

    def test_notification_cleanup_is_idempotent(self):
        self.win.power_notification = 456
        self.win._unregister_power_notification()
        self.win._unregister_power_notification()
        self.api.UnregisterPowerSettingNotification.assert_called_once_with(456)

    def test_exit_hides_before_destroy_and_never_changes_display_mode(self):
        backdrop = Mock(hwnd=123)
        calls = []
        self.api.ShowWindow.side_effect = lambda *args: calls.append('hide')
        backdrop.close.side_effect = lambda: calls.append('destroy')
        self.ns['restore_windows_desktop'](backdrop)
        self.assertEqual(calls, ['hide', 'destroy'])
        self.api.ChangeDisplaySettingsExW.assert_not_called()


if __name__ == '__main__':
    unittest.main()
