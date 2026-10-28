"""Drive the actual scheduler with controlled child processes, no native cores."""
import contextlib
import io
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import independent_slots as scheduler


class ParallelStartupTests(unittest.TestCase):
    def run_case(self, limit=None, mode='waiting', heavy=False, system_timing=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);events=[];procs=[];traces=[];starts=[];clock=[0.]
            class Window:
                hwnd=123;fullscreen=True;should_close=False;exit_reason='test';power_idle=False;pumps=0
                def pump(self):
                    self.pumps+=1
                    if mode.startswith('reselect') and self.pumps==3:self.saver_controls.key(0x26)
                    if mode=='standby' and self.pumps==3:self.power_idle=True
                    if self.pumps>=(12 if mode in ('resize','resize_group') else 8):self.should_close=True
                def present(self):pass
                def begin_composite(self):pass
                def _note_exit(self,*a):events.append(('user_exit',))
            win=Window()
            if mode in ('resize','resize_group'):
                class Layout:
                    def take(self,now):
                        count={3:6,8:2}.get(win.pumps)
                        if count is not None:
                            events.append(('layout',count))
                            return [(i*20,0,20,20) for i in range(count)]
                win.tile_layout=Layout()
            class Trace:
                def __init__(self):self.number=len(traces);self.closed=False;traces.append(self)
                def close(self):self.closed=True;events.append(('trace_close',self.number))
            class Proc:
                def __init__(self,index):
                    self.index=index;self.pid=100+len(procs);self.code=None;self.ready=False
                    self.born=win.pumps;procs.append(self)
                def poll(self):
                    if self.code is None and self.index==0 and win.pumps>=3:
                        if mode=='crash':self.code=scheduler.FAILED
                        if mode=='user':self.code=0
                        if mode=='complete':self.code=scheduler.COMPLETE
                    return self.code
                def kill(self):self.code=-1;events.append(('kill',self.pid))
                def wait(self,timeout):
                    events.append(('wait',self.pid))
                    if mode=='reselect_cleanup_failure':raise TimeoutError('child still alive')
                    return self.code
            def popen(cmd,env):
                index=int(Path(cmd[-1]).stem)
                if mode=='popen_error' and index==1:raise OSError('test spawn error')
                proc=Proc(index);starts.append((win.pumps,index))
                pending=sum(p.code is None and not p.ready for p in procs)
                events.append(('spawn',index,pending))
                return proc
            def prepare(api,window,rects,cfg,titles,folder,index,pick,duration,tag):
                content=root/f'content_{index}';content.mkdir(exist_ok=True)
                spec=root/f'{index}.json';spec.write_text('{}')
                gate=root/f'gate_{index}'
                if gate.exists():gate.unlink()
                events.append(('pick',index,pick[0]['id']))
                events.append(('duration',index,pick[0]['id'],duration))
                return gate,spec,content,{},['fake.exe']
            def assign(job,proc):
                self.assertFalse((root/f'gate_{proc.index}').exists())
                events.append(('assign',proc.pid))
                return not (mode=='assign_error' and proc.index==1)
            def close_job(job):
                events.append(('job_close',))
                for proc in procs:
                    if proc.code is None:proc.code=-1
                return True
            def read(trace):
                proc=procs[trace.number]
                self.assertTrue((root/f'gate_{proc.index}').exists())
                proc.ready=(mode in ('advance','mixed') and proc.index!=0) or mode in ('resize','resize_group')
                phase='SLOT_RUNNING' if proc.ready else 'WAIT_FRAME'
                if mode=='user' and proc.index==0 and win.pumps>=3:phase='SLOT_USER_EXIT'
                if mode=='complete' and proc.index==0 and win.pumps>=3:phase='SLOT_COMPLETE'
                return {'phase':phase,'raw':f'{phase}:{win.pumps}'}
            def tick():clock[0]+=.001;return clock[0]
            system=dict(id='a',name='A',max_concurrent=4)
            if system_timing is not None:system.update(system_timing)
            if heavy or mode=='mixed':system.update(resource_group='heavy_cd',resource_weight=1)
            systems=[system];catalogs={'a':[Path(f'a{i}.rom') for i in range(8)]}
            if mode=='mixed':
                systems.append(dict(id='light',name='Light',max_concurrent=4))
                catalogs['light']=[Path(f'l{i}.rom') for i in range(8)]
            cfg={'persistent_rom_blacklist_enabled':False,'resource_groups':{'heavy_cd':{'max_weight':1}}}
            if mode=='resize_group':cfg['_single_system_rendering']=True
            if mode.startswith('reselect'):cfg.update(saver_controls_enabled=True,independent_slots_enabled=True)
            if system_timing is not None:cfg.update(cycle_seconds=180,independent_jitter_seconds=0)
            if limit is not None:cfg['independent_startup_parallelism']=limit
            api=SimpleNamespace(RUNTIME_TRACE_SIZE=4096,_create_worker_job_object=lambda:9,
                _assign_worker_to_job=assign,kernel32=SimpleNamespace(CloseHandle=close_job),
                write_runtime_trace=lambda *a,**k:events.append(('runtime',a)),read_runtime_trace=read,
                resolve_app_relative_path=lambda value,default:root/default)
            original=scheduler.select_slot;rng=random.Random(110)
            def select(*a,**kw):return original(*a,**kw,rng=rng)
            error=None
            import presentation_restart as restart
            if mode.startswith('reselect'):
                restart.write_state(root,{('a','bad.rom')},{'Other'},{'Other':2},pid=0)
            with patch.multiple(scheduler,
                mmap=SimpleNamespace(mmap=lambda *a,**k:Trace()),
                subprocess=SimpleNamespace(Popen=popen),
                time=SimpleNamespace(monotonic=tick,monotonic_ns=lambda:int(tick()*1e9),sleep=lambda x:None),
                select_slot=select,_prepare_slot_launch=prepare,
                _load_scheduler_state=lambda *a:(root/'black.json',{}, {},catalogs),
                _refresh_scheduler_favorites=lambda *a:(1,[(a[3][0],catalogs['a'][0])])), \
                patch('worker_workspace.worker_temp_parent',return_value=str(root) if mode.startswith('reselect') else None), \
                (patch.object(restart,'write_state',side_effect=OSError('write failed')) if mode=='reselect_failure' else contextlib.nullcontext()),contextlib.redirect_stdout(io.StringIO()):
                try:
                    code=scheduler.run_scheduler(api,win,[(0,0,20,20)]*4,systems,catalogs,cfg,root/'favorites.json',{})
                    events.append(('return',code))
                    if code==restart.RESELECT:
                        events.append(('safety',restart.read_state(root,scheduler.os.getpid())))
                except Exception as exc:error=exc
            self.assertTrue(all(p.code is not None for p in procs))
            if mode!='reselect_cleanup_failure':self.assertTrue(all(t.closed for t in traces))
            self.assertEqual(sum(e[0]=='job_close' for e in events),1)
            self.assertTrue(all(e[2]<=scheduler.startup_parallelism(cfg) for e in events if e[0]=='spawn'))
            return starts,events,error

    def test_up_cleans_loading_tiles_and_returns_request_without_refill(self):
        starts,events,error=self.run_case(mode='reselect')
        self.assertIsNone(error);self.assertEqual([i for _,i in starts],[0,1])
        self.assertIn(('return',77),events)
        self.assertEqual(events[-1],('safety',({('a','bad.rom')},{'Other'},{'Other':2})))
        self.assertLess(events.index(('job_close',)),events.index(('return',77)))

    def test_up_write_or_cleanup_failure_does_not_report_success(self):
        for mode in ('reselect_failure','reselect_cleanup_failure'):
            starts,events,error=self.run_case(mode=mode)
            self.assertIsNotNone(error);self.assertNotIn(('return',77),events)
            self.assertEqual([i for _,i in starts],[0,1])

    def test_live_resize_keeps_existing_children_and_resource_caps(self):
        for mode,expected in (('resize',4),('resize_group',6)):
            starts,events,error=self.run_case(mode=mode)
            self.assertIsNone(error)
            self.assertEqual([i for _,i in starts],list(range(expected)))
            shrink=events.index(('layout',2));closed=events.index(('job_close',))
            early_kills=[e[1] for e in events[shrink:closed] if e[0]=='kill']
            self.assertEqual(early_kills,list(reversed(range(102,100+expected))))
            self.assertNotIn(100,early_kills);self.assertNotIn(101,early_kills)

    def test_default_two_waiting_children_and_serial_one(self):
        starts,_,error=self.run_case();self.assertIsNone(error)
        self.assertEqual([i for _,i in starts],[0,1])
        starts,_,error=self.run_case(limit=1);self.assertIsNone(error)
        self.assertEqual([i for _,i in starts],[0])

    def test_slow_first_tile_does_not_block_other_ready_tiles(self):
        starts,_,error=self.run_case(mode='advance');self.assertIsNone(error)
        self.assertEqual([i for _,i in starts],[0,1,2,3])

    def test_loading_heavy_tile_reserves_its_weight(self):
        starts,_,error=self.run_case(heavy=True);self.assertIsNone(error)
        self.assertEqual([i for _,i in starts],[0])
        starts,events,error=self.run_case(mode='mixed');self.assertIsNone(error)
        self.assertEqual([e[2] for e in events if e[0]=='pick'],['a','light','light','light'])

    def test_crash_and_completion_release_startup_capacity(self):
        for mode in ('crash','complete'):
            starts,_,error=self.run_case(mode=mode);self.assertIsNone(error)
            self.assertEqual([i for _,i in starts][:3],[0,1,0])

    def test_user_exit_and_standby_stop_both_children(self):
        for mode in ('user','standby'):
            starts,_,error=self.run_case(mode=mode);self.assertIsNone(error)
            self.assertEqual([i for _,i in starts],[0,1])

    def test_second_child_launch_failure_cleans_up_first(self):
        for mode in ('assign_error','popen_error'):
            _,_,error=self.run_case(mode=mode)
            self.assertIsNotNone(error)

    def test_configuration_is_bounded(self):
        self.assertEqual(scheduler.startup_parallelism({}),2)
        for value,expected in ((1,1),('1',1),(2,2),(100,2),(0,1),(-1,1),('bad',2),(None,2),(float('inf'),2)):
            self.assertEqual(scheduler.startup_parallelism({'independent_startup_parallelism':value}),expected)

    def test_machine_duration_reaches_favorite_ordinary_and_replacement_tiles(self):
        for mode in ('waiting','complete'):
            with self.subTest(mode=mode):
                _,events,error=self.run_case(mode=mode,system_timing={'cycle_seconds':300})
                self.assertIsNone(error)
                durations=[e for e in events if e[0]=='duration']
                self.assertEqual([e[1] for e in durations][:2],[0,1])
                if mode=='complete':self.assertGreater(len(durations),2)
                self.assertTrue(all(e[3]==300 for e in durations))

    def test_unspecified_machine_inherits_global_duration_alongside_overridden_machine(self):
        _,events,error=self.run_case(mode='mixed',system_timing={'cycle_seconds':360})
        self.assertIsNone(error)
        self.assertEqual([(e[2],e[3]) for e in events if e[0]=='duration'],
                         [('a',360),('light',180),('light',180),('light',180)])


if __name__=='__main__':unittest.main()
