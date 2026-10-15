import ast
import inspect
import contextlib
import copy
import io
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests_fixtures import legacy_launch_v076 as old


def outcome(fn,*args):
    out,err=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
        try:
            value=fn(*args)
            if hasattr(value,'__dict__'):value=vars(value)
            result=('ok',value)
        except SystemExit as exc:result=('SystemExit',exc.code)
        except Exception as exc:result=('error',type(exc).__name__,str(exc))
    return result,out.getvalue(),err.getvalue()


class CliCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import launch_options
        cls.current=launch_options
        # Adapt only the deliberate new option, preserving the stored legacy
        # fixture and checking all old defaults, diagnostics and abbreviations.
        tree=ast.parse(inspect.getsource(old.parse_main_args))
        fn=tree.body[0]
        index=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
                   and any(isinstance(t,ast.Name) and t.id=='args' for t in n.targets))
        fn.body[index:index]=ast.parse("ap.add_argument('--presentation', choices=('auto','normal','single-system'), default='auto')").body
        ns=dict(old.__dict__)
        exec(compile(ast.fix_missing_locations(tree),'<legacy CLI plus presentation>','exec'),ns)
        cls.legacy_main=staticmethod(ns['parse_main_args'])

    def compare(self,name,*args):
        with patch('sys.argv',['RetroNativeSaver.scr']):
            expected=outcome(self.legacy_main if name=='parse_main_args' else getattr(old,name),*copy.deepcopy(args))
            actual=outcome(getattr(self.current,name),*copy.deepcopy(args))
        self.assertEqual(actual,expected)
        return actual

    def test_windows_switches_and_precedence(self):
        for argv in ([],['/s'],['-S','--windowed'],['/c:123'],['-c','999'],
                     ['/p','123'],['/p:0x10'],['-p','bad'],['/p'],['/p','--slots','2'],
                     ['/p:bad','/s'],['/s','/p','42','/c'],['/p','0x10','/p'],[None,1,'/s'],
                     ['--system','pcenginecd','/s']):
            original=copy.deepcopy(argv)
            self.compare('parse_screensaver_args',argv)
            self.assertEqual(argv,original)

    def test_generated_windows_switch_sequences(self):
        rng=random.Random(77)
        tokens=['/s','/c','/c:10','/p','/p:0x20','bad','0','--windowed','--system','ps2']
        for _ in range(300):
            self.compare('parse_screensaver_args',[rng.choice(tokens) for _ in range(rng.randrange(10))])

    def test_normal_cli_defaults_overrides_and_flags(self):
        cases=[[],['--worker','--windowed','--favorites','--force-system'],
               ['--system',' Mega-CD ','--slots','3','--cycle-seconds','180'],
               ['--config','custom.json','--config','last.json'],
               ['--no-hw-readback','--env-trace-frames','12','--disable-log-interface',
                '--disable-perf-interface','--no-frame-rebind','--trace-core-vars'],
               ['--slots','0'],['--slots=-3'],['--cycle-seconds','nan'],['--cycle-seconds','inf']]
        for argv in cases:
            # NaN doesn't compare equal to itself; argparse still must accept it.
            if 'nan' in argv:
                a=self.current.parse_main_args(argv,Path('C:/App'))
                b=old.parse_main_args(argv,Path('C:/App'))
                self.assertEqual(str(a.cycle_seconds),str(b.cycle_seconds))
            else:self.compare('parse_main_args',argv,Path('C:/App'))

    def test_cli_errors_help_and_abbreviations(self):
        for argv in (['--help'],['--unknown'],['--slots','bad'],['--cycle-seconds'],
                     ['--sys','ps2'],['--disable'],['/s'],['--rom-lists']):
            self.compare('parse_main_args',argv,Path('C:/App'))
        for argv in (['--rom-lists'],['--rom-lists','--config','x.json'],['--help'],
                     ['--rom-lists','--system','ps2'],['--config']):
            self.compare('parse_rom_list_args',argv,Path('C:/App'))


class RunSettingsCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import system_config
        cls.current=system_config

    def compare(self,name,*args):
        # Preserve alias checks separately; these comparisons also check errors/logs.
        expected=outcome(getattr(old,name),*copy.deepcopy(args))
        actual=outcome(getattr(self.current,name),*copy.deepcopy(args))
        self.assertEqual(actual,expected)
        return actual

    def test_display_modes_and_windowed_precedence(self):
        for mode in ('normal','screen','preview','config','unknown'):
            for full in (True,False,None,0,'false'):
                for windowed in (True,False):
                    self.compare('display_mode',mode,{'fullscreen':full},SimpleNamespace(windowed=windowed))
        self.compare('display_mode','screen',{},SimpleNamespace())
        self.compare('display_mode','preview',{},SimpleNamespace())

    def test_slot_count_cli_and_preview_defaults(self):
        for preview in (True,False):
            for slots in (None,0,-1,4,'3','bad'):
                for value in (None,0,-2,6,'5','bad'):
                    self.compare('requested_slot_count',{'preview_slot_count':value,'windowed_slot_count':value},SimpleNamespace(slots=slots),preview)
        for preview in (True,False):self.compare('requested_slot_count',{},SimpleNamespace(slots=None),preview)
        self.assertEqual(self.current.requested_slot_count({'windowed_slot_count':0},SimpleNamespace(slots=None),False),0)
        self.assertEqual(self.current.requested_slot_count({},SimpleNamespace(slots=0),False),1)

    def test_cycle_defaults_overrides_and_boundaries(self):
        for preview in (True,False):
            for cli in (None,0,-1,180,'2','bad'):
                for cfg in ({},{'cycle_enabled':False,'preview_cycle_enabled':True},
                            {'cycle_seconds':7,'preview_cycle_seconds':8,'fade_duration_ms':-1},
                            {'overlay':None,'startup_retry_attempts':'3','runtime_heartbeat_seconds':0}):
                    self.compare('cycle_settings',cfg,SimpleNamespace(cycle_seconds=cli),preview)
        normal=self.current.cycle_settings({},SimpleNamespace(cycle_seconds=None),False)
        preview=self.current.cycle_settings({},SimpleNamespace(cycle_seconds=None),True)
        self.assertEqual(normal[:2],(True,240.0));self.assertEqual(preview[:2],(False,30.0))

    def test_conversion_order_and_overlay_identity(self):
        for field in ('cycle_seconds','startup_retry_attempts','fade_duration_ms','runtime_heartbeat_seconds'):
            for value in (None,'bad',[],0,-1):
                self.compare('cycle_settings',{field:value},SimpleNamespace(cycle_seconds=None),False)
        self.compare('cycle_settings',dict(cycle_seconds='bad',startup_retry_attempts=None,fade_duration_ms=[]),SimpleNamespace(cycle_seconds=None),False)
        overlay={'enabled':True}; cfg={'overlay':overlay}; before=copy.deepcopy(cfg)
        result=self.current.cycle_settings(cfg,SimpleNamespace(cycle_seconds=None),False)
        self.assertIs(result[3],overlay);self.assertEqual(cfg,before)


class LaunchSystemCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import system_config
        cls.current=system_config

    def compare(self,name,*args):
        before=copy.deepcopy(args); after=copy.deepcopy(args)
        expected=outcome(getattr(old,name),*before)
        actual=outcome(getattr(self.current,name),*after)
        self.assertEqual(actual,expected);self.assertEqual(after,before)
        return actual,after

    def test_preview_filter_order_and_truthiness(self):
        systems=[dict(id='a'),dict(id='b',process_recycle_required=True),dict(id='c',process_recycle_required='false'),dict(id='d',process_recycle_required=False)]
        result,_=self.compare('filter_preview_systems',systems)
        self.assertEqual([s['id'] for s in result[0][1]],['a','d'])
        for systems in ([],[{}],[{'process_recycle_required':None}]):self.compare('filter_preview_systems',systems)

    def test_session_mutation_names_counts_and_errors(self):
        systems=[dict(id='a',name='A',enabled=True),dict(id='b'),dict(id='c',name=None),dict(id='d',name='A')]
        for disabled in (set(),{'A'},{'a'},{'b','None'}):
            for quarantine in ({},{'A':{'x','y'}},{'A':None}):
                self.compare('apply_session_suspensions',systems,quarantine,disabled)
        result,mutated=self.compare('apply_session_suspensions',systems,{}, {'A'})
        self.assertIsNone(result[0][1]);self.assertFalse(mutated[0][0]['enabled']);self.assertFalse(mutated[0][3]['enabled'])


if __name__=='__main__':unittest.main()
