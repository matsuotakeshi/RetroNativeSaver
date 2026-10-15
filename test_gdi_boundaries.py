import ast
from test_gdi_support import drawing_classes
import contextlib
import copy
import ctypes
import io
from pathlib import Path
import random
import unittest
from functools import cache

ROOT=Path(__file__).parent
OLD=(ROOT/'tests_fixtures/legacy_gdi_v095.py').read_text(encoding='utf-8')
NEW=(ROOT/'native_saver.py').read_text(encoding='utf-8')
CHANGED={'draw_frame_to_rect','_ensure_overlay_fonts'}
ADDED={'_make_bitmap_info','_create_overlay_font'}
def gdi(source):return next(n for n in ast.parse(source).body if getattr(n,'name','')=='GDIWindow')

@cache
def drawing_code(source):
    tree=ast.parse(source)
    keep=CHANGED|ADDED|{'_fit_inside','_pack_dib_rows'}
    names={'BITMAPINFOHEADER','RGBQUAD','BITMAPINFO','BITMAPINFO_MASKS'}
    structures=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names]
    return compile(ast.Module(body=structures+drawing_classes(source, keep),type_ignores=[]),'<gdi>','exec')

def build(source,api):
    ns=dict(vars(ctypes));ns.update(ctypes=ctypes,gdi32=api,HALFTONE=4,RETRO_PIXEL_FORMAT_XRGB8888=1,RETRO_PIXEL_FORMAT_RGB565=2,BI_RGB=0,BI_BITFIELDS=3,DIB_RGB_COLORS=0,SRCCOPY=0x00CC0020,
      FW_NORMAL=400,DEFAULT_CHARSET=1,OUT_DEFAULT_PRECIS=0,CLIP_DEFAULT_PRECIS=0,DEFAULT_QUALITY=0,DEFAULT_PITCH=0,FF_DONTCARE=0)
    exec(drawing_code(source),ns)
    return ns['GDIWindow']

class GdiBoundaryTests(unittest.TestCase):

    def draw(self,args,hwnd=1,fail=None):
        results=[]
        for source in (OLD,NEW):
            events=[]
            class Api:
                def SetStretchBltMode(self,*values):
                    events.append(('mode',values))
                    if fail=='mode':raise OSError('mode failure')
                    return 1
                def StretchDIBits(self,*values):
                    buf,bmi=values[9],values[10]._obj
                    events.append(('draw',values[:9],buf.raw,bytes(bmi),values[11:]))
                    if fail=='draw':raise OSError('draw failure')
                    return 1
            cls=build(source,Api());obj=cls();obj.hwnd=hwnd;obj.mem_dc=17
            try:value=obj.draw_frame_to_rect(*args);error=None
            except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
            results.append((value,error,events))
        self.assertEqual(*results);return results[1]

    def test_image_formats_orientation_padding_and_aspect(self):
        rng=random.Random(96)
        for i in range(300):
            width,height=rng.randint(1,30),rng.randint(1,20);fmt=rng.choice([0,1,2,999]);pitch=width*(4 if fmt==1 else 2)+rng.randint(0,5)
            frame=rng.randbytes(pitch*height)
            args=(frame,width,height,pitch,fmt,rng.choice([0,4/3,16/9]),rng.randint(-10,10),rng.randint(-10,10),rng.randint(1,600),rng.randint(1,400),bool(i%2))
            result=self.draw(args);self.assertIsNone(result[1]);self.assertEqual([e[0] for e in result[2]],['mode','draw'])

    def test_empty_and_missing_window(self):
        args=(b'data',1,1,4,1,0,0,0,10,10,False)
        self.assertEqual(self.draw(args,hwnd=None)[2],[])
        self.assertEqual(self.draw((b'',)+args[1:])[2],[])

    def test_draw_failures_and_invalid_dimensions(self):
        args=(b'1234',1,1,4,1,0,0,0,10,10,False)
        for failure in ('mode','draw'):
            r=self.draw(args,fail=failure);self.assertEqual(r[1][0],'OSError')
        for width,height,pitch in ((0,0,0),(-1,1,4),(1,-1,4),(1,1,-1)):
            self.draw((b'1234',width,height,pitch,2,0,0,0,10,10,False))

    def fonts(self,system_px,game_px,initial=(None,None),responses=(101,102),fail_at=None):
        results=[]
        for source in (OLD,NEW):
            events=[];queue=list(responses)
            class Api:
                def CreateFontW(self,*args):
                    events.append(args)
                    if len(events)==fail_at:raise OSError('font failure')
                    return queue.pop(0) if queue else 103
            cls=build(source,Api());obj=cls();obj.overlay_system_font,obj.overlay_game_font=initial
            try:value=obj._ensure_overlay_fonts(system_px,game_px);error=None
            except Exception as exc:value=None;error=(type(exc).__name__,str(exc))
            results.append((value,error,events,obj.overlay_system_font,obj.overlay_game_font))
        self.assertEqual(*results);return results[1]

    def test_font_sizes_and_cached_handles(self):
        for first in (-10,0,8,12,'16'):
            for second in (-1,9,20,'24'):
                for initial in ((None,None),(11,None),(None,12),(11,12)):
                    result=self.fonts(first,second,initial);self.assertIsNone(result[1])
        result=self.fonts(0,0);self.assertEqual([e[0] for e in result[2]],[-8,-9])

    def test_font_creation_failure_and_partial_state(self):
        for failure in (1,2):self.fonts(12,16,fail_at=failure)
        self.fonts('bad',16);result=self.fonts(12,'bad');self.assertEqual(result[3],101);self.assertIsNone(result[4])

if __name__=='__main__':unittest.main()
