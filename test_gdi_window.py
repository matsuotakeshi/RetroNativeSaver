"""Behavioral checks limited to GDI creation and message handling."""
import ast
from test_gdi_support import drawing_classes
import contextlib
import ctypes
from ctypes import wintypes
from functools import cache
import io
from pathlib import Path
import unittest
import uuid

ROOT = Path(__file__).parent
OLD = (ROOT/'tests_fixtures/legacy_gdi_window_v100.py').read_text(encoding='utf-8')
# Normalize only the intentional title/version change for the legacy behavior comparison.
NEW = (ROOT/'native_saver.py').read_text(encoding='utf-8').replace('f"Retro Native Saver {APP_VERSION}"', '"Retro Native Saver v0.20.100"')
KEEP = {'__init__', '_note_exit', '_request_display_exit', '_unregister_power_notification',
        '_proc', 'create', 'pump', '_handle_power_message', '_handle_mouse_move',
        '_register_window_class', '_prepare_window_geometry', '_show_created_window'}

def norm(v):
    if hasattr(v, '_obj'): return norm(v._obj)
    if isinstance(v, ctypes.Structure): return tuple(norm(getattr(v, f[0])) for f in v._fields_)
    if isinstance(v, ctypes.Array): return tuple(v)
    if isinstance(v, ctypes.c_void_p): return v.value
    return v

@cache
def code(source):
    support=[]
    for n in ast.parse(NEW).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and (t.id.startswith(('WM_', 'PBT_', 'WS_', 'SW_', 'CS_', 'SM_', 'IDC_', 'CW_')) or t.id in ('SESSION_DISPLAY_GUID','PM_REMOVE')) for t in n.targets): support.append(n)
        if isinstance(n, ast.ClassDef) and n.name in ('WNDCLASSW','RECT','POINT','MSG','PowerBroadcastSetting'): support.append(n)
    return compile(ast.Module(body=support+drawing_classes(source, KEEP|{'_init_backbuffer_state','_init_overlay_state'}),type_ignores=[]),'<GDI window>','exec')

class WindowTests(unittest.TestCase):
    def compare(self, messages=None, options=None, state=None, fail=None, zero=None, parent_gone=False, last_error=5, cursor=(10,20), queue=()):
        results=[]
        for source in (OLD, NEW):
            events=[];windows=[0];pending=list(queue)
            class API:
                def __getattr__(self,name):
                    def call(*args):
                        events.append((name,tuple(norm(v) for v in args)))
                        if len(events)==fail: raise OSError('injected window failure')
                        if name=='IsWindow':
                            if name==zero:return 0
                            windows[0]+=1
                            return not parent_gone or windows[0]==1
                        if name==zero: return 0
                        if name=='GetClientRect':
                            args[1]._obj.right=320;args[1]._obj.bottom=240
                        if name=='GetCursorPos':args[0]._obj.x,args[0]._obj.y=cursor
                        if name=='GetSystemMetrics':return {76:-1920,77:-100,78:4480,79:1180}[args[0]]
                        if name=='PeekMessageW':
                            if not pending:return 0
                            args[0]._obj.message=pending.pop(0);return 1
                        return {'GetModuleHandleW':11,'LoadCursorW':12,'CreateWindowExW':13,'RegisterPowerSettingNotification':14,'DefWindowProcW':77}.get(name,1)
                    return call
            api=API();ns=dict(vars(ctypes));ns.update(vars(wintypes))
            ns.update(ctypes=ctypes,uuid=uuid,user32=api,kernel32=api,WNDPROC=lambda f:ctypes.c_void_p(99))
            exec(code(source),ns);ctypes.set_last_error(last_error)
            obj=ns['GDIWindow'](**(options or {}));obj.__dict__.update(state or {})
            log=io.StringIO();values=[]
            with contextlib.redirect_stdout(log):
                try:
                    if messages is None: values.append(obj.create())
                    else:
                        for message in messages:
                            kind=message[0]
                            if kind=='power':
                                event=ns['PowerBroadcastSetting']();event.guid[:]=ns['SESSION_DISPLAY_GUID'] if len(message)<3 or message[2] else bytes(16);event.length=message[3] if len(message)>3 else 4;event.state=message[1]
                                values.append(obj._proc(13,ns['WM_POWERBROADCAST'],ns['PBT_POWERSETTINGCHANGE'],ctypes.addressof(event)))
                            elif kind=='pump':obj.pump()
                            else:values.append(obj._proc(13,ns.get(kind,0x9999),message[1] if len(message)>1 else 0,message[2] if len(message)>2 else 0))
                    error=None
                except Exception as exc:error=(type(exc).__name__,str(exc))
            snapshot={k:norm(v) for k,v in vars(obj).items() if k!='_wndproc'}
            # Raw pointer addresses in DefWindowProc power payloads are irrelevant.
            events=[(name,args[:3]+('power-pointer',) if name=='DefWindowProcW' and args[1]==ns['WM_POWERBROADCAST'] and args[3] else args) for name,args in events]
            # Exit detail lines were intentionally removed. Keep all API calls,
            # exceptions, state and remaining logs in the legacy comparison.
            retained_log=[]
            for line in log.getvalue().splitlines(keepends=True):
                if 'GetCursorPos failed' in line:
                    line='[input] GetCursorPos failed; mouse notification ignored\n'
                elif line.startswith(('[exit-diagnostic]', '[exit]')):
                    continue
                retained_log.append(line)
            results.append((values,error,events,snapshot,''.join(retained_log)))
        self.assertEqual(*results);return results[1]

    def test_create_modes_and_each_operation_failure(self):
        for options in ({},{'fullscreen':True},{'parent_hwnd':22,'preview_mode':True},{'parent_hwnd':22,'embedded_rect':(-2,3,100,80)},{'hide_cursor':False},{'fullscreen':True,'preview_mode':True}):
            baseline=self.compare(options=options);self.assertEqual(baseline[0],[True]);self.assertIsNone(baseline[1])
            for step in range(1,len(baseline[2])+1):self.compare(options=options,fail=step)
        for zero in ('RegisterClassW','CreateWindowExW','RegisterPowerSettingNotification'):
            self.compare(options={'fullscreen':True},zero=zero)
        self.assertEqual(self.compare(zero='RegisterClassW',last_error=1410)[0],[True])

    def test_preview_parent_disappears_and_rect_failure(self):
        r=self.compare(options={'parent_hwnd':22},zero='IsWindow')
        self.assertEqual(r[0],[False]);self.assertTrue(r[3]['should_close'])
        r=self.compare(options={'parent_hwnd':22},zero='GetClientRect',parent_gone=True)
        self.assertEqual(r[0],[False]);self.assertTrue(r[3]['should_close'])
        self.assertIsNotNone(self.compare(options={'parent_hwnd':22},zero='GetClientRect')[1])

    def test_power_sequences_modes_and_invalid_payloads(self):
        for full in (False,True):
            for preview in (False,True):
                for hold in (False,True):
                    for exit_off in (False,True):
                        for seq in ([('power',2),('power',0),('power',1)],[('power',0),('power',0),('power',1)],[('power',1)],[('power',99)],[('power',0,False)],[('power',0,True,3)]):
                            self.compare(seq,{'fullscreen':full,'preview_mode':preview},{'hold_on_display_power':hold,'exit_on_display_off':exit_off})
        for wp in (0,7,18,0x8013):self.compare([('WM_POWERBROADCAST',wp)],{'fullscreen':True})

    def test_input_exit_threshold_and_message_routing(self):
        for preview in (False,True):
            for msg in ('WM_KEYDOWN','WM_SYSKEYDOWN','WM_LBUTTONDOWN','WM_RBUTTONDOWN','WM_MBUTTONDOWN','WM_MOUSEWHEEL','WM_ERASEBKGND','WM_CLOSE','WM_DESTROY','unknown','WM_DISPLAYCHANGE'):
                for idle in (False,True):self.compare([(msg,0,0)],{'fullscreen':True,'preview_mode':preview},{'power_idle':idle,'power_notification':14})
        for first in (None,(0,0),(10,9),(10,8),(10,20)):
            self.compare([('WM_MOUSEMOVE',0,0xFFFF8000)],state={'first_mouse':first})
        r=self.compare([('WM_MOUSEMOVE',),('WM_MOUSEMOVE',)],zero='GetCursorPos')
        self.assertEqual(r[4].count('GetCursorPos failed'),1)
        r=self.compare([('WM_KEYDOWN',),('WM_CLOSE',),('WM_DESTROY',)])
        self.assertEqual(r[3]['exit_reason'],'key-down')

    def test_message_failure_boundaries_and_quit(self):
        for seq,state in [([('power',0)],{'exit_on_display_off':True}),([('power',0),('power',1)],{'hold_on_display_power':True}),([('WM_MOUSEMOVE',)],{'first_mouse':(0,0)})]:
            baseline=self.compare(seq,{'fullscreen':True},state)
            for step in range(1,len(baseline[2])+1):self.compare(seq,{'fullscreen':True},state,fail=step)
        result=self.compare([('pump',)],queue=(0x123,0x12,0x456))
        self.assertTrue(result[3]['should_close']);self.assertEqual(result[3]['exit_reason'],'WM_QUIT')

if __name__=='__main__':unittest.main()
