"""Optional machine timings must not change existing global or catalog behavior."""
import contextlib
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

from fixed_rom_catalog import signature
from independent_slots import duration_seconds
from system_config import read_system_config


class SystemCycleDurationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(cycle_seconds=180, independent_jitter_seconds=15)

    def test_unconfigured_machine_preserves_draws_and_random_state(self):
        left, right = random.Random(42), random.Random(42)
        expected = [duration_seconds(self.cfg, left) for _ in range(100)]
        actual = [duration_seconds(self.cfg, right, system={'id':'ps1'}) for _ in range(100)]
        self.assertEqual(actual, expected)
        self.assertEqual(left.getstate(), right.getstate())

    def test_per_machine_center_inherits_global_jitter(self):
        rng = random.Random(11)
        values = [duration_seconds(self.cfg, rng, system={'cycle_seconds':300}) for _ in range(100)]
        self.assertTrue(all(285 <= x <= 315 for x in values))
        self.assertGreater(len(set(values)), 90)

    def test_optional_jitter_inherits_center_and_zero_disables_variation(self):
        self.assertEqual(duration_seconds(self.cfg, system={'independent_jitter_seconds':0}),180)
        for center in (300,360):
            self.assertEqual(duration_seconds(self.cfg, system={
                'cycle_seconds':center,'independent_jitter_seconds':0}),center)

    def test_existing_minimum_applies_after_machine_override(self):
        for center in (.1,1,5):
            self.assertEqual(duration_seconds(self.cfg, system={
                'cycle_seconds':center,'independent_jitter_seconds':0}),5)
        values=[duration_seconds(self.cfg, random.Random(i), system={
            'cycle_seconds':20,'independent_jitter_seconds':60}) for i in range(100)]
        self.assertTrue(all(5 <= x <= 80 for x in values))

    def test_bad_machine_values_fall_back_per_key_with_identifiable_warning(self):
        invalid=[None,True,False,[],{},'bad',float('nan'),float('inf'),-float('inf'),10**1000,-1]
        for key in ('cycle_seconds','independent_jitter_seconds'):
            for value in invalid+([0] if key=='cycle_seconds' else []):
                with self.subTest(key=key,value=str(value)[:20]):
                    system={'id':'ps1',key:value}
                    log=io.StringIO()
                    with contextlib.redirect_stdout(log):
                        actual=duration_seconds(self.cfg,random.Random(10),system=system)
                    self.assertEqual(actual,duration_seconds(self.cfg,random.Random(10)))
                    self.assertIn(f'[ps1] invalid {key}=',log.getvalue())
                    self.assertIn('using global value',log.getvalue())

    def test_bad_one_key_does_not_discard_other_machine_key(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(duration_seconds(self.cfg,system={
                'cycle_seconds':None,'independent_jitter_seconds':0}),180)
            value=duration_seconds(self.cfg,system={
                'cycle_seconds':300,'independent_jitter_seconds':None})
        self.assertTrue(285 <= value <= 315)

    def test_command_line_duration_remains_an_explicit_override(self):
        cfg=dict(self.cfg,cycle_seconds=60,_cycle_seconds_override=True)
        self.assertEqual(duration_seconds(cfg,system={
            'cycle_seconds':300,'independent_jitter_seconds':0}),60)

    def test_system_file_round_trip_does_not_require_rom_catalog_refresh(self):
        system={'id':'ps1','rom_dir':'C:/ROMs/psx','extensions':['.chd']}
        original_signature=signature(system)
        system.update(cycle_seconds=300,independent_jitter_seconds=0)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ps1.json'
            path.write_text(json.dumps(system),encoding='utf-8')
            loaded=read_system_config(path)
        before_cfg,before_system=copy.deepcopy(self.cfg),copy.deepcopy(loaded)
        self.assertEqual(duration_seconds(self.cfg,system=loaded),300)
        self.assertEqual(signature(loaded),original_signature)
        self.assertEqual(self.cfg,before_cfg)
        self.assertEqual(loaded,before_system)


if __name__ == '__main__':
    unittest.main()
