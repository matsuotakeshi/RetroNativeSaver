import contextlib
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import favorites as current
from tests_fixtures import legacy_cycle_favorites_v078 as old


class CycleFavoritesTests(unittest.TestCase):
    def compare(self, name, *args):
        outcomes = []
        for module in (old, current):
            data = copy.deepcopy(args)
            before = copy.deepcopy(data)
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                try: result = ('ok', getattr(module, name)(*data))
                except Exception as exc: result = ('error', type(exc).__name__, str(exc))
            self.assertEqual(data, before)
            outcomes.append((result, log.getvalue()))
        self.assertEqual(*outcomes)
        return outcomes[1][0]

    def test_loading_filters_and_failed_roms(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'favorites.json'
            systems = [{'id': name, 'render_backend': backend} for name, backend in
                       [('a','software'),('b','OPENGL'),('c','glcore'),('d','unknown')]]
            systems.append({'id':'e','enabled':False})
            catalogs = {s['id']:[Path(s['id']+'.zip')] for s in systems}
            p.write_text(json.dumps({'items':[{'system':s['id'],'rom':s['id']+'.zip'} for s in systems]}))
            result = self.compare('load_cycle_favorites',p,systems,catalogs,{'b.zip'})
            self.assertEqual([s['id'] for s,r in result[1]], ['a','c'])

    def test_missing_invalid_disabled_and_empty_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'favorites.json'
            self.compare('load_cycle_favorites',p,[],{},set())
            for text in ('{bad','[]','{}','{"enabled":false,"items":[]}',
                         '{"items":[{"system":"missing","rom":"game.zip"}]}'):
                p.write_text(text)
                self.compare('load_cycle_favorites',p,[],{},set())

    def test_caught_and_uncaught_errors(self):
        for error in (OSError('read'),ValueError('format'),RuntimeError('unexpected')):
            with patch.object(old,'load_favorites',side_effect=error), patch.object(current,'load_favorites',side_effect=error):
                result=self.compare('load_cycle_favorites','unused',[],{},set())
                self.assertEqual(result[0], 'error' if isinstance(error,RuntimeError) else 'ok')

    def test_only_selected_first_slot_retries_favorites(self):
        a={'id':'a'}; rom=Path('a.zip'); fav=[(a,rom)]
        for i, selected in ((0,rom),(1,rom),(0,Path('other.zip'))):
            result=self.compare('cycle_favorite_retries',i,a,selected,fav,[(a,selected)],4,{})
            self.assertEqual(result[1],fav if i==0 and selected==rom else None)

    def test_concurrency_resource_budget_and_duplicate_rom(self):
        a={'id':'a','max_concurrent':2,'resource_group':'heavy_cd','resource_weight':1}
        b={'id':'b','max_concurrent':1,'resource_group':'heavy_cd','resource_weight':2}
        c={'id':'c','max_concurrent':1}
        fav=[(a,Path('one')),(a,Path('two')),(b,Path('three')),(c,Path('four'))]
        picks=[fav[0],fav[1],fav[3]]
        result=self.compare('cycle_favorite_retries',0,a,Path('one'),fav,picks,4,
                            {'resource_groups':{'heavy_cd':{'max_weight':2}}})
        self.assertEqual(result[1],[fav[0]])

    def test_selected_rom_duplicate_exception_is_preserved(self):
        a={'id':'a','max_concurrent':3}; pair=(a,Path('one'))
        result=self.compare('cycle_favorite_retries',0,a,pair[1],[pair],[pair,pair],4,{})
        self.assertEqual(result[1],[pair])

    def test_generated_resource_and_concurrency_conditions(self):
        rng=random.Random(79)
        for _ in range(300):
            systems=[{'id':str(i),'max_concurrent':rng.choice([0,1,2,4,'bad']),
                      'resource_group':rng.choice(['','heavy_cd','other']),
                      'resource_weight':rng.choice([0,1,2,-1,'bad'])} for i in range(4)]
            fav=[(s,Path(f'{s["id"]}_{j}.zip')) for s in systems for j in range(2)]
            picks=[fav[0]]+rng.sample(fav, rng.randrange(4))
            cfg={'resource_groups':{'heavy_cd':{'max_weight':rng.choice([0,1,2,3,'bad'])}}}
            self.compare('cycle_favorite_retries',0,systems[0],fav[0][1],fav,picks,4,cfg)

    def test_returned_pairs_keep_original_references(self):
        a={'id':'a'}; rom=Path('a.zip'); pair=(a,rom)
        result=current.cycle_favorite_retries(0,a,rom,[pair],[pair],4,{})
        self.assertIs(result[0][0],a)
        self.assertIs(result[0][1],rom)
