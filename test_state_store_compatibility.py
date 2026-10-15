import ast
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

NAMES={'_empty_persistent_rom_state','_load_persistent_rom_state','_save_persistent_rom_state',
       '_empty_persistent_rom_whitelist','_load_persistent_rom_whitelist'}


def load(path):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in NAMES]
    ns=dict(json=json,os=os)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
    return ns


class StateStoreCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent
        cls.old=load(root/'tests_fixtures/legacy_state_store_v071.py')
        cls.new=load(root/'native_saver.py')

    def run_case(self,ns,operation,content=None,seed=None,state=None,failure=None,null_path=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'state/list.json'; seed_path=root/'default.json'
            if content is not None:
                path.parent.mkdir(); path.write_bytes(content)
            if seed is not None: seed_path.write_bytes(seed)
            state=copy.deepcopy(state)
            initial=copy.deepcopy(state)
            log=io.StringIO()
            original_write=Path.write_text
            def partial_write(p,*args,**kwargs):
                original_write(p,'partial',encoding='utf-8')
                raise OSError('partial write')
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(log))
                if failure in ('replace','replace+unlink'):
                    stack.enter_context(patch.object(os,'replace',side_effect=OSError('replace denied')))
                if failure=='replace+unlink':
                    stack.enter_context(patch.object(Path,'unlink',side_effect=OSError('unlink denied')))
                if failure=='write': stack.enter_context(patch.object(Path,'write_text',new=partial_write))
                if failure=='mkdir': stack.enter_context(patch.object(Path,'mkdir',side_effect=OSError('mkdir denied')))
                if failure=='read': stack.enter_context(patch.object(Path,'read_text',side_effect=OSError('read denied')))
                if failure=='exists': stack.enter_context(patch.object(Path,'exists',side_effect=OSError('exists denied')))
                actual_path=None if null_path else path
                try:
                    if operation=='save': result=ns['_save_persistent_rom_state'](actual_path,state)
                    elif operation=='white': result=ns['_load_persistent_rom_whitelist'](actual_path,seed_path if seed is not None else None)
                    else: result=ns['_load_persistent_rom_state'](actual_path)
                    value=('ok',result)
                except Exception as exc: value=('error',type(exc).__name__,str(exc))
            self.assertEqual(state,initial)
            files=[(str(p.relative_to(root)),p.read_bytes() if p.is_file() else 'dir') for p in sorted(root.rglob('*'))]
            return value,log.getvalue().replace(str(root),'<root>'),files

    def compare(self,operation,**kwargs):
        expected=self.run_case(self.old,operation,**kwargs)
        actual=self.run_case(self.new,operation,**kwargs)
        self.assertEqual(actual,expected)
        return actual

    def test_load_json_shapes_unknown_keys_and_encoding(self):
        payloads=[{},None,[],1,{'version':'2','systems':[],'extra':{'keep':1}},
                  {'version':'bad','systems':{}}, {'systems':{'日本語':['ゲーム.chd']}}]
        for payload in payloads:
            for encoding in ('utf-8','utf-8-sig'):
                content=json.dumps(payload,ensure_ascii=False).encode(encoding)
                for op in ('load','white'):
                    self.compare(op,content=content)
        for raw in (b'{broken',b'\xff\xfe',b''):
            for op in ('load','white'): self.compare(op,content=raw)

    def test_missing_null_and_fresh_empty_states(self):
        for op in ('load','white','save'):
            self.compare(op,null_path=True,state={})
            self.compare(op,state={})
        for name in ('_empty_persistent_rom_state','_empty_persistent_rom_whitelist'):
            first=self.new[name](); second=self.new[name]()
            self.assertEqual(first,self.old[name]())
            first['systems']['changed']=[]
            self.assertEqual(second,{'version':1,'systems':{}})

    def test_save_exact_bytes_and_replacement(self):
        states=[{}, {'version':1,'systems':{'日本語':{'Game.zip':{'blacklisted':True}}},'z':None,'a':2}, {'bad':{1,2}}]
        for state in states:
            for content in (None,b'original'):
                self.compare('save',state=state,content=content)
        result=self.compare('save',state={'z':'日本語','a':1},content=b'original')
        self.assertEqual(result[0],('ok',True))
        self.assertIn(json.dumps({'z':'日本語','a':1},ensure_ascii=False,indent=2,sort_keys=True).replace('\n',os.linesep).encode(),[v for _,v in result[2]])

    def test_save_failures_preserve_original_and_temp_cleanup(self):
        for failure in ('mkdir','write','replace','replace+unlink'):
            for content in (None,b'original'):
                result=self.compare('save',content=content,state={'new':1},failure=failure)
                self.assertEqual(result[0],('ok',False))
                if content is not None: self.assertIn(('state\\list.json',content),result[2])

    def test_seed_only_when_missing_and_preserve_failure_residue(self):
        seeds=[b'{"version":1,"systems":{"MAME":["game.zip"]},"unknown":3}', b'{bad', b'[]', b'\xef\xbb\xbf{}']
        for seed in seeds:
            for content in (None,b'{"systems":{"Existing":[]}}',b'{broken'):
                self.compare('white',content=content,seed=seed)
        for failure in ('mkdir','read','write','replace','replace+unlink'):
            self.compare('white',seed=seeds[0],failure=failure)
        result=self.compare('white',seed=seeds[0],failure='replace')
        self.assertTrue(any('.tmp.' in name for name,_ in result[2]))
        self.assertEqual(result[0],('ok',{'version':1,'systems':{}}))

    def test_read_and_exists_exception_boundaries(self):
        for op in ('load','white'):
            for failure in ('read','exists'):
                result=self.compare(op,content=b'{}',failure=failure)
                self.assertEqual(result[0][0],'error' if failure=='exists' else 'ok')


if __name__=='__main__': unittest.main()
