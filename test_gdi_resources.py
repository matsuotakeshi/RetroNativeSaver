"""Focused compatibility checks for GDI allocation, disposal and overlay drawing."""
import ast
from test_gdi_support import drawing_classes
import ctypes
from ctypes import wintypes
from functools import cache
from pathlib import Path
import unittest

ROOT = Path(__file__).parent
OLD = (ROOT/'tests_fixtures/legacy_gdi_resources_v099.py').read_text(encoding='utf-8')
NEW = (ROOT/'native_saver.py').read_text(encoding='utf-8')
METHODS = {'_ensure_backbuffer', '_dispose_overlay_bg_resources', '_ensure_overlay_bg_resources',
           '_draw_overlay_background', '_draw_overlay_line', 'close', '_dispose_backbuffer',
           '_create_backbuffer', '_dispose_overlay_fonts', '_fill_overlay_black',
           '_blend_overlay_background', '_paint_overlay_text'}

class Blend(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ubyte) for name in ('op', 'flags', 'alpha', 'format')]

@cache
def code(source):
    return compile(ast.Module(body=drawing_classes(source, METHODS), type_ignores=[]), '<GDI resources>', 'exec')


def normalized(value):
    if hasattr(value, '_obj'):
        return normalized(value._obj)
    if isinstance(value, ctypes.Structure):
        return tuple(getattr(value, field[0]) for field in value._fields_)
    return value

class GdiResourceTests(unittest.TestCase):
    def compare(self, method, args=(), overrides=None, fail_at=None, zero=None):
        results = []
        for source in (OLD, NEW):
            events = []
            class API:
                def __getattr__(self, name):
                    def call(*values):
                        events.append((name, tuple(normalized(v) for v in values)))
                        if len(events) == fail_at:
                            raise OSError('injected GDI failure')
                        if name == zero:
                            return 0
                        if name == 'GetTextExtentPoint32W':
                            values[-1]._obj.cx = 25
                            values[-1]._obj.cy = 13
                        return {'GetDC': 101, 'CreateCompatibleDC': 102,
                                'CreateCompatibleBitmap': 103, 'SelectObject': 104,
                                'GetStockObject': 105}.get(name, 1)
                    return call
            api = API()
            ns = dict(vars(ctypes))
            ns.update(ctypes=ctypes, user32=api, gdi32=api, msimg32=api,
                      HFONT=wintypes.HANDLE, RECT=wintypes.RECT, SIZE=wintypes.SIZE,
                      BLENDFUNCTION=Blend, BLACK_BRUSH=4, AC_SRC_OVER=0, TRANSPARENT=1)
            exec(code(source), ns)
            obj = ns['GDIWindow']()
            obj.__dict__.update(hwnd=1, mem_dc=10, mem_bitmap=11, mem_old_bitmap=12,
                mem_w=100, mem_h=80, overlay_bg_dc=20, overlay_bg_bitmap=21,
                overlay_bg_old_bitmap=22, overlay_system_font=30, overlay_game_font=31,
                cursor_hidden=True)
            obj.__dict__.update(overrides or {})
            obj._unregister_power_notification = lambda: api.unregister()
            try:
                result = getattr(obj, method)(*args)
                error = None
            except Exception as exc:
                result = None
                error = (type(exc).__name__, str(exc))
            state = {k: v for k, v in vars(obj).items() if not k.startswith('_')}
            results.append((result, error, [e for e in events if e[0]!='IsWindow'], state))
        self.assertEqual(*results)
        return results[1]

    def test_successful_resize_keeps_existing_api_order(self):
        self.compare('_ensure_backbuffer',(100,80))
        result=self.compare('_ensure_backbuffer',(200,150))
        self.assertIsNone(result[1])
        self.assertEqual(result[2][-1][0],'ReleaseDC')

    def test_successful_drawing_and_close_keep_existing_behavior(self):
        self.compare('close')
        for alpha in (0,112,255):
            self.compare('_draw_overlay_background',(3,4,20,10,alpha))
            self.compare('_draw_overlay_line',('日本語タイトル',30,0,3,4,2,alpha))

if __name__=='__main__':unittest.main()
