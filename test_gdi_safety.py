"""Resource-model regressions for allocation rollback and unsuccessful release."""
import ctypes
from types import SimpleNamespace
import unittest
import gdi_safety as safe
from test_gdi_drawing import CODE
from ctypes import wintypes
import libretro_abi as abi

class Model:
    def __init__(self):
        self.next=100;self.live={};self.selected={};self.screen=set();self.events=[];self.fail={};self.calls={}
    def __getattr__(self,name):
        def call(*args):
            self.events.append(name);self.calls[name]=self.calls.get(name,0)+1
            fault=self.fail.get((name,self.calls[name]),self.fail.get(name))
            if fault=='raise':raise OSError(name+' injected')
            if fault is not None:return fault
            if name=='GetDC':
                self.next+=1;self.screen.add(self.next);return self.next
            if name=='ReleaseDC':self.screen.remove(args[1]);return 1
            if name=='CreateCompatibleDC':
                self.next+=1;self.live[self.next]='dc';self.selected[self.next]=1;return self.next
            if name in ('CreateCompatibleBitmap','CreateFontW'):
                self.next+=1;self.live[self.next]='bitmap' if name.endswith('Bitmap') else 'font';return self.next
            if name=='SelectObject':
                dc,obj=args;old=self.selected[dc];self.selected[dc]=obj;return old
            if name=='DeleteObject':
                if args[0] in self.selected.values():return 0
                del self.live[args[0]];return 1
            if name=='DeleteDC':del self.live[args[0]];del self.selected[args[0]];return 1
            if name=='GetClientRect':args[1]._obj.right=320;args[1]._obj.bottom=240
            if name=='GetTextExtentPoint32W':args[-1]._obj.cx=20;args[-1]._obj.cy=12
            return 1
        return call

def window(api):
    ns=dict(vars(ctypes));ns.update(vars(wintypes));ns.update(vars(abi))
    ns.update(ctypes=ctypes,user32=api,gdi32=api,msimg32=api,WNDPROC=lambda fn:ctypes.c_void_p(99))
    exec(CODE,ns);obj=ns['GDIWindow']();obj.hwnd=13;return obj

class GdiSafetyTests(unittest.TestCase):
    def test_partial_allocation_rolls_back(self):
        for name in ('GetDC','CreateCompatibleDC','CreateCompatibleBitmap','SelectObject'):
            for fault in (0,'raise'):
                with self.subTest(name=name,fault=fault):
                    api=Model();api.fail[name]=fault;obj=window(api)
                    with self.assertRaises(OSError):obj._create_backbuffer(320,240)
                    self.assertEqual(api.live,{});self.assertEqual(api.screen,set())
                    self.assertFalse(obj.mem_dc);self.assertFalse(obj.mem_bitmap)
                    self.assertEqual((obj.mem_w,obj.mem_h),(0,0))

    def test_failed_release_retains_handle_and_blocks_overwrite(self):
        for fault in (0,'raise'):
            api=Model();obj=window(api);obj._create_backbuffer(320,240)
            api.fail['DeleteDC']=fault;api.fail['DeleteObject']=fault
            self.assertFalse(obj._dispose_backbuffer())
            self.assertIn(obj.mem_dc,api.live);self.assertIn(obj.mem_bitmap,api.live)
            before=dict(api.live)
            with self.assertRaises(safe.GDIError):obj._create_backbuffer(640,480)
            self.assertEqual(api.live,before)
            api.fail.clear();self.assertTrue(obj._dispose_backbuffer());self.assertEqual(api.live,{})

    def test_deselect_failure_still_deletes_dc_then_bitmap(self):
        for fault in (0,'raise'):
            api=Model();obj=window(api);obj._create_backbuffer(320,240)
            api.fail['SelectObject']=fault;api.events.clear()
            self.assertTrue(obj._dispose_backbuffer())
            self.assertEqual(api.events,['SelectObject','DeleteDC','DeleteObject'])
            self.assertEqual(api.live,{})

    def test_close_continues_after_font_and_overlay_failures(self):
        api=Model();obj=window(api);obj.begin_composite();obj._ensure_overlay_bg_resources();obj._ensure_overlay_fonts(12,16)
        api.fail['DeleteObject']=0
        obj.close()
        self.assertNotIn('dc',api.live.values());self.assertTrue(obj.overlay_system_font);self.assertTrue(obj.overlay_bg_bitmap)
        self.assertIsNone(obj.hwnd)
        api.fail.clear();obj.close();self.assertEqual(api.live,{})

    def test_overlay_creation_failure_falls_back_without_leaking(self):
        for name in ('CreateCompatibleDC','CreateCompatibleBitmap','SelectObject','FillRect'):
            api=Model();obj=window(api);obj.begin_composite();original=dict(api.live)
            api.fail[(name,api.calls.get(name,0)+1)]=0
            obj._draw_overlay_background(0,0,10,10,100)
            self.assertEqual(api.live,original)
            self.assertFalse(getattr(obj,'_overlay_bg_ready',False))
            self.assertEqual(api.events[-1],'FillRect')
            obj.close();self.assertEqual(api.live,{})

    def test_drawing_zero_returns_are_errors_and_dc_is_returned(self):
        for name in ('SetStretchBltMode','StretchDIBits','BitBlt','FillRect','TextOutW','SetBkMode'):
            api=Model();obj=window(api);obj.begin_composite();api.fail[name]=0
            with self.subTest(name=name):
                with self.assertRaises(safe.GDIError):
                    if name=='BitBlt':obj.present()
                    elif name=='FillRect':obj.begin_composite()
                    elif name in ('TextOutW','SetBkMode'):obj._paint_overlay_text('test',0,0,0,0)
                    else:obj.draw_frame_to_rect(bytes(16),2,2,8,1,1,0,0,20,20)
                self.assertEqual(api.screen,set())
            api.fail.clear();obj.close()

    def test_zero_text_color_is_valid_but_clr_invalid_is_not(self):
        api=Model();obj=window(api);obj.begin_composite();api.fail['SetTextColor']=0
        obj._paint_overlay_text('test',0,0,0,0)
        api.fail['SetTextColor']=0xFFFFFFFF
        with self.assertRaises(safe.GDIError):obj._paint_overlay_text('test',0,0,0,0)
        obj.close()

    def test_window_dc_failure_retains_reference_for_retry(self):
        api=Model();obj=window(api);obj.begin_composite();api.fail['ReleaseDC']=0
        obj.present();self.assertEqual(len(obj._pending_window_dcs),1)
        self.assertEqual(set(dc for _,dc in obj._pending_window_dcs),api.screen)
        api.fail.clear();obj.close();self.assertEqual(api.screen,set());self.assertEqual(obj._pending_window_dcs,[])

    def test_orphan_bitmap_without_dc_is_freed(self):
        api=Model();obj=window(api);obj.mem_bitmap=api.CreateCompatibleBitmap(1,1,1)
        self.assertTrue(obj._dispose_backbuffer());self.assertEqual(api.live,{})

    def test_pending_dc_does_not_accumulate_on_repeated_present(self):
        api=Model();obj=window(api);obj.begin_composite();api.fail['ReleaseDC']=0
        obj.present();count=api.calls['GetDC']
        with self.assertRaises(safe.GDIError):obj.present()
        self.assertEqual(api.calls['GetDC'],count);self.assertEqual(len(api.screen),1)
        api.fail.clear();obj.close();self.assertFalse(api.screen)

    def test_notification_and_window_failure_do_not_block_gdi_cleanup(self):
        api=Model();obj=window(api);obj.begin_composite();obj.power_notification=77
        api.fail['UnregisterPowerSettingNotification']='raise';api.fail['DestroyWindow']=0
        obj.close();self.assertEqual(api.live,{})
        self.assertEqual(obj.power_notification,77);self.assertEqual(obj.hwnd,13)
        api.fail.clear();obj.close();self.assertIsNone(obj.power_notification);self.assertIsNone(obj.hwnd)

    def test_invalid_window_size_read_is_not_a_one_pixel_success(self):
        api=Model();obj=window(api);api.fail['GetClientRect']=0
        with self.assertRaises(safe.GDIError):obj.client_size()

    def test_font_creation_failure_is_reported_and_first_font_remains_owned(self):
        api=Model();obj=window(api);api.fail[('CreateFontW',2)]=0
        with self.assertRaises(safe.GDIError):obj._ensure_overlay_fonts(12,16)
        self.assertIn(obj.overlay_system_font,api.live);self.assertIsNone(obj.overlay_game_font)
        obj.close();self.assertEqual(api.live,{})

    def test_backdrop_creation_failure_closes_unreturned_window(self):
        import ast
        from pathlib import Path
        from unittest.mock import Mock
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if getattr(n,'name','')=='create_supervisor_backdrop')
        for phase in ('create','begin_composite','present'):
            obj=Mock();getattr(obj,phase).side_effect=safe.GDIError('injected')
            ns={'GDIWindow':Mock(return_value=obj)}
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<backdrop>','exec'),ns)
            with self.assertRaises(safe.GDIError):ns['create_supervisor_backdrop']({})
            obj.close.assert_called_once()

if __name__=='__main__':unittest.main()
