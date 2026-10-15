import ast
import contextlib
import copy
import ctypes
import io
from pathlib import Path
import random
from types import SimpleNamespace
import unittest


class Variable(ctypes.Structure):
    _fields_=[('key',ctypes.c_char_p),('value',ctypes.c_char_p)]


class CoreOptionCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent
        source=(root/'native_saver.py').read_text(encoding='utf-8'); tree=ast.parse(source)
        decode=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='decode_cstr')
        core=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LibretroCore')
        from test_environment_boundaries import restore_environment_core
        core=restore_environment_core(core)
        install=next(n for n in core.body if isinstance(n,ast.FunctionDef) and n.name=='_install_callbacks')
        env=next(n for n in install.body if isinstance(n,ast.FunctionDef) and n.name=='env')
        names={'RETRO_ENVIRONMENT_SET_VARIABLES','RETRO_ENVIRONMENT_GET_VARIABLE'}
        branches=[n for n in env.body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and any(isinstance(x,ast.Name) and x.id in names for x in n.test.comparators)]
        fn=ast.FunctionDef(name='env',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=s) for s in ('self','cmd','data')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=branches,decorator_list=[])
        cls.apis=[]
        for nodes in ([decode]+ast.parse((root/'tests_fixtures/legacy_options_v084.py').read_text(encoding='utf-8')).body,[decode,fn]):
            ns=dict(ctypes=ctypes,POINTER=ctypes.POINTER,RetroVariable=Variable,
                    RETRO_ENVIRONMENT_SET_VARIABLES=16,RETRO_ENVIRONMENT_GET_VARIABLE=15)
            exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<options env>','exec'),ns)
            cls.apis.append(ns['env'])

    def compare(self, registrations, queries, overrides=None, initial=None, trace=False):
        results=[]
        for api in self.apis:
            core=SimpleNamespace(variables=copy.deepcopy(initial or {}),core_option_overrides=copy.deepcopy(overrides or {}),trace_core_vars=trace)
            variables=core.variables; override_map=core.core_option_overrides
            log=io.StringIO(); events=[]
            with contextlib.redirect_stdout(log):
                for batch in registrations:
                    array=(Variable*(len(batch)+1))()
                    for i,(key,value) in enumerate(batch):array[i].key=key; array[i].value=value
                    try:events.append(('set',api(core,16,ctypes.addressof(array))))
                    except Exception as exc:events.append(('error',type(exc).__name__,str(exc)))
                for key in queries:
                    value=Variable(key,b'old')
                    try:events.append(('get',api(core,15,ctypes.addressof(value)),value.value))
                    except Exception as exc:events.append(('error',type(exc).__name__,str(exc),value.value))
                events.append(('null',api(core,15,None)))
            self.assertIs(core.variables,variables); self.assertIs(core.core_option_overrides,override_map)
            results.append((events,core.variables,core.core_option_overrides,log.getvalue()))
        self.assertEqual(*results)
        return results[1]

    def test_defaults_overrides_and_dynamic_queries(self):
        result=self.compare([[(b'a',b'Label; first|second')]], [b'a',b'dynamic',b'missing'], {'a':b'override','dynamic':b'value'},trace=True)
        self.assertEqual(result[0][1:4],[('get',True,b'override'),('get',True,b'value'),('get',True,None)])

    def test_empty_missing_and_multiple_delimiters(self):
        for raw in (None,b'',b'label',b'label;',b'label; |second',b'label; first;extra|second',b'label;  first | second '):
            self.compare([[(b'a',raw)]],[b'a'],initial={'a':b'cached'},trace=True)

    def test_duplicate_keys_repeated_registration_and_empty_list(self):
        self.compare([[(b'a',b'L; one|two'),(b'a',b'L; three|four')],[],[(b'a',b'no default')]], [b'a'],trace=True)

    def test_unicode_invalid_bytes_and_dolphin_logging(self):
        self.compare([[(b'dolphin_option',b'L; first|second'),('機種'.encode(), '名称; 日本語|英語'.encode()),(b'bad\xff',b'L; \xffvalue')]],
                     [b'dolphin_option','機種'.encode(),b'bad\xff'],trace=True)

    def test_logging_disabled_and_error_after_update(self):
        for trace in (False,True):
            self.compare([[(b'a',b'L; first')]], [b'a'], {'a':None},trace=trace)
            # Invalid values cannot be passed to a real c_char_p: an integer is
            # interpreted as an address. Test registration and pre-write errors.
            self.compare([[(b'a',b'L; first')]], [b'a'] if trace else [], {'a':7},trace=trace)

    def test_null_key_and_terminating_empty_key(self):
        self.compare([[(b'',b'L; ignored'),(b'a',b'L; after')]], [None,b''],trace=True)

    def test_returned_bytes_remain_owned_by_core_dictionary(self):
        for api in self.apis:
            stored=b''.join([b'long',b'_option_value'])
            core=SimpleNamespace(variables={},core_option_overrides={'a':stored},trace_core_vars=False)
            value=Variable(b'a',None)
            self.assertTrue(api(core,15,ctypes.addressof(value)))
            self.assertIs(core.core_option_overrides['a'],stored)
            self.assertEqual(value.value,stored)

    def test_generated_registration_query_sequences(self):
        rng=random.Random(85)
        for _ in range(400):
            keys=[b'a',b'b',b'dolphin_x']
            batch=[(rng.choice(keys),rng.choice([None,b'No default',b'L; one|two',b'L; |two',b'L; three'])) for _ in range(rng.randrange(10))]
            overrides={key.decode():rng.choice([b'one',b'custom',b'']) for key in keys if rng.random()<.5}
            self.compare([batch],keys+[b'unknown'],overrides,trace=rng.choice([False,True]))
