"""Compare the refactor with frozen .64 behavior, including existing quirks."""
import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest

import resource_policy as policy
import system_config
from independent_slots import select_slot
from tests_fixtures import legacy_v064 as legacy


def outcome(function, *args, **kwargs):
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        try:
            result = ('ok', function(*args, **kwargs))
        except Exception as exc:
            result = ('error', type(exc).__name__, str(exc))
    return result, log.getvalue()


class RefactorCompatibilityTests(unittest.TestCase):
    def test_cycle_resource_values_and_errors_match(self):
        groups = ['', 'heavy_cd', ' heavy_cd ', None, 0]
        weights = [0, 1, 2, -1, '2', 'bad', None, 2.8]
        configs = [{}, {'resource_groups':None}, {'resource_groups':[]},
                   {'resource_groups':{'heavy_cd':None}}]
        configs += [{'resource_groups':{'heavy_cd':{'max_weight':x}}}
                    for x in [0, 1, 2, -1, '2', 'bad', None]]
        for group in groups:
            for weight in weights:
                system = dict(id='a',resource_group=group,resource_weight=weight)
                self.assertEqual(outcome(legacy._resource_group_info,system), outcome(policy._resource_group_info,system))
                for cfg in configs:
                    self.assertEqual(outcome(legacy._resource_group_limit,cfg,group), outcome(policy._resource_group_limit,cfg,group))
                    for replacing in [None,dict(resource_group='heavy_cd',resource_weight=2),system]:
                        usage = {'heavy_cd':2,'other':1}
                        before = copy.deepcopy(usage)
                        self.assertEqual(outcome(legacy._resource_group_can_add,system,usage,cfg,replacing),
                                         outcome(policy._resource_group_can_add,system,usage,cfg,replacing))
                        self.assertEqual(usage,before)

    def test_resource_accumulation_and_retry_replacement(self):
        a = dict(id='a',resource_group='heavy_cd',resource_weight=2)
        for b in [dict(id='b'),dict(id='b',resource_group='other',resource_weight=1),
                  dict(id='b',resource_group='heavy_cd',resource_weight=3)]:
            picks=[(a,Path('a')),(b,Path('b'))]
            self.assertEqual(legacy._resource_group_usage_from_picks(picks),policy._resource_group_usage_from_picks(picks))
            expected={'heavy_cd':1}; actual=expected.copy()
            group,weight=legacy._resource_group_info(a)
            if group: expected[group]=max(0,expected.get(group,0)-weight)
            legacy._resource_group_add_usage(b,expected)
            policy.replace_cycle_usage(a,b,actual)
            self.assertEqual(expected,actual)

    def test_cycle_selection_matches_seed_and_log(self):
        tree=ast.parse(Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8'))
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and
                   (n.name.startswith('_resource_group_') or n.name=='choose_slots')]
        ns=dict(random=random,Path=Path)
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<cycle>', 'exec'),ns)
        systems=[dict(id='a',max_concurrent=1,resource_group='heavy_cd',resource_weight=2),
                 dict(id='b',resource_group='heavy_cd',resource_weight=1),dict(id='c',max_concurrent=3)]
        catalogs={s['id']:[Path(s['id']+'1'),Path(s['id']+'2')] for s in systems}
        for seed in range(100):
            cfg={'resource_groups':{'heavy_cd':{'max_weight':seed%5}}}
            fav=[(systems[0],catalogs['a'][0])] if seed%2 else []
            random.seed(seed)
            expected=outcome(legacy.choose_slots,systems,catalogs,cfg,seed%9,fav)
            state=random.getstate()
            random.seed(seed)
            actual=outcome(ns['choose_slots'],systems,catalogs,cfg,seed%9,fav)
            self.assertEqual(expected,actual)
            self.assertEqual(state,random.getstate())

    def test_independent_selection_matches_valid_settings(self):
        for seed in range(500):
            rng=random.Random(seed)
            systems=[dict(id=str(i),name=str(i),max_concurrent=rng.choice([0,1,2,999]),
                          resource_group=rng.choice(['heavy_cd','other','']),
                          resource_weight=rng.choice([0,1,2,-1,'2'])) for i in range(3)]
            catalogs={s['id']:[Path(s['id']+'1'),Path(s['id']+'2')] for s in systems}
            picks=[(s,catalogs[s['id']][0]) for s in systems]
            occupied=rng.sample(picks,rng.randrange(4))
            favorites=rng.sample(picks,rng.randrange(4))
            normal=occupied[1:] if seed%2 else None
            cfg=rng.choice([{}, {'resource_groups':{'heavy_cd':{'max_weight':rng.choice([0,1,3,'2',-1])}}}])
            banned={(s['id'],str(r)) for s,r in picks[:seed%2]}
            suspended={'2'} if seed%3 else set()
            left_rng=random.Random(seed); right_rng=random.Random(seed)
            args=(seed%3,systems,catalogs,cfg,occupied,favorites,banned,suspended)
            snapshot=copy.deepcopy(args)
            self.assertEqual(outcome(legacy.select_slot,*args,rng=left_rng,normal_occupied=normal),
                             outcome(select_slot,*args,rng=right_rng,normal_occupied=normal),seed)
            self.assertEqual(left_rng.getstate(),right_rng.getstate())
            self.assertEqual(args,snapshot)

    def test_loading_retains_sort_unknown_fields_and_bad_json_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'b.json').write_text('{"id":"b","unknown":{"x":1}}',encoding='utf-8')
            (root/'a.json').write_text('{"id":"a","enabled":false}',encoding='utf-8')
            (root/'bad.json').write_text('{broken',encoding='utf-8')
            (root/'bom.json').write_text('{"id":"bom"}',encoding='utf-8-sig')
            (root/'array.json').write_text('[]',encoding='utf-8')
            self.assertEqual(outcome(legacy.load_system_configs,root),outcome(system_config.load_system_configs,root))
            self.assertEqual(outcome(legacy.load_system_configs,root/'missing'),outcome(system_config.load_system_configs,root/'missing'))

    def test_cli_overrides_retain_filtering_and_mutations(self):
        source=[dict(id='a',name='Alpha',enabled=False),dict(id='b',name='Beta',unknown=42)]
        for name in [None,'A',' alpha ','missing']:
            for enabled in [False,True]:
                args=SimpleNamespace(system=name,force_system=enabled,no_hw_readback=enabled,
                    env_trace_frames=3 if enabled else 0,disable_log_interface=enabled,
                    disable_perf_interface=enabled,no_frame_rebind=enabled,trace_core_vars=enabled)
                left=copy.deepcopy(source); right=copy.deepcopy(source)
                self.assertEqual(outcome(legacy.apply_cli_system_overrides,left,args),outcome(system_config.apply_cli_system_overrides,right,args))
                self.assertEqual(left,right)


if __name__ == '__main__':
    unittest.main()
