"""Exercise the real GDI inheritance boundary using simulated Win32 calls."""
import ast
import ctypes
from ctypes import wintypes
from pathlib import Path
import unittest
import libretro_abi as abi

SOURCE=Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
STRUCTURES={'RECT','POINT','SIZE','BITMAPINFOHEADER','RGBQUAD','BITMAPINFO','BITMAPINFO_MASKS','BLENDFUNCTION'}
CONSTANTS={'WM_DISPLAYCHANGE', 'PBT_APMRESUMEAUTOMATIC', 'WM_MOUSEWHEEL', 'WS_CHILD', 'SM_CYVIRTUALSCREEN', 'DEFAULT_QUALITY', 'OUT_DEFAULT_PRECIS', 'BLACK_BRUSH', 'SM_YVIRTUALSCREEN', 'WM_ERASEBKGND', 'CS_VREDRAW', 'SM_CXSCREEN', 'SM_CXVIRTUALSCREEN', 'WM_MOUSEMOVE', 'PBT_APMRESUMESUSPEND', 'FF_DONTCARE', 'SRCCOPY', 'WM_MBUTTONDOWN', 'IDC_ARROW', 'SM_CYSCREEN', 'CLIP_DEFAULT_PRECIS', 'CS_HREDRAW', 'CW_USEDEFAULT', 'PBT_POWERSETTINGCHANGE', 'WS_OVERLAPPEDWINDOW', 'WS_POPUP', 'FW_NORMAL', 'WM_POWERBROADCAST', 'BI_BITFIELDS', 'WM_SYSKEYDOWN', 'TRANSPARENT', 'SW_HIDE', 'HALFTONE', 'SM_XVIRTUALSCREEN', 'WM_LBUTTONDOWN', 'AC_SRC_OVER', 'WM_DESTROY', 'WS_VISIBLE', 'WM_CLOSE', 'WM_KEYDOWN', 'WM_PAINT', 'SW_SHOW', 'WS_EX_TOPMOST', 'DEFAULT_PITCH', 'DEFAULT_CHARSET', 'AC_SRC_ALPHA', 'DIB_RGB_COLORS', 'BI_RGB', 'WM_RBUTTONDOWN', 'PM_REMOVE'}
NODES=[n for n in TREE.body if (isinstance(n,ast.ClassDef) and n.name in STRUCTURES|{'GDIDrawingSurface','GDIWindow'}) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in CONSTANTS for t in n.targets))]
CODE=compile(ast.Module(body=NODES,type_ignores=[]),'<drawing boundary>','exec')

class DrawingBoundaryTests(unittest.TestCase):
    def make(self):
        events=[];counter=[100]
        class API:
            def __getattr__(self,name):
                def call(*args):
                    events.append((name,args))
                    if name=='GetClientRect':args[1]._obj.right=320;args[1]._obj.bottom=240
                    if name=='GetTextExtentPoint32W':args[-1]._obj.cx=40;args[-1]._obj.cy=12
                    if name.startswith('Create') or name in ('GetDC','SelectObject'):
                        counter[0]+=1;return counter[0]
                    return 1
                return call
        api=API();ns=dict(vars(ctypes));ns.update(vars(wintypes));ns.update(vars(abi))
        ns.update(ctypes=ctypes,user32=api,gdi32=api,msimg32=api,WNDPROC=lambda fn:ctypes.c_void_p(99))
        exec(CODE,ns)
        return ns['GDIWindow'],events

    def test_instances_keep_independent_drawing_and_window_state(self):
        cls,events=self.make();a,b=cls(),cls()
        a.hwnd=13;a.begin_composite()
        self.assertIsNotNone(a.mem_dc);self.assertIsNone(b.mem_dc)
        self.assertFalse(a.should_close);self.assertFalse(b.should_close)
        self.assertIn('mem_dc',vars(a));self.assertNotIn('mem_dc',vars(cls))
        a.close();self.assertIsNone(a.hwnd);self.assertIsNone(a.mem_dc)
        self.assertIsNone(b.hwnd);self.assertIsNone(b.mem_bitmap)

    def test_draw_present_resize_and_close_preserve_lifetime(self):
        cls,events=self.make();obj=cls();obj.hwnd=13
        obj.begin_composite();first=obj.mem_dc
        obj.draw_frame_to_rect(bytes(16),2,2,8,1,1.0,0,0,320,240)
        obj.draw_overlay('System','Game',0,0,320,240,dict(scroll_enabled=False))
        obj.draw_fade_black(100);obj.present()
        names=[e[0] for e in events]
        self.assertIn('StretchDIBits',names);self.assertEqual(names.count('TextOutW'),2)
        self.assertIn('AlphaBlend',names);self.assertIn('BitBlt',names)
        events.clear();obj.begin_composite()
        self.assertEqual(obj.mem_dc,first)
        self.assertNotIn('CreateCompatibleDC',[e[0] for e in events])
        obj._ensure_backbuffer(640,480);self.assertNotEqual(obj.mem_dc,first)
        obj.close();self.assertIsNone(obj.mem_dc);self.assertIsNone(obj.mem_bitmap)
        self.assertIsNone(obj.overlay_bg_dc);self.assertIsNone(obj.overlay_system_font)
        self.assertIsNone(obj.overlay_game_font);self.assertIsNone(obj.hwnd)
        events.clear();obj.close();self.assertEqual(events,[])

    def test_hidden_window_drawing_short_circuits(self):
        cls,events=self.make();obj=cls()
        obj.begin_composite();obj.draw_frame_to_rect(bytes(16),2,2,8,1,1,0,0,20,20)
        obj.draw_fade_black(100);obj.present()
        self.assertEqual(events,[])

    def test_overlay_pair_has_only_configured_gap_and_nonoverlapping_backgrounds(self):
        for padding in (0, 4, 24):
            for gap in (0, 3):
                with self.subTest(padding=padding, gap=gap):
                    cls, events = self.make(); obj = cls(); obj.hwnd = 13
                    obj.begin_composite()
                    obj.draw_overlay('Sharp X68000 (PX68k)', '日本語タイトル', 10, 20, 320, 240,
                                     dict(padding=padding, line_gap=gap, scroll_enabled=False))
                    text = [args for name, args in events if name == 'TextOutW']
                    self.assertEqual([args[3] for args in text], ['Sharp X68000', '日本語タイトル'])
                    self.assertEqual(text[0][1:3], (16 + padding, 26 + padding))
                    self.assertEqual(text[1][1], text[0][1])
                    self.assertEqual(text[1][2] - (text[0][2] + 12), gap)
                    backgrounds = [args for name, args in events if name == 'AlphaBlend']
                    self.assertEqual(len(backgrounds), 2)
                    first, second = backgrounds
                    self.assertEqual(second[2] - (first[2] + first[4]), gap)
                    self.assertEqual(first[2] + padding, text[0][2])
                    self.assertEqual(second[2] + second[4], text[1][2] + 12 + padding)
                    obj.close()

    def test_single_overlay_line_keeps_outer_padding(self):
        for system, game in (('System', ''), ('', 'Game')):
            cls, events = self.make(); obj = cls(); obj.hwnd = 13
            obj.begin_composite(); obj.draw_overlay(system, game, 0, 0, 320, 240, dict(scroll_enabled=False))
            text = [args for name, args in events if name == 'TextOutW']
            self.assertEqual(len(text), 1)
            self.assertEqual(text[0][1:3], (10, 10))
            background = next(args for name, args in events if name == 'AlphaBlend')
            self.assertEqual(background[2], 6)
            self.assertEqual(background[4], 20)
            obj.close()

    def test_disabled_overlay_does_not_allocate_or_draw(self):
        cls, events = self.make(); obj = cls()
        obj.draw_overlay('System', 'Game', 0, 0, 320, 240, dict(enabled=False))
        self.assertEqual(events, [])

    def test_pixel_scaling_is_opt_in_per_window_and_normal_stays_halftone(self):
        cls,events=self.make();normal,dense=cls(),cls()
        dense.stretch_blt_mode=3  # Win32 COLORONCOLOR
        for obj,expected in ((normal,4),(dense,3),(normal,4)):
            obj.hwnd=13;obj.begin_composite();events.clear()
            obj.draw_frame_to_rect(bytes(16),2,2,8,1,1.0,0,0,320,240)
            self.assertEqual([args[1] for name,args in events if name=='SetStretchBltMode'],[expected])
        normal.close();dense.close()

if __name__=='__main__':unittest.main()
