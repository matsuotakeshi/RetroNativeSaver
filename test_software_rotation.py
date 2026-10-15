import ast
import contextlib
import ctypes
import io
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import libretro_abi as abi
from frame_format import rotate_frame, pack_dib_rows


class FrameRotationTests(unittest.TestCase):
    def test_direction_and_channels_with_handwritten_pixel_layout(self):
        # a b c -> c f (90 CCW), f e d (180), d a (270 CCW)
        # d e f    b e          c b a        e b
        #          a d                      f c
        for bpp in (2,4):
            pixels=[bytes([i,i+10,i+20,i+30][:bpp]) for i in range(1,7)]
            source=b''.join(pixels[:3])+b'PAD'+b''.join(pixels[3:])+b'PAD'
            for turns,order,wh in ((1,[3,6,2,5,1,4],(2,3)),(2,[6,5,4,3,2,1],(3,2)),(3,[4,1,5,2,6,3],(2,3))):
                result,w,h,pitch=rotate_frame(source,3,2,3*bpp+3,bpp,turns)
                self.assertEqual((w,h,pitch),(*wh,wh[0]*bpp))
                self.assertEqual(result,b''.join(pixels[i-1] for i in order))

    def test_random_padding_sizes_and_roundtrips(self):
        rng=random.Random(217)
        for bpp in (2,4):
            for w,h in ((1,1),(1,7),(7,1),(3,5),(20,13)):
                pitch=w*bpp+3
                raw=rng.randbytes(pitch*h)
                tight=b''.join(raw[y*pitch:y*pitch+w*bpp] for y in range(h))
                for turns in (1,2,3):
                    rotated,rw,rh,rp=rotate_frame(raw,w,h,pitch,bpp,turns)
                    restored,*layout=rotate_frame(rotated,rw,rh,rp,bpp,4-turns)
                    self.assertEqual(layout,[w,h,w*bpp]);self.assertEqual(restored,tight)
                frame,w1,h1,p1=raw,w,h,pitch
                for _ in range(4):frame,w1,h1,p1=rotate_frame(frame,w1,h1,p1,bpp,1)
                self.assertEqual(frame,tight)

    def test_zero_rotation_returns_original_bytes_and_pitch(self):
        raw=b'original padding'
        result=rotate_frame(raw,2,1,16,4,0)
        self.assertIs(result[0],raw);self.assertEqual(result[1:],(2,1,16))

    def test_truncated_rows_invalid_pitch_and_rotation_are_rejected(self):
        for args in ((b'',2,2,8,4,1),(bytes(16),2,2,7,4,1),
                     (bytes(16),2,2,8,3,1),(bytes(16),0,2,8,4,1),
                     (bytes(16),2,2,8,4,4),(bytes(16),2,2,8,4,-1)):
            with self.assertRaises(ValueError):rotate_frame(*args)

    def test_odd_sized_16bit_rotated_rows_pack_for_gdi(self):
        raw=bytes(range(16))
        rotated,w,h,pitch=rotate_frame(raw,2,3,6,2,1)  # final row needs no trailing padding
        dib,stride=pack_dib_rows(rotated,w,h,pitch,2)
        self.assertEqual((w,h,pitch,stride),(3,2,6,8))
        for y in range(h):
            self.assertEqual(dib[y*stride:y*stride+6],rotated[y*pitch:(y+1)*pitch])
            self.assertEqual(dib[y*stride+6:(y+1)*stride],b'\0\0')


class CoreRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        core=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LibretroCore')
        core.body=[n for n in core.body if getattr(n,'name','') in ('_handle_environment','_receive_video')]
        ns=dict(vars(abi),ctypes=ctypes,POINTER=ctypes.POINTER,c_bool=ctypes.c_bool,
                c_char_p=ctypes.c_char_p,decode_cstr=lambda b:b.decode() if b else '')
        exec(compile(ast.Module(body=[core],type_ignores=[]),'<actual core rotation>','exec'),ns)
        cls.core_type=ns['LibretroCore']

    def core(self,name='FinalBurn Neo',fmt=1):
        c=self.core_type()
        c.__dict__.update(system_info=SimpleNamespace(library_name=name.encode()),env_trace_frames=0,
            hw_context=None,_software_rotation=0,pixel_format=fmt,display_aspect=.75,
            frame_bytes=None,frame_w=0,frame_h=0,frame_pitch=0,frame_bottom_up=False,
            _frame_layout_logged=True)
        return c

    def request(self,core,turns):
        data=ctypes.c_uint(turns)
        with contextlib.redirect_stdout(io.StringIO()):
            return core._handle_environment(abi.RETRO_ENVIRONMENT_SET_ROTATION,ctypes.byref(data))

    def video(self,core,raw,w,h,pitch):
        buf=ctypes.create_string_buffer(raw)
        core._receive_video(ctypes.addressof(buf),w,h,pitch)

    def test_fbneo_requests_rotate_real_callback_pixels_all_formats(self):
        for fmt,bpp in ((0,2),(1,4),(2,2)):
            for turns in (1,2,3):
                c=self.core(fmt=fmt);self.assertTrue(self.request(c,turns))
                raw=bytes(range(6*bpp));self.video(c,raw,3,2,3*bpp)
                expected=rotate_frame(raw,3,2,3*bpp,bpp,turns)
                self.assertEqual((c.frame_bytes,c.frame_w,c.frame_h,c.frame_pitch),expected)
                self.assertEqual(c.display_aspect,.75);self.assertFalse(c.frame_bottom_up)

    def test_changed_request_uses_new_frame_once_zero_restores_horizontal(self):
        c=self.core();raw=bytes(range(24))
        for turns in (1,1,3,2,0):
            self.assertTrue(self.request(c,turns));self.video(c,raw,3,2,12)
            self.assertEqual(c.frame_bytes,rotate_frame(raw,3,2,12,4,turns)[0])
        self.assertEqual((c.frame_w,c.frame_h,c.frame_pitch),(3,2,12))

    def test_null_frame_keeps_last_rotated_frame_without_rotating_twice(self):
        c=self.core();self.request(c,1);self.video(c,bytes(range(24)),3,2,12)
        before=(c.frame_bytes,c.frame_w,c.frame_h,c.frame_pitch)
        c._receive_video(None,3,2,12)
        self.assertEqual((c.frame_bytes,c.frame_w,c.frame_h,c.frame_pitch),before)

    def test_missing_or_invalid_request_preserves_previous_rotation(self):
        c=self.core();self.request(c,1)
        self.assertFalse(c._handle_environment(abi.RETRO_ENVIRONMENT_SET_ROTATION,None))
        self.assertFalse(self.request(c,4));self.assertFalse(self.request(c,0xFFFFFFFF))
        self.assertEqual(c._software_rotation,1)

    def test_other_cores_and_wonderswan_keep_existing_rotation_policy(self):
        raw=bytes(range(24))
        for name,accepted in (('MAME',True),('Flycast',True),('Beetle WonderSwan',False)):
            c=self.core(name);self.assertEqual(self.request(c,1),accepted)
            self.video(c,raw,3,2,12)
            self.assertEqual((c.frame_bytes,c.frame_w,c.frame_h),(raw,3,2))
            self.assertEqual(c._software_rotation,0)

    def test_horizontal_does_not_call_rotator_and_hw_frame_stays_deferred(self):
        c=self.core()
        with patch('frame_format.rotate_frame',side_effect=AssertionError('unexpected work')):
            self.video(c,bytes(range(24)),3,2,12)
        self.request(c,1);c.hw_context=object()
        before=c.frame_bytes
        with patch('frame_format.rotate_frame',side_effect=AssertionError('HW callback')):
            c._receive_video(abi.RETRO_HW_FRAME_BUFFER_VALID,640,480,0)
        self.assertEqual(c._pending_hw_frame,(640,480));self.assertIs(c.frame_bytes,before)


if __name__=='__main__':unittest.main()
