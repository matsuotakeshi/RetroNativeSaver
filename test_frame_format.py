import ast
from pathlib import Path
import random
import unittest
import screen_layout
import frame_format
from tests_fixtures import legacy_frame_v085 as old


def outcome(fn,*args):
    try:
        result=fn(*args)
        return ('ok',result,tuple(type(v).__name__ for v in result) if isinstance(result,tuple) else type(result).__name__)
    except Exception as exc:return ('error',type(exc).__name__,str(exc))


class FrameFormatCompatibilityTests(unittest.TestCase):
    def compare(self,name,*args):
        module=screen_layout if name=='fit_inside' else frame_format
        a=outcome(getattr(old,name),*args); b=outcome(getattr(module,name),*args)
        self.assertEqual(a,b)
        return b

    def test_aspect_fallback_centering_and_invalid_values(self):
        for size in ((320,240),(256,224),(0,0),(-1,4)):
            for aspect in (None,0,-1,4/3,16/9,float('nan'),float('inf'),'bad'):
                for box in ((0,0,800,600),(-100,20,801,601),(0,0,0,0),(0,0,-1,20)):
                    self.compare('fit_inside',*size,aspect,*box)
        self.assertEqual(screen_layout.fit_inside(320,240,4/3,0,0,1920,1080),(240,0,1440,1080))

    def test_generated_aspect_cases(self):
        rng=random.Random(86)
        for _ in range(1000):
            self.compare('fit_inside',rng.randrange(1,1921),rng.randrange(1,1081),rng.choice([0,4/3,16/9,1]),
                         rng.randrange(-2000,2000),rng.randrange(-2000,2000),rng.randrange(1,2001),rng.randrange(1,2001))

    def test_row_padding_and_source_pitch(self):
        source=bytes(range(16))
        packed,stride=frame_format.pack_dib_rows(source,3,2,7,2)
        self.assertEqual((packed,stride),(source[:6]+b'\0\0'+source[7:13]+b'\0\0',8))
        # Same stride takes the fast path and preserves source padding.
        self.assertEqual(frame_format.pack_dib_rows(source,3,2,8,2),(source,8))

    def test_generated_row_layouts(self):
        rng=random.Random(860)
        for _ in range(1000):
            w=rng.randrange(1,65); h=rng.randrange(1,12); bpp=rng.choice([2,4])
            pitch=w*bpp+rng.randrange(9)
            data=rng.randbytes(pitch*h)
            self.compare('pack_dib_rows',data,w,h,pitch,bpp)

    def test_short_buffers_and_unusual_dimensions(self):
        for args in ((b'',3,2,8,2),(b'123',3,2,8,2),(b'123',3,2,7,2),
                     (b'',0,2,0,4),(b'',2,0,8,4),(b'',2,-1,7,4),(b'',-1,2,8,2),
                     (None,1,1,4,4),(b'',1,1,-1,2)):
            self.compare('pack_dib_rows',*args)

    def test_source_types_and_nonmutation(self):
        for data in (bytes(range(16)),bytearray(range(16)),memoryview(bytes(range(16)))):
            before=bytes(data)
            for pitch in (8,7):self.compare('pack_dib_rows',data,3,2,pitch,2)
            self.assertEqual(bytes(data),before)

    def test_color_conversion_and_existing_fallbacks(self):
        for value in (None,'','#ff0080',' #12AB34 ','bad','#zzzzzz','####123456',123456):
            for default in ('#B8B8B8','#010203','bad',None):self.compare('colorref_from_hex',value,default)
        self.assertEqual(frame_format.colorref_from_hex('#123456'),0x563412)
        self.assertEqual(frame_format.colorref_from_hex('bad'),0xB8B8B8)
        self.assertEqual(frame_format.colorref_from_hex('#zzzzzz'),0xD8D8D8)

    def test_native_method_wrappers_and_static_method(self):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GDIDrawingSurface')
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'_fit_inside','_pack_dib_rows','_colorref_from_hex'}]
        ns={}; exec(compile(ast.Module(body=[cls],type_ignores=[]),'<geometry wrappers>','exec'),ns)
        obj=ns['GDIDrawingSurface']()
        self.assertEqual(obj._fit_inside(320,240,4/3,0,0,1920,1080),(240,0,1440,1080))
        self.assertEqual(obj._pack_dib_rows(bytes(16),2,2,8,4),(bytes(16),8))
        self.assertEqual(ns['GDIDrawingSurface']._colorref_from_hex('#123456'),0x563412)
