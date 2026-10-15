import ast
import contextlib
import copy
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import rom_catalog
import startup_timing
from title_metadata import _title_key


class CatalogPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent
        cls.legacy=(root/'tests_fixtures/legacy_catalog_pipeline_v074.py').read_text(encoding='utf-8')
        source=(root/'native_saver.py').read_text(encoding='utf-8')
        main=source.index('def main():')
        marker='    from rom_catalog import build_catalogs\n'
        start=source.find(marker,main)
        if start<0:start=source.index('    catalogs = {}',main)
        end=source.index('    favorite_catalogs = catalogs',start)
        cls.current='def build_catalogs(systems, title_maps, worker_mode, session_quarantine, write_runtime_trace):\n'+source[start:end]+'    return catalogs\n'

    def compare(self,systems,roms,titles=None,worker=True,quarantine=None,fail=None):
        def run(code):
            data=copy.deepcopy((systems,titles or {},quarantine or {})); original=copy.deepcopy(data)
            events=[]; log=io.StringIO()
            def trace(phase,**kwargs):
                events.append(('trace',phase,kwargs))
                if fail=='trace':raise OSError('trace failed')
            def scan(system,progress=None):
                events.append(('scan',copy.deepcopy(system)))
                if fail==system['id']:raise OSError('scan failed')
                if progress:progress(128)
                return list(roms.get(system['id'],[]))
            def key(path):
                events.append(('title_key',path))
                return _title_key(path)
            ns=dict(scan_roms=scan,_title_key=key,startup=startup_timing,APP_DIR=Path('test-app'))
            exec(compile(code,'<pipeline>','exec'),ns)
            # Compare the existing live-scan path; fixed-file hits/failures have
            # dedicated integration tests in test_fixed_rom_catalog.
            with contextlib.redirect_stdout(log),patch('fixed_rom_catalog.read_catalog',return_value={}),patch.object(rom_catalog,'scan_roms',side_effect=scan),patch.object(rom_catalog,'_title_key',side_effect=key,create=True):
                try:result=('ok',ns['build_catalogs'](data[0],data[1],worker,data[2],trace))
                except Exception as exc:result=('error',type(exc).__name__,str(exc))
            self.assertEqual(data,original)
            return result,events,log.getvalue()
        old=run(self.legacy); new=run(self.current)
        self.assertEqual(new,old)
        return new

    def test_skip_rules_and_backend_values(self):
        for enabled in (True,False,None,'false'):
            for backend in ('software','opengl','glcore','GLCORE',' glcore ',None,'unsupported'):
                system=dict(id='a',name='A',enabled=enabled,render_backend=backend)
                self.compare([system],{'a':[Path('x.zip')]})

    def test_quarantine_before_title_filter_and_worker_scope(self):
        systems=[dict(id='a',name='A',require_title_db_match=True)]
        roms={'a':[Path('bad.zip'),Path('KEEP.ZIP'),Path('other.zip')]}
        for worker in (True,False):
            for quarantine in ({},{'A':{'bad.zip'}},{'a':{'bad.zip'}},{'A':{'BAD.ZIP'}}):
                for titles in ({},{'a':{}},{'a':{'keep':'Good'}},{'a':{'bad':'Bad','keep':'Good'}}):
                    self.compare(systems,roms,titles,worker,quarantine)
        result=self.compare(systems,roms,{'a':{'keep':'Good'}},True,{'A':{'bad.zip'}})
        self.assertEqual(result[0],('ok',{'a':[Path('KEEP.ZIP')]}))
        self.assertNotIn(('title_key',Path('bad.zip')),result[1])

    def test_system_order_duplicate_ids_and_empty_catalogs(self):
        systems=[dict(id='b',name='B'),dict(id='a',name='A'),dict(id='empty'),
                 dict(id='b',name='Again',require_title_db_match=True)]
        result=self.compare(systems,{'a':[Path('a.zip')],'b':[Path('b.zip'),Path('b2.zip')]}, {'b':{'b2':'B2'}})
        self.assertEqual(list(result[0][1]),['b','a'])
        self.assertEqual(result[0][1]['b'],[Path('b2.zip')])
        self.assertEqual([e[1]['id'] for e in result[1] if e[0]=='scan'],['b','a','empty','b'])
        self.assertEqual([e[2]['call_count'] for e in result[1] if e[0]=='trace' and 'call_count' in e[2]],[128]*4)

    def test_failures_and_invalid_values_keep_order(self):
        systems=[dict(id='a',name='A'),dict(id='b',name='B')]
        for fail in ('a','b','trace'):
            result=self.compare(systems,{'a':[Path('a.zip')]},fail=fail)
            self.assertEqual(result[0][0],'error')
        for system in ({},{'enabled':False},{'id':'a','name':None,'require_title_db_match':True}):
            for titles in ({},{'a':None},{'a':[]}):
                self.compare([system],{'a':[Path('game.zip')]},titles)


if __name__=='__main__': unittest.main()
