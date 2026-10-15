"""Freeze monitor decisions without invoking Windows process termination."""
import copy
import random
import unittest
from runtime_policy import progress_key, tile_hung, tile_exit_status, watchdog_timeout
from tests_fixtures import legacy_monitor_v069 as old


def outcome(fn,*args):
    try: return ('ok',fn(*args))
    except Exception as exc: return ('error',type(exc).__name__,str(exc))


class MonitorCompatibilityTests(unittest.TestCase):
    def test_progress_fields_and_conversion_errors(self):
        base=dict(cycle=1,slot=2,system='PS2',rom='Game',loop_count=3,call_count=4)
        for field in base:
            for value in (None,'','3','bad',0,-1,1.5,False,[],{}):
                snapshot=dict(base,**{field:value})
                original=copy.deepcopy(snapshot)
                self.assertEqual(outcome(progress_key,snapshot,'RUN_ENTER'),outcome(old.progress_key,snapshot,'RUN_ENTER'))
                self.assertEqual(snapshot,original)
        self.assertEqual(progress_key({},'START_ENTER'),('START_ENTER',0,0,'','',0,0))

    def test_progress_reset_and_ignored_fields(self):
        snapshot=dict(cycle=1,slot=2,system='PS2',rom='Game',loop_count=3,call_count=4)
        initial=progress_key(snapshot,'RUN_ENTER')
        self.assertEqual(initial,progress_key(dict(snapshot,raw='new',timestamp=999),'RUN_ENTER'))
        for field in snapshot:
            value=snapshot[field]
            changed=dict(snapshot,**{field:value+1 if isinstance(value,int) else value+'x'})
            self.assertNotEqual(initial,progress_key(changed,'RUN_ENTER'))
        self.assertNotEqual(initial,progress_key(snapshot,'START_ENTER'))

    def test_tile_and_parent_share_default_timeout(self):
        for ready in (True,False):
            record=dict(ready=ready,spawned=0.,progress=30.)
            for now in (0,14.99,15,30,44.99,45,45.01,60):
                self.assertEqual(tile_hung(record,{},now),old.tile_hung(record,{},now))
        self.assertFalse(tile_hung(dict(ready=True,spawned=0,progress=0),{},14.99))
        self.assertTrue(tile_hung(dict(ready=True,spawned=0,progress=0),{},15))
        self.assertFalse(tile_hung(dict(ready=False,spawned=0,progress=0),{},44.99))
        self.assertTrue(tile_hung(dict(ready=False,spawned=0,progress=0),{},45))
        self.assertEqual(watchdog_timeout('RUN_ENTER',{}),15)
        self.assertIsNone(watchdog_timeout('SLOT_POWER_IDLE',{}))

    def test_parent_and_tile_explicit_timeout_boundaries_match(self):
        for cfg in ({},{'worker_run_hang_timeout_seconds':2,'worker_start_hang_timeout_seconds':1},
                    {'worker_run_hang_timeout_seconds':30,'worker_start_hang_timeout_seconds':80}):
            for ready,phase in ((True,'RUN_ENTER'),(False,'START_ENTER')):
                limit=watchdog_timeout(phase,cfg)
                record=dict(ready=ready,progress=0,spawned=0)
                self.assertFalse(tile_hung(record,cfg,limit-.001))
                self.assertTrue(tile_hung(record,cfg,limit))

    def test_tile_invalid_config_evaluation_order(self):
        values=[None,'bad','',0,-1,'2',2.5,float('inf'),float('nan')]
        for run in values:
            for start in values:
                for record in ({},dict(ready=True,progress=0),dict(ready=False,spawned=0)):
                    cfg=dict(worker_run_hang_timeout_seconds=run,worker_start_hang_timeout_seconds=start)
                    self.assertEqual(outcome(tile_hung,record,cfg,50),outcome(old.tile_hung,record,cfg,50))
        # Both timeouts are parsed before readiness is inspected, even if unused.
        result=outcome(tile_hung,dict(ready=True,progress=0),dict(worker_start_hang_timeout_seconds='bad'),50)
        self.assertEqual(result[1],'ValueError')

    def test_exit_code_and_phase_are_both_required(self):
        for code in (0,75,76,1,-1073741819,0xC0000005,None,'75'):
            for phase in ('SLOT_USER_EXIT','SLOT_COMPLETE','SLOT_RUNNING','',None,' SLOT_COMPLETE '):
                self.assertEqual(tile_exit_status(code,phase,75),old.tile_exit_status(code,phase,75))
        self.assertEqual(tile_exit_status(0,'SLOT_USER_EXIT',75),'user_exit')
        self.assertEqual(tile_exit_status(75,'SLOT_COMPLETE',75),'complete')
        self.assertEqual(tile_exit_status(75,'SLOT_RUNNING',75),'failure')
        self.assertEqual(tile_exit_status(0,'SLOT_COMPLETE',75),'failure')

    def test_generated_clock_and_readiness_cases(self):
        rng=random.Random(70)
        for _ in range(1000):
            record=dict(ready=rng.choice([True,False,0,1]),spawned=rng.uniform(-10,100),progress=rng.uniform(-10,100))
            cfg=dict(worker_run_hang_timeout_seconds=rng.uniform(-5,100),worker_start_hang_timeout_seconds=rng.uniform(-5,100))
            now=rng.uniform(-10,200)
            before=copy.deepcopy((record,cfg))
            self.assertEqual(tile_hung(record,cfg,now),old.tile_hung(record,cfg,now))
            self.assertEqual((record,cfg),before)


if __name__=='__main__': unittest.main()
