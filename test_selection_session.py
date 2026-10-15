import contextlib
import copy
import io
import json
from pathlib import Path
import random
import unittest
import slot_selection
import rom_list_policy
from tests_fixtures import legacy_selection_v080 as old


class SelectionSessionTests(unittest.TestCase):
    def compare(self, name, args, seed=0):
        module = rom_list_policy if name == 'load_session_safety' else slot_selection
        outputs = []
        saved = random.getstate()
        try:
            for target in (old, module):
                data = copy.deepcopy(args)
                before = copy.deepcopy(data)
                random.seed(seed)
                log = io.StringIO()
                with contextlib.redirect_stdout(log):
                    try: value = ('ok', getattr(target, name)(*data))
                    except Exception as exc: value = ('error', type(exc).__name__, str(exc))
                self.assertEqual(data, before)
                outputs.append((value, log.getvalue(), random.getstate()))
            self.assertEqual(*outputs)
            return outputs[1][0]
        finally:
            random.setstate(saved)

    def test_selection_generated_results_logs_and_random_state(self):
        rng = random.Random(81)
        for seed in range(1000):
            systems = [{'id': str(i), 'name': str(i), 'enabled': rng.choice([True,True,False]),
                        'render_backend': rng.choice(['software','glcore','opengl','unknown']),
                        'max_concurrent': rng.choice([0,1,2,4,'bad']),
                        'resource_group': rng.choice(['','heavy_cd','other']),
                        'resource_weight': rng.choice([0,1,2,'bad'])} for i in range(4)]
            catalogs = {s['id']: [Path(f'{s["id"]}/{j}.zip') for j in range(rng.randrange(4))] for s in systems}
            fav = [(s,r) for s in systems for r in catalogs[s['id']]][:rng.randrange(6)]
            cfg = {'resource_groups': {'heavy_cd': {'max_weight': rng.choice([0,1,2,4,'bad'])}}}
            self.compare('choose_slots',(systems,catalogs,cfg,rng.randrange(-1,9),fav),seed)

    def test_favorite_reserved_before_resource_budget(self):
        a = {'id':'a','name':'A','resource_group':'heavy_cd','resource_weight':1}
        b = {'id':'b','name':'B','resource_group':'heavy_cd','resource_weight':1}
        pair = (a,Path('a.zip'))
        args = ([a,b],{'a':[pair[1]],'b':[Path('b.zip')]},
                {'resource_groups':{'heavy_cd':{'max_weight':1}}},4,[pair])
        self.assertEqual(self.compare('choose_slots',args)[1],[pair])

    def test_selection_invalid_inputs(self):
        for systems,catalogs in (([],{}),([None],{}),([{'id':'x','name':'X'}],{'x':[Path('a')]})):
            for count in (0,1,None,'bad'):
                self.compare('choose_slots',(systems,catalogs,{},count,None))

    def test_retry_order_failed_filter_and_random_state(self):
        a={'id':'a'}; b={'id':'b','enabled':False}
        paths=[Path(f'{i}.zip') for i in range(8)]
        fav=[(a,r) for r in paths]+[(b,paths[1])]
        for seed in range(100):
            self.compare('initial_retry_candidates',(a,paths[0],[a,b],{'a':paths,'b':paths},{str(paths[2])},fav),seed)

    def test_retry_empty_invalid_and_backend_cases(self):
        a={'id':'a'}; rom=Path('a.zip')
        systems=[a,{'id':'b','render_backend':'OPENGL'},{'id':'c','render_backend':'unknown'}]
        catalogs={s['id']:[rom] for s in systems}
        for favorites in (None,[],[(a,rom)],[({},rom)],[(a,None)]):
            self.compare('initial_retry_candidates',(a,rom,systems,catalogs,set(),favorites))
        self.compare('initial_retry_candidates',(a,rom,[None],catalogs,set(),None))

    def test_selection_and_retry_keep_references(self):
        a={'id':'a','name':'A'}; rom=Path('a.zip')
        with contextlib.redirect_stdout(io.StringIO()):
            picks=slot_selection.choose_slots([a],{'a':[rom]}, {},1)
        self.assertIs(picks[0][0],a); self.assertIs(picks[0][1],rom)
        candidates,enabled=slot_selection.initial_retry_candidates(a,rom,[a],{'a':[rom]},set(),None)
        self.assertIs(candidates[0][0],a); self.assertIs(enabled[0],a)

    def test_session_shapes_names_and_normalization(self):
        values=['','  ','{bad','null','[]','{}',json.dumps({'A':[' GAME.ZIP ','',None,3,'ß'], 'B':'not a list'}),
                json.dumps([' A ','',None,3,'ß'])]
        for quarantine in values:
            for disabled in values:
                self.compare('load_session_safety',({'Q':quarantine,'D':disabled},'Q','D'))

    def test_session_environment_read_order_and_uncaught_errors(self):
        outcomes=[]
        for target in (old,rom_list_policy):
            events=[]
            class Env:
                def get(self,key,default):
                    events.append(key)
                    return '{}' if key=='Q' else None
            try: result=target.load_session_safety(Env(),'Q','D')
            except Exception as exc: result=(type(exc).__name__,str(exc))
            outcomes.append((result,events))
        self.assertEqual(*outcomes)
        self.assertEqual(outcomes[1][1],['Q','D'])

    def test_session_preserves_name_whitespace_and_rom_casefold(self):
        result=self.compare('load_session_safety',({'Q':'{" A ":[" GAME.ZIP "]}','D':'[" A "]'},'Q','D'))
        self.assertEqual(result[1],({' A ':{' game.zip '}},{' A '}))
