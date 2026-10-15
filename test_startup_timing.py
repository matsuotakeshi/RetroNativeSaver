import ast
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import startup_timing as timing


class StartupTimingTests(unittest.TestCase):
    def test_measured_result_and_exception_are_unchanged(self):
        events=[]
        with patch.object(timing, 'record', lambda event, **kw: events.append(kw)):
            value=object()
            self.assertIs(timing.measure('prepare', lambda: value), value)
            original=ValueError('failure')
            def fail(): raise original
            with self.assertRaises(ValueError) as caught:
                timing.measure('prepare', fail)
            self.assertIs(caught.exception, original)
        self.assertEqual([x['name'] for x in events], ['prepare_begin','prepare_end']*2)
        self.assertTrue(events[1]['completed'])
        self.assertFalse(events[3]['completed'])
        self.assertGreaterEqual(events[1]['elapsed_seconds'], 0)

    def test_logging_failure_does_not_replace_result_or_exception(self):
        with patch.object(timing, 'record', side_effect=OSError('disk full')):
            self.assertEqual(timing.measure('prepare', lambda: 5), 5)
            with self.assertRaisesRegex(ValueError, 'original'):
                with timing.span('prepare'): raise ValueError('original')

    def present_method(self):
        tree=ast.parse((Path(__file__).parent/'native_saver.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='GDIDrawingSurface')
        method=next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='present')
        self.blit_result=1; self.dc_result=9; self.released=[]
        api=SimpleNamespace(GetDC=lambda *a:self.dc_result, ReleaseDC=lambda *a:self.released.append(a) or 1)
        ns=dict(user32=api,gdi32=SimpleNamespace(BitBlt=lambda *a:self.blit_result),SRCCOPY=1)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'real present','exec'),ns)
        return ns['present']

    def test_present_milestones_require_real_success_and_nonblack_fade(self):
        present=self.present_method(); w=SimpleNamespace(hwnd=1,mem_dc=2,client_size=lambda:(100,100))
        events=[]
        with patch.object(timing,'record',lambda event,**kw:events.append(kw)):
            timing.arm_presentation(w,[1],255); present(w)
            self.assertFalse(events)
            timing.arm_presentation(w,[1],128); present(w)
            self.assertEqual([x['name'] for x in events],['first_game_gdi_submit'])
            timing.arm_presentation(w,[1],0); present(w)
            timing.arm_presentation(w,[1],0); present(w)
            self.assertEqual([x['name'] for x in events],['first_game_gdi_submit','first_unfaded_gdi_submit'])
            self.assertFalse(events[0]['physical_visibility_verified'])

    def test_failed_or_skipped_present_is_not_reported_and_pending_is_consumed(self):
        present=self.present_method(); w=SimpleNamespace(hwnd=1,mem_dc=2,client_size=lambda:(100,100))
        events=[]
        with patch.object(timing,'record',lambda event,**kw:events.append(kw)):
            self.blit_result=0
            timing.arm_presentation(w,[1],0)
            with self.assertRaises(OSError):present(w)
            self.assertEqual(len(self.released),1)
            self.blit_result=1
            present(w)  # A later background repaint must not consume stale game data.
            self.assertFalse(events)
            w.mem_dc=None
            timing.arm_presentation(w,[1],0);present(w)
            self.assertFalse(events)

    def test_multislot_progress_does_not_mark_unready_slots(self):
        w=SimpleNamespace(); events=[]
        with patch.object(timing,'record',lambda event,**kw:events.append(kw)):
            timing.arm_presentation(w,[2],0);timing.presented(w,w._startup_pending_present)
            self.assertEqual(w._startup_presented_slots,{2})
            timing.arm_presentation(w,[1,2,3],0);timing.presented(w,w._startup_pending_present)
            self.assertEqual([x['slot'] for x in events if x['name']=='first_game_gdi_submit'],[2,1,3])


if __name__=='__main__':unittest.main()
