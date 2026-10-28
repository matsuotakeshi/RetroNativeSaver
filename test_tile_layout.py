"""Geometry, persisted live changes and real shared-memory consistency checks."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import tile_layout as layout
from settings_store import SettingsDocument, FIELDS

MONITORS = [(0, 0, 1920, 1080), (1920, 0, 4480, 1080)]


class GridTests(unittest.TestCase):
    def test_known_grids_one_tile_and_four_rows(self):
        self.assertEqual(layout.grids(MONITORS, 1), [(1, 1), (1, 1)])
        self.assertEqual(layout.grids(MONITORS, 2), [(4, 2), (5, 2)])
        rows, rects, grids = layout.plan(MONITORS, (0, 0), 4)
        self.assertEqual((rows, grids, len(rects)), (4, [(7, 4), (9, 4)], 64))
        self.assertEqual(rects[0], (0, 0, 274, 270))
        self.assertEqual(rects[28], (1920, 0, 284, 270))
        self.assertEqual(layout.initial_rows(MONITORS, (0, 0), rects), 4)

    def test_physical_size_resolution_portrait_and_capacity(self):
        for monitors in (MONITORS, [(0, 0, 3840, 2160)], [(-1080, -300, 0, 1620)],
                         [(0, 0, 1280, 720), (1280, 0, 3200, 1080)], [(0, 0, 100, 100)]):
            origin = monitors[0][:2]
            for limit in (32, 64):
                previous = 0
                for desired in range(1, 65):
                    rows, rects, grids = layout.plan(monitors, origin, desired, limit=limit)
                    self.assertLessEqual(len(rects), limit)
                    self.assertGreaterEqual(len(rects), previous)
                    previous = len(rects)
                    offset = 0
                    for (left, top, right, bottom), (cols, count) in zip(monitors, grids):
                        cells = rects[offset:offset+cols*count]
                        offset += cols*count
                        self.assertEqual(sum(w*h for _, _, w, h in cells), (right-left)*(bottom-top))
                        self.assertTrue(all(h >= min(270, bottom-top) for _, _, w, h in cells))
                        self.assertEqual(cells[0][:2], (left-origin[0], top-origin[1]))
        self.assertEqual(layout.plan(MONITORS, (0, 0), 4, limit=32)[2], [(4, 2), (5, 2)])
        self.assertEqual(layout.plan([(0, 0, 3840, 2160)], (0, 0), 8)[2], [(9, 5)])

    def test_invalid_and_legacy_values(self):
        for v in (None, True, -1, 65, '4', 3.5, {}, float('inf')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(layout.configured_rows({'tile_rows': v}), 0)
        self.assertEqual(layout.configured_rows({}), 0)
        for monitors in ([], [(0, 0, 10, 0)], MONITORS*33):
            with self.assertRaises(ValueError):
                layout.plan(monitors, (0, 0), 4)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'config.json'
        self.write({'unknown': {'keep': ['日本語']}, 'tile_rows': 2})

    def write(self, value):
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def controller(self, rows=2):
        self.now = 10.
        cfg = {'tile_rows': rows}
        return layout.Controller(cfg, self.path, MONITORS, (0, 0),
                                 layout.plan(MONITORS, (0, 0), rows)[1], clock=lambda: self.now)

    def test_merge_latest_backup_and_no_redundant_save(self):
        before = self.path.read_bytes()
        layout.save_rows(self.path, 3)
        self.assertEqual(self.read(), {'unknown': {'keep': ['日本語']}, 'tile_rows': 3})
        self.assertEqual([p.read_bytes() for p in self.path.parent.glob('*.bak-*')], [before])
        layout.save_rows(self.path, 3)
        self.assertEqual(len(list(self.path.parent.glob('*.bak-*'))), 1)
        current = self.read(); current['external'] = 'preserve'; self.write(current)
        layout.save_rows(self.path, 4)
        self.assertEqual(self.read()['external'], 'preserve')

    def test_malformed_missing_and_atomic_write_failure(self):
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            layout.save_rows(self.path, 3)
        self.assertEqual(self.path.read_text(), '{broken')
        self.path.unlink()
        with self.assertRaises(OSError):
            layout.save_rows(self.path, 3)
        self.write({'tile_rows': 2})
        with patch('file_transaction.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                layout.save_rows(self.path, 3)
        self.assertEqual(self.read()['tile_rows'], 2)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_recycle_reload_only_mutable_field(self):
        frozen = {'tile_rows': 4, 'cycle_seconds': 150, '_single_system_session': ['gb']}
        self.write({'tile_rows': 1, 'cycle_seconds': 999})
        updated = layout.refresh_saved_rows(frozen, self.path)
        self.assertEqual(updated, dict(frozen, tile_rows=1))
        self.assertEqual(frozen['tile_rows'], 4)

    def test_page_keys_coalesce_saves_and_reverse_at_bounds(self):
        c = self.controller()
        self.assertIsNone(c.take(100))
        c.step(1)
        self.assertIsNone(c.take(10.1))
        c.step(1)
        result = c.take(10.3)
        self.assertEqual(len(result), 64)
        self.assertEqual(self.read()['tile_rows'], 4)
        self.assertIsNone(c.take(100))
        c.step(1)
        self.assertIsNone(c.take(100))
        c.step(-3)
        self.assertEqual(len(c.take(100)), 2)
        self.assertEqual(self.read()['tile_rows'], 1)
        c.step(-1)
        self.assertIsNone(c.take(100))

    def test_failed_save_keeps_display_and_retries_only_on_new_input(self):
        c = self.controller(); c.step(1)
        with patch.object(layout, 'save_rows', side_effect=PermissionError('readonly')), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(c.take(100))
        self.assertEqual((c.rows, c.pending), (2, 2))
        self.assertIsNone(c.take(200))
        c.step(-1)
        self.assertEqual(len(c.take(200)), 2)

    def test_stale_open_dialog_cannot_overwrite_live_edit(self):
        document = SettingsDocument(self.path)
        layout.save_rows(self.path, 3)
        with self.assertRaises(ValueError):
            document.save({('cycle_seconds',): 200})
        self.assertEqual(self.read()['tile_rows'], 3)

    def test_field_validation(self):
        for value in ('-1', '65', 'NaN', True, '2.5'):
            with self.assertRaises(ValueError):
                FIELDS[('tile_rows',)].parse(value)
        self.assertEqual(FIELDS[('tile_rows',)].parse('4'), 4)


class LiveTests(unittest.TestCase):
    def test_actual_window_proc_consumes_page_keys_but_retains_exit_paths(self):
        source = ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'GDIWindow')
        proc = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_proc')
        constants = [n for n in source.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id.startswith('WM_') for t in n.targets)]
        user = Mock()
        ns = {'user32': user}
        exec(compile(ast.Module(body=constants+[proc], type_ignores=[]), '<actual window procedure>', 'exec'), ns)
        for disabled, idle, preview in ((False, False, False), (True, False, False),
                                       (False, True, False), (False, False, True)):
            control = Mock()
            win = SimpleNamespace(fullscreen=True, preview_mode=preview, should_close=False,
                                  power_idle=idle, tile_layout=None if disabled else control,
                                  _note_exit=Mock())
            ns['_proc'](win, 10, 0x0100, layout.PAGE_UP, 0)
            if not (disabled or idle or preview):
                control.step.assert_called_once_with(1)
                self.assertFalse(win.should_close)
                ns['_proc'](win, 10, 0x0100, layout.PAGE_UP, 1 << 30)
                control.step.assert_called_once_with(1)  # Ignore held-key auto-repeat.
                ns['_proc'](win, 10, 0x0100, layout.PAGE_DOWN, 0)
                control.step.assert_called_with(-1)
                self.assertFalse(win.should_close)
                ns['_proc'](win, 10, 0x020A, 120 << 16, 0)  # Mouse wheel exits again.
                self.assertTrue(win.should_close)
            else:
                control.step.assert_not_called()
                self.assertEqual(win.should_close, not preview)

    @unittest.skipUnless(os.name == 'nt', 'Windows window geometry')
    def test_real_hidden_child_resize(self):
        import ctypes as C
        from ctypes import wintypes as W
        user = C.WinDLL('user32', use_last_error=True)
        user.CreateWindowExW.argtypes = [W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,
                                        C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
        user.CreateWindowExW.restype = W.HWND
        user.DestroyWindow.argtypes = [W.HWND]; user.DestroyWindow.restype = W.BOOL
        user.GetClientRect.argtypes = [W.HWND,C.POINTER(W.RECT)]; user.GetClientRect.restype = W.BOOL
        parent = user.CreateWindowExW(0,'STATIC','layout test',0x80000000,0,0,100,100,None,None,None,None)
        self.assertTrue(parent)
        self.addCleanup(user.DestroyWindow,parent)
        child = user.CreateWindowExW(0,'STATIC','layout child',0x40000000,0,0,10,10,parent,None,None,None)
        self.assertTrue(child)
        self.addCleanup(user.DestroyWindow,child)
        owner = layout.Geometry(); self.addCleanup(owner.close)
        reader = layout.Geometry(owner.tag); self.addCleanup(reader.close)
        owner.publish([(3,4,37,59)])
        win = SimpleNamespace(hwnd=child, embedded_rect=(0,0,10,10))
        layout.resize_tile(SimpleNamespace(user32=user),win,reader,0)
        rect = W.RECT()
        self.assertTrue(user.GetClientRect(child,C.byref(rect)))
        self.assertEqual((rect.right,rect.bottom),(37,59))

    def test_page_key_forwarding_repeat_and_unrelated_input(self):
        ui = Mock(); forwarded = layout.RowKeyForward(ui, lambda: 88)
        for key in (layout.PAGE_UP, layout.PAGE_DOWN):
            self.assertTrue(layout.handle_keys(forwarded, 0x0100, key))
            ui.PostMessageW.assert_called_with(88, layout.ROW_KEY_MESSAGE, key, 0)
        calls = ui.PostMessageW.call_count
        self.assertTrue(layout.handle_keys(forwarded, 0x0100, layout.PAGE_UP, 1 << 30))
        self.assertEqual(ui.PostMessageW.call_count, calls)
        receiver = Mock()
        layout.handle_keys(receiver, layout.ROW_KEY_MESSAGE, layout.PAGE_DOWN)
        receiver.step.assert_called_once_with(-1)
        self.assertFalse(layout.handle_keys(None, 0x0100, layout.PAGE_UP))
        for msg, key in ((0x020A, 120 << 16), (0x0100, 0x26), (0x0100, 0x28),
                         (0x0100, 0x1b), (0x0101, layout.PAGE_UP), (0x0104, layout.PAGE_UP)):
            self.assertFalse(layout.handle_keys(receiver, msg, key))

    def test_legacy_toggle_never_binds_mouse_wheel(self):
        from settings_store import display_values
        for cfg, enabled in (({}, True), ({'tile_wheel_enabled': False}, False),
                             ({'tile_wheel_enabled': True}, True),
                             ({'tile_wheel_enabled': False, 'tile_resize_keys_enabled': True}, True),
                             ({'tile_resize_keys_enabled': False}, False)):
            self.assertEqual(layout.resize_keys_enabled(cfg), enabled)
            self.assertEqual(display_values(cfg)[('tile_resize_keys_enabled',)], enabled)
            self.assertFalse(layout.handle_keys(Mock() if enabled else None, 0x020A, 120 << 16))

    @unittest.skipUnless(os.name == 'nt', 'Windows named shared memory')
    def test_geometry_shared_reader_consistent_and_readonly(self):
        owner = layout.Geometry(); self.addCleanup(owner.close)
        owner.publish([(0, 0, 1920, 1080), (1920, 0, 2560, 1080)])
        reader = layout.Geometry(owner.tag); self.addCleanup(reader.close)
        self.assertEqual(reader.rectangle(1), (1920, 0, 2560, 1080))
        self.assertIsNone(reader.rectangle(2))
        owner.publish([(0, 0, 10, 20)])
        self.assertEqual(reader.rectangle(0), (0, 0, 10, 20))
        self.assertIsNone(reader.rectangle(1))
        struct.pack_into('<I', owner.shared, 0, 9)  # Interrupted write is never accepted.
        self.assertIsNone(reader.rectangle(0))
        with self.assertRaises(ValueError):
            reader.publish([(0, 0, 1, 1)])

    def test_resize_retains_survivors_and_waits_before_dropping_ownership(self):
        a, b, c = object(), object(), object()
        slots, retry, rects = [a, b, c], [1, 2, 3], [(0, 0, 1, 1)]*3
        calls = []
        def dispose(index):
            calls.append(slots[index]); slots[index] = None
        layout.resize_slots(slots, retry, rects, [(0, 0, 2, 2)], dispose, 10)
        self.assertEqual(calls, [c, b])
        self.assertEqual(slots, [a]); self.assertEqual(retry, [1])
        layout.resize_slots(slots, retry, rects, [(0, 0, 1, 1)]*3, dispose, 20)
        self.assertEqual(slots, [a, None, None]); self.assertEqual(retry, [1, 20, 20])
        slots[:] = [a, b, c]
        with self.assertRaises(TimeoutError):
            layout.resize_slots(slots, retry, rects, [(0, 0, 2, 2)], Mock(side_effect=TimeoutError()), 30)
        self.assertEqual(slots, [a, b, c])
        self.assertEqual(len(rects), 3)

    def test_child_resize_uses_no_activation_and_checks_api_failure(self):
        api = SimpleNamespace(user32=SimpleNamespace(SetWindowPos=Mock(return_value=1)))
        win = SimpleNamespace(hwnd=10, embedded_rect=(0, 0, 1, 1))
        shared = SimpleNamespace(rectangle=lambda i: (5, 6, 100, 200))
        layout.resize_tile(api, win, shared, 0)
        api.user32.SetWindowPos.assert_called_once_with(10, None, 5, 6, 100, 200, 0x14)
        layout.resize_tile(api, win, shared, 0)
        self.assertEqual(api.user32.SetWindowPos.call_count, 1)
        win.embedded_rect = (0, 0, 1, 1)
        api.user32.SetWindowPos.return_value = 0
        with self.assertRaises(OSError):
            layout.resize_tile(api, win, shared, 0)
        self.assertEqual(win.embedded_rect, (0, 0, 1, 1))


if __name__ == '__main__':
    unittest.main()
