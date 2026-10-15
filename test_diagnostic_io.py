import contextlib
import ast
import datetime
import io
import random
import mmap
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import diagnostic_io as current
from tests_fixtures import legacy_diagnostics_v083 as old


class Clock:
    @staticmethod
    def now(*args): return datetime.datetime(2026,10,9,12,34,56,123456)


class Buffer(io.BytesIO):
    def __init__(self, data=b'', failure=None):
        super().__init__(data); self.events=[]; self.failure=failure
    def seek(self, offset, *args):
        self.events.append(('seek',offset))
        if self.failure=='seek': raise OSError('seek blocked')
        return super().seek(offset,*args)
    def read(self, size=-1):
        self.events.append(('read',size))
        if self.failure=='read': raise OSError('read blocked')
        return super().read(size)
    def write(self, data):
        self.events.append(('write',data))
        if self.failure=='write': raise OSError('write blocked')
        return super().write(data)


def outcome(fn,*args):
    try:return ('ok',fn(*args))
    except Exception as exc:return ('error',type(exc).__name__,str(exc))


class TraceCompatibilityTests(unittest.TestCase):
    def write_compare(self,args, failure=None, absent=False):
        results=[]
        for module in (old,current):
            buffer=None if absent else Buffer(b'old data\0tail',failure)
            if module is old:
                module._RUNTIME_TRACE_MAP=buffer
                result=outcome(module.write_runtime_trace,*args)
            else: result=outcome(module.write_runtime_trace,buffer,*args)
            results.append((result,None if absent else buffer.getvalue(),None if absent else buffer.events))
        self.assertEqual(*results)
        return results[1]

    def test_trace_fields_encoding_and_numeric_conversions(self):
        for args in [('RUN_ENTER',),('P\t\r\n',2,3,'機種','rom\t名',4,5),
                     (None,True,False,None,0,'2',3.9),('x','bad'),('x',None),('x',float('inf'))]:
            self.write_compare(args)

    def test_byte_boundaries_multibyte_and_surrogates(self):
        for text in ('a'*8190,'a'*8191,'a'*8192,'あ'*3000,'\ud800','\x00embedded'):
            result=self.write_compare((text,))
            self.assertLessEqual(len(result[2][-2][1]),8191)
            self.assertEqual(result[2][-1],('write',b'\0'))

    def test_absent_mapping_and_write_failures(self):
        self.write_compare(('x','bad'),absent=True)
        for failure in ('seek','write'):
            self.write_compare(('x',1),failure)

    def test_read_malformed_partial_and_extra_fields(self):
        cases=[b'',b'\0tail',b'P',b'P\tbad\t2',b'P\t1\t2\ts\tr\t3\t4\textra',
               b'\xff\t\xfe',b'a'*9000,b'P\t1\t2\ts\tr\t3\t4\0stale']
        for data in cases:
            a=Buffer(data); b=Buffer(data)
            self.assertEqual(outcome(old.read_runtime_trace,a),outcome(current.read_runtime_trace,b))
            self.assertEqual(a.events,b.events)

    def test_generated_read_records(self):
        rng=random.Random(84)
        for _ in range(500):
            data=bytes(rng.randrange(256) for _ in range(rng.randrange(250)))
            self.assertEqual(outcome(old.read_runtime_trace,Buffer(data)),outcome(current.read_runtime_trace,Buffer(data)))

    def test_read_error_and_snapshot_logs(self):
        for data,failure in ((b'',None),(b'RUN\t1\t2\tSYS\tROM\t3\t4',None),(b'P','seek'),(b'P','read')):
            results=[]
            for module in (old,current):
                log=io.StringIO(); buffer=Buffer(data,failure)
                with contextlib.redirect_stdout(log): value=module.log_runtime_trace_snapshot(buffer,42,'exit')
                results.append((value,log.getvalue(),buffer.events))
            self.assertEqual(*results)
        self.assertIsNone(current.read_runtime_trace(None))

    def test_round_trip_latest_record_ignores_stale_tail(self):
        mm=Buffer(b'long old record'*100)
        current.write_runtime_trace(mm,'RUN',2,3,'機種','ROM',4,5)
        record=current.read_runtime_trace(mm)
        self.assertEqual((record['phase'],record['system'],record['call_count']),('RUN','機種',5))
        self.assertEqual(record['raw'],'RUN\t2\t3\t機種\tROM\t4\t5')

    def test_native_wrapper_uses_current_mapping(self):
        source=Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8')
        names={'write_runtime_trace','read_runtime_trace','log_runtime_trace_snapshot'}
        nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in names]
        ns={'_RUNTIME_TRACE_MAP':None}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<trace wrappers>','exec'),ns)
        ns['write_runtime_trace']('NO_MAP','bad')
        for phase in ('FIRST','SECOND'):
            mm=Buffer(); ns['_RUNTIME_TRACE_MAP']=mm
            ns['write_runtime_trace'](phase,slot=2)
            self.assertEqual(ns['read_runtime_trace'](mm)['phase'],phase)

    def test_real_anonymous_mapping_bytes_and_readback(self):
        results=[]
        for module in (old,current):
            with mmap.mmap(-1,8192) as mm:
                if module is old:
                    with patch.object(old,'_RUNTIME_TRACE_MAP',mm):old.write_runtime_trace('RUN',3,2,'機種','ROM',4,5)
                else:current.write_runtime_trace(mm,'RUN',3,2,'機種','ROM',4,5)
                results.append((bytes(mm[:]),module.read_runtime_trace(mm)))
        self.assertEqual(*results)


class StreamCompatibilityTests(unittest.TestCase):
    def run_stream(self,module,argv,pieces,broken=False,original=True):
        events=[]
        class Sink:
            encoding='cp932'
            def __init__(self,name): self.name=name
            def write(self,value):
                events.append((self.name,'write',value))
                if broken:raise OSError('sink failed')
            def flush(self):
                events.append((self.name,'flush'))
                if broken:raise OSError('flush failed')
            def isatty(self):
                if broken:raise OSError('isatty failed')
                return True
        with patch.object(module,'datetime',SimpleNamespace(datetime=Clock)),patch.object(module.os,'getpid',return_value=123),patch.object(module.sys,'argv',['saver']+argv):
            stream=module._DiagnosticStream(Sink('console') if original else None,Sink('file'),'OUT')
            values=[outcome(stream.write,p) for p in pieces]
            stream.flush()
            return values,events,stream._line_start,stream.isatty(),stream.encoding

    def test_chunked_lines_role_precedence_and_unicode(self):
        roles=['--supervisor-guard','--slot-worker','--worker']
        pieces=[None,'','first',' continued\nnext\r','\n','日本語\n',0,'x\vY\n']
        for argv in [[],*[[r] for r in roles],roles,list(reversed(roles))]:
            self.assertEqual(self.run_stream(old,argv,pieces),self.run_stream(current,argv,pieces))

    def test_sink_failures_and_windowed_stream(self):
        for broken in (False,True):
            for original in (False,True):
                self.assertEqual(self.run_stream(old,[],['a\nb','c\n'],broken,original),
                                 self.run_stream(current,[],['a\nb','c\n'],broken,original))

    def test_generated_write_chunks(self):
        rng=random.Random(840)
        for _ in range(100):
            pieces=[''.join(rng.choice('abcあ\r\n\t') for _ in range(rng.randrange(20))) for _ in range(10)]
            self.assertEqual(self.run_stream(old,['--worker'],pieces),self.run_stream(current,['--worker'],pieces))
