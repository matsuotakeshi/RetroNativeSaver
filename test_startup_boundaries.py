import ast
import contextlib
import copy
import io
from pathlib import Path
import random
import textwrap
import unittest
import slot_selection
import resource_policy
import test_startup_compatibility as harness


class StartupBoundaryCompatibilityTests(harness.StartupCompatibilityTests):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent
        cls.before = harness.functions(root/'tests_fixtures/legacy_startup_v081.py')
        cls.after = harness.functions(root/'native_saver.py')

    def test_core_option_conversion_and_post_load_errors(self):
        for name in ('hw_context_width','hw_context_height','env_trace_frames','force_aspect_ratio'):
            for value in ('bad',None,0,-1,'640'):
                for recycle,worker in ((False,False),(True,True)):
                    self.compare(changes={name:value},recycle=recycle,worker=worker)

    def test_constructor_flags_and_aspect(self):
        keys=('hw_readback','provide_log_interface','provide_perf_interface',
              'frame_rebind_context','trace_core_vars','destroy_hw_before_unload')
        for value in (False,True,None,'false'):
            self.compare(changes=dict.fromkeys(keys,value))
        for value in (None,0,-1,1.333,'1.777',float('inf')):
            self.compare(changes={'force_aspect_ratio':value})

    def test_normal_retry_and_exhaustion_through_full_startup(self):
        root=Path(__file__).parent
        for exhausted in (False,True):
            outcomes=[]
            for path in (root/'tests_fixtures/legacy_startup_v081.py',root/'native_saver.py'):
                tree=ast.parse(path.read_text(encoding='utf-8'))
                nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                       {'resolve_app_relative_path','prepare_dolphin_user_config','start_slot_with_retry'}]
                fn=next(n for n in nodes if n.name=='start_slot_with_retry')
                setup='favorite_retries = None\n'
                if exhausted: setup+='catalogs = {initial_system["id"]: [initial_rom]}\n'
                fn.body[1:1]=ast.parse(setup).body
                code=compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(path),'exec')
                outcomes.append(self.run_case(code,retry=True))
            self.assertEqual(*outcomes)
            self.assertEqual(outcomes[1][0][0],'error' if exhausted else 'ok')


class NormalRetryCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(Path(__file__).parent/'tests_fixtures/legacy_startup_v081.py').read_text(encoding='utf-8')
        start=source.index('            if not enabled_supported:')
        end=source.index('        sid = system["id"]\n        rom_key',start)
        # Keep the old continue inside a one-iteration loop, ending with None.
        block=textwrap.indent(textwrap.dedent(source[start:end]),'        ')
        code='def choose(preferred_system, enabled_supported, catalogs, failed_roms, cycle_group_usage, cfg):\n    for _ in range(1):\n'+block+'        return system, rom\n    return None\n'
        ns={'random':random,'_resource_group_can_add':resource_policy._resource_group_can_add}
        exec(compile(code,'<legacy normal retry>','exec'),ns)
        cls.legacy=staticmethod(ns['choose'])

    def compare(self,args,seed=0):
        results=[]; saved=random.getstate()
        try:
            for fn in (self.legacy,slot_selection.normal_retry_candidate):
                data=copy.deepcopy(args); before=copy.deepcopy(data)
                random.seed(seed); log=io.StringIO()
                with contextlib.redirect_stdout(log):
                    try: result=('ok',fn(*data))
                    except Exception as exc: result=('error',type(exc).__name__,str(exc))
                self.assertEqual(data,before)
                results.append((result,log.getvalue(),random.getstate()))
            self.assertEqual(*results)
            return results[1][0]
        finally: random.setstate(saved)

    def test_preferred_system_and_replacement_budget(self):
        a={'id':'a','resource_group':'heavy_cd','resource_weight':1}
        b={'id':'b','resource_group':'heavy_cd','resource_weight':2}
        cfg={'resource_groups':{'heavy_cd':{'max_weight':2}}}
        catalogs={'a':[Path('bad'),Path('good')],'b':[Path('other')]}
        self.assertEqual(self.compare((a,[a,b],catalogs,{'bad'},{'heavy_cd':2},cfg))[1],(a,Path('good')))
        self.assertIsNone(self.compare((a,[a,b],catalogs,{'bad','good'},{'heavy_cd':2},cfg))[1])
        self.assertEqual(self.compare((a,[a,b],catalogs,{'bad','good'},{'heavy_cd':1},cfg))[1],(b,Path('other')))

    def test_empty_invalid_and_no_candidate(self):
        for systems,catalogs in (([],{}),([{'id':'a'}],{}),([None],{}),([{'id':'a'}],{'a':None})):
            self.compare(({'id':'a'},systems,catalogs,set(),None,{}))

    def test_generated_candidates_and_random_state(self):
        rng=random.Random(82)
        for seed in range(1000):
            systems=[{'id':str(i),'resource_group':rng.choice(['','heavy_cd','other']),
                      'resource_weight':rng.choice([0,1,2,'bad'])} for i in range(4)]
            catalogs={s['id']:[Path(f'{s["id"]}/{j}') for j in range(rng.randrange(4))] for s in systems}
            failed={str(p) for values in catalogs.values() for p in values if rng.random()<.7}
            cfg={'resource_groups':{'heavy_cd':{'max_weight':rng.choice([0,1,2,3,'bad'])}}}
            self.compare((systems[0],systems,catalogs,failed,{'heavy_cd':rng.randrange(5)},cfg),seed)
