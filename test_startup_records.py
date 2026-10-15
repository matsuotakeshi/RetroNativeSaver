import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import favorites
import startup_preparation
import title_metadata
import test_startup_compatibility as harness
from tests_fixtures import legacy_records_v082 as old


class FullStartupRecordTests(harness.StartupCompatibilityTests):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent
        cls.before=harness.functions(root/'tests_fixtures/legacy_startup_v082.py')
        cls.after=harness.functions(root/'native_saver.py')


class StartupRecordTests(unittest.TestCase):
    def compare(self, name, args):
        target={'prepare_core_paths':startup_preparation,'append_slot_metadata':title_metadata,
                'record_favorite_startup':favorites}[name]
        results=[]
        for module in (old,target):
            data=copy.deepcopy(args); log=io.StringIO()
            with contextlib.redirect_stdout(log):
                try: value=('ok',getattr(module,name)(*data))
                except Exception as exc: value=('error',type(exc).__name__,str(exc))
            results.append((value,log.getvalue(),data))
        self.assertEqual(*results)
        return results[1]

    def test_relative_absolute_missing_and_existing_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); core=root/'core.dll'; core.write_bytes(b'placeholder')
            for name in ('core.dll',str(core),'missing.dll'):
                result=self.compare('prepare_core_paths',({'id':'a','name':'A','core':name},root,root,2,3,set(),'rom.zip'))
                if name=='missing.dll':
                    self.assertIsNone(result[0][1]); self.assertEqual(result[2][-2],{'rom.zip'})
                else:
                    self.assertEqual(result[0][1],(core.resolve(),root/'slot_2_3_core.dll',root/'slot_2_3'))
                    self.assertTrue((root/'slot_2_3').is_dir())

    def test_path_errors_before_core_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'core.dll').write_bytes(b'placeholder')
            for method in ('resolve','exists','mkdir'):
                with patch.object(Path,method,side_effect=PermissionError('blocked '+method)):
                    result=self.compare('prepare_core_paths',({'name':'A','core':'core.dll'},root,root,0,1,set(),'rom'))
                    self.assertEqual(result[0][0],'error')
                    self.assertEqual(result[2][-2],set())
            for system in ({},{'core':None},{'core':'missing.dll'}):
                self.compare('prepare_core_paths',(system,root,root,0,1,set(),'rom'))

    def test_existing_file_blocks_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'core.dll').write_bytes(b'x'); (root/'slot_0_1').write_bytes(b'blocked')
            result=self.compare('prepare_core_paths',({'core':'core.dll'},root,root,0,1,set(),'rom'))
            self.assertEqual(result[0][1],'FileExistsError')

    def test_metadata_titles_fallbacks_and_existing_lists(self):
        for system in ({'id':'a','name':'A'},{'id':'a'},{},{'id':'a','name':None}):
            for maps in ({},{'a':{'game':'Readable title'}}):
                result=self.compare('append_slot_metadata',(system,Path('game.zip'),maps,[('old','old')],[('old','old')]))
                self.assertEqual(result[2][-1][-1][1],'game.zip')

    def test_metadata_partial_updates_when_second_append_fails(self):
        class FailList(list):
            def append(self,value): raise RuntimeError('append failed')
        result=self.compare('append_slot_metadata',({'id':'a'},Path('game.zip'),{},[],FailList()))
        self.assertEqual(result[0][0],'error')
        self.assertEqual(result[2][-2],[('a','game')])
        result=self.compare('append_slot_metadata',({'id':'a'},None,{},[],[]))
        self.assertEqual(result[0][0],'error')
        self.assertEqual(result[2][-2],[])

    def test_favorite_usage_and_status_log(self):
        initial={'id':'a','resource_group':'heavy_cd','resource_weight':1}
        selected={'id':'b','resource_group':'heavy_cd','resource_weight':2}
        for candidates in ([],[(selected,Path('game'))],[(initial,Path('other'))]):
            result=self.compare('record_favorite_startup',(initial,selected,Path('game'),candidates,{'heavy_cd':2}))
            self.assertEqual(result[2][-1],{'heavy_cd':3})
            self.assertIn('READY' if candidates and candidates[0][0] is selected else 'normal fallback',result[1])

    def test_favorite_partial_usage_change_before_bad_entry(self):
        initial={'id':'a','resource_group':'heavy_cd','resource_weight':1}
        selected={'id':'b','resource_group':'heavy_cd','resource_weight':2}
        result=self.compare('record_favorite_startup',(initial,selected,Path('game'),[({},Path('x'))],{'heavy_cd':1}))
        self.assertEqual(result[0][1],'KeyError')
        self.assertEqual(result[2][-1],{'heavy_cd':2})
