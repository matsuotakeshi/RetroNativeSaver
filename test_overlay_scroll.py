"""Scroll timing, title changes, clipping and GDI failure recovery."""
import unittest
from unittest.mock import Mock, patch
from ctypes.wintypes import RECT
from types import SimpleNamespace

import overlay_scroll as scroll
import test_gdi_drawing as drawing
from gdi_safety import GDIError


class ScrollTimingTests(unittest.TestCase):
    def test_initial_pause_then_time_based_leftward_motion(self):
        self.assertEqual(scroll.positions(400, 200, 0), (0,))
        self.assertEqual(scroll.positions(400, 200, 2), (0,))
        self.assertEqual(scroll.positions(400, 200, 2.5), (-12,))

    def test_next_copy_enters_from_right_and_pauses_at_left(self):
        self.assertEqual(scroll.positions(400, 200, 2 + 300 / 24), (-300, 148))
        self.assertEqual(scroll.positions(400, 200, 2 + 448 / 24), (0,))

    def test_short_labels_also_scroll_without_tiling_repeated_copies(self):
        self.assertEqual(scroll.positions(40, 300, 0), (0,))
        self.assertEqual(scroll.positions(40, 300, 2.5), (-12,))
        self.assertEqual(scroll.positions(40, 300, 2 + 100 / 24), (248,))

    def test_zero_speed_stays_still_and_empty_area_has_no_text(self):
        self.assertEqual(scroll.positions(400, 200, 100, speed=0), (0,))
        self.assertEqual(scroll.positions(0, 200, 1), ())
        self.assertEqual(scroll.positions(100, 0, 1), ())
        self.assertEqual(scroll.positions(100, 200, -1), (0,))

    def test_invalid_scroll_options_fall_back_and_values_are_bounded(self):
        for value in (None, 'bad', float('nan'), float('inf')):
            self.assertEqual(scroll.number(value, 24, 200), 24)
        self.assertEqual(scroll.number(-1, 24, 200), 0)
        self.assertEqual(scroll.number(1000, 24, 200), 200)


class ScrollDrawingTests(unittest.TestCase):
    def setUp(self):
        cls, self.events = drawing.DrawingBoundaryTests().make()
        self.obj = cls()
        self.obj.hwnd = 13
        self.obj.begin_composite()
        self.events.clear()
        self.api = cls.draw_overlay.__globals__['gdi32']

    def tearDown(self):
        self.obj.close()

    def draw(self, at=100, system='Sharp X68000 (PX68k)', game='日本語ゲーム', x=10, **cfg):
        with patch.object(scroll.time, 'monotonic', return_value=at):
            self.obj.draw_overlay(system, game, x, 20, 320, 240, cfg)

    def calls(self, name):
        return [args for event, args in self.events if event == name]

    def test_default_is_joined_and_uses_system_font_at_top_left(self):
        self.draw(system_font_size=12, game_font_size=30)
        text = self.calls('TextOutW')
        self.assertEqual([args[3] for args in text], ['Sharp X68000 / ', '日本語ゲーム'])
        self.assertEqual(text[0][1:3], (20, 30))
        self.assertEqual(text[1][1:3], (60, 30))
        fonts = self.calls('CreateFontW')
        self.assertEqual(len(fonts), 1)
        self.assertEqual(fonts[0][0], -12)
        self.assertEqual(fonts[0][-1], 'Segoe UI')
        self.assertIsNone(self.obj.overlay_game_font)
        self.assertEqual(self.calls('IntersectClipRect')[0][1:], (16, 26, 324, 46))
        self.assertEqual(self.calls('IntersectClipRect')[1][1:], (20, 30, 320, 42))
        self.assertEqual(self.events[-1][0], 'RestoreDC')

    def test_measurements_are_cached_and_motion_uses_elapsed_time(self):
        self.draw()
        self.events.clear()
        self.draw(at=102.5)
        self.assertEqual(self.calls('GetTextExtentPoint32W'), [])
        self.assertEqual(self.calls('CreateFontW'), [])
        self.assertEqual(self.calls('TextOutW')[0][1], 8)

    def test_changed_title_restarts_at_left_without_growing_cache(self):
        self.draw()
        self.draw(at=105)
        self.events.clear()
        self.draw(at=106, game='次のゲーム')
        self.assertEqual(self.calls('TextOutW')[0][1], 20)
        self.assertEqual(len(self.calls('GetTextExtentPoint32W')), 2)
        self.assertEqual(len(self.obj._overlay_scroll_states), 1)

    def test_tiles_keep_separate_start_times(self):
        self.draw()
        self.draw(at=103, x=400)
        self.events.clear()
        self.draw(at=103)
        self.assertEqual(self.calls('TextOutW')[0][1], -4)
        self.events.clear()
        self.draw(at=103, x=400)
        self.assertEqual(self.calls('TextOutW')[0][1], 410)
        self.assertEqual(len(self.obj._overlay_scroll_states), 2)

    def test_disabled_or_too_small_overlay_does_not_allocate(self):
        self.draw(enabled=False)
        self.draw(margin=200)
        self.assertEqual(self.events, [])

    def test_single_label_has_no_separator_and_utf16_length_is_used(self):
        self.draw(system='', game='ゲーム🎮')
        self.assertEqual(self.calls('TextOutW')[0][3:], ('ゲーム🎮', 5))
        self.assertEqual(self.calls('GetTextExtentPoint32W')[0][2], 5)

    def test_font_clip_and_color_state_are_restored_on_api_failures(self):
        for call in ('GetTextExtentPoint32W', 'IntersectClipRect', 'TextOutW'):
            self.obj._overlay_scroll_states = {}
            self.events.clear()
            with self.subTest(call=call), patch.object(self.api, call, return_value=0, create=True):
                with self.assertRaises(GDIError):
                    self.draw()
            self.assertEqual(self.events[-1][0], 'RestoreDC')

    def test_failed_save_prevents_drawing_and_failed_restore_is_reported(self):
        with patch.object(self.api, 'SaveDC', return_value=0, create=True):
            with self.assertRaises(GDIError):
                self.draw()
        self.assertEqual(self.calls('TextOutW'), [])
        with patch.object(self.api, 'RestoreDC', return_value=0, create=True):
            with self.assertRaisesRegex(GDIError, 'RestoreDC'):
                self.draw()

    def test_legacy_two_line_mode_remains_available(self):
        self.draw(scroll_enabled=False)
        self.assertEqual([args[3] for args in self.calls('TextOutW')],
                         ['Sharp X68000', '日本語ゲーム'])
        self.assertNotEqual(self.calls('TextOutW')[0][2], self.calls('TextOutW')[1][2])
        self.assertEqual(self.calls('SaveDC'), [])

    def test_selection_help_keeps_static_two_line_display(self):
        import saver_controls as controls
        tile = controls.TileControls.__new__(controls.TileControls)
        tile.index = 0
        tile.shared = controls.STATE.pack(1, 0, controls.NORMAL, 200, 1)
        gdi = SimpleNamespace(GetStockObject=Mock(return_value=1), SetDCBrushColor=Mock(return_value=1))
        api = SimpleNamespace(gdi32=gdi, user32=SimpleNamespace(FillRect=Mock(return_value=1)), RECT=RECT)
        win = SimpleNamespace(mem_dc=1, client_size=lambda: (320, 240), draw_overlay=Mock())
        with patch.object(controls.time, 'monotonic', return_value=100):
            tile.draw(api, win)
        args = win.draw_overlay.call_args.args
        self.assertIn('Enter', args[0])
        self.assertIn('Del', args[1])
        self.assertFalse(args[-1]['scroll_enabled'])


if __name__ == '__main__':
    unittest.main()
