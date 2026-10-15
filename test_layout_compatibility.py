import ast
import contextlib
import copy
import io
from pathlib import Path
import random
import unittest
from tests_fixtures import legacy_layout_v075 as old


def outcome(fn,*args):
    log=io.StringIO()
    with contextlib.redirect_stdout(log):
        try:value=('ok',fn(*args))
        except Exception as exc:value=('error',type(exc).__name__,str(exc))
    return value,log.getvalue()


class LayoutCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        names={'auto_grid_for_monitor','build_monitor_slots','build_windowed_slots'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        cls.ns={}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<layout>','exec'),cls.ns)

    def compare(self,name,*args):
        before=copy.deepcopy(args)
        expected=outcome(getattr(old,name),*args)
        actual=outcome(self.ns[name],*args)
        self.assertEqual(actual,expected)
        self.assertEqual(args,before)
        return actual[0]

    def test_auto_grid_thresholds(self):
        for width in (0,1920,2499,2500,3299,3300,3799,3800,7680):
            for height in (0,999,1000,1299,1300,1999,2000,4320):
                self.compare('auto_grid_for_monitor',width,height)
        self.assertEqual(self.ns['auto_grid_for_monitor'](3840,2160),(4,4))
        self.assertEqual(self.ns['auto_grid_for_monitor'](3440,1440),(4,3))

    def test_monitor_origin_order_caps_and_gap(self):
        monitors=[(-1920,-100,0,980),(0,0,3840,2160)]
        for cap in (-1,0,1,2,3,4,6,9,12,16,20):
            for gap in (-3,0,1,20,2000):
                self.compare('build_monitor_slots',monitors,-1920,-100,gap,cap)
        result=self.compare('build_monitor_slots',monitors,-1920,-100,0,16)[1]
        self.assertEqual(result[0],(0,0,960,540))
        self.assertEqual(result[4],(1920,100,960,540))
        self.compare('build_monitor_slots',[],0,0)
        self.compare('build_monitor_slots',list(reversed(monitors)),-1920,-100)

    def test_window_count_and_rounding_preserve_special_single_slot(self):
        for count in (-1,0,1,2,3,4,5,7,8,9,16):
            for gap in (-1,0,3,1000):
                self.compare('build_windowed_slots',1281,721,count,gap)
        self.assertEqual(self.ns['build_windowed_slots'](1281,721,0,99),[(0,0,1281,721)])
        rects=self.ns['build_windowed_slots'](1281,721,4,0)
        self.assertEqual(rects,[(0,0,640,360),(640,0,641,360),(0,360,640,361),(640,360,641,361)])

    def test_degenerate_and_invalid_values(self):
        for width,height in ((0,0),(-1,-1),(1,1),(2.5,3.5),(None,1),('1920',1080)):
            self.compare('auto_grid_for_monitor',width,height)
            for count in (1,2,5,None,'4',2.5):
                self.compare('build_windowed_slots',width,height,count,1)
        for monitors in ([(0,0,0,0)],[(100,100,0,0)],[(0,0,1)],[(None,0,1,1)]):
            for cap in (1,None,'4'):
                self.compare('build_monitor_slots',monitors,0,0,0,cap)
        for gap in (None,'2',2.5):
            self.compare('build_windowed_slots',1920,1080,4,gap)
            self.compare('build_monitor_slots',[(0,0,1920,1080)],0,0,gap)

    def test_generated_layouts(self):
        rng=random.Random(76)
        for _ in range(1000):
            width,height=rng.randrange(1,8001),rng.randrange(1,5001)
            left,top=rng.randrange(-4000,4000),rng.randrange(-2000,2000)
            gap=rng.randrange(-3,50)
            self.compare('build_monitor_slots',[(left,top,left+width,top+height)],
                         rng.randrange(-4000,0),rng.randrange(-2000,0),gap,rng.randrange(0,20))
            self.compare('build_windowed_slots',width,height,rng.randrange(0,25),gap)


if __name__=='__main__':unittest.main()
