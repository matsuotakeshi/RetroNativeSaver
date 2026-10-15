import random
from pathlib import Path
import unittest
from independent_slots import duration_seconds, fade_alpha, select_slot


class IndependentTests(unittest.TestCase):
    def setUp(self):
        self.a = dict(id='a', name='A', max_concurrent=1, resource_group='heavy_cd', resource_weight=2)
        self.b = dict(id='b', name='B', max_concurrent=2, resource_group='heavy_cd', resource_weight=1)
        self.c = dict(id='c', name='C', max_concurrent=8)
        self.systems = [self.a, self.b, self.c]
        self.catalogs = {s['id']: [Path(s['id'] + '1.zip'), Path(s['id'] + '2.zip')] for s in self.systems}
        self.cfg = {'resource_groups': {'heavy_cd': {'max_weight': 3}}}

    def choose(self, index, occupied=(), banned=frozenset(), suspended=frozenset()):
        return select_slot(index, self.systems, self.catalogs, self.cfg, occupied,
                           [(self.a, Path('a1.zip'))], banned, suspended, random.Random(2))

    def test_per_tile_duration_is_bounded_and_varied(self):
        rng = random.Random(12)
        values = [duration_seconds(dict(cycle_seconds=180, independent_jitter_seconds=60), rng) for _ in range(100)]
        self.assertTrue(all(120 <= x <= 240 for x in values))
        self.assertGreater(len(set(values)), 90)
        self.assertEqual(duration_seconds(dict(cycle_seconds=180, independent_jitter_seconds=0)), 180)
        self.assertEqual(duration_seconds(dict(cycle_seconds=-10, independent_jitter_seconds=1)), 5)
        with self.assertRaises(ValueError):
            duration_seconds(dict(cycle_seconds=float('nan')))

    def test_fade_at_start_middle_end(self):
        self.assertEqual(fade_alpha(0, 180, .8), 255)
        self.assertEqual(fade_alpha(90, 180, .8), 0)
        self.assertEqual(fade_alpha(180, 180, .8), 255)
        self.assertEqual(fade_alpha(200, 180, .8), 255)
        self.assertEqual(fade_alpha(180, 180, 0), 0)
        self.assertAlmostEqual(fade_alpha(179.6, 180, .8), 128, delta=1)

    def test_top_left_prefers_favorite_and_reserves_weight(self):
        first = self.choose(0)
        self.assertEqual(first, (self.a, Path('a1.zip')))
        second = self.choose(1, [first])
        self.assertNotEqual(second[0]['id'], 'a')
        occupied = [first, (self.b, Path('b1.zip'))]
        self.assertEqual(self.choose(2, occupied)[0]['id'], 'c')

    def test_replacement_counts_other_loading_and_running_slots(self):
        occupied = [(self.b, Path('b1.zip')), (self.b, Path('b2.zip'))]
        self.assertIsNone(self.choose(0, occupied))
        self.assertEqual(self.choose(0, occupied[:1])[0]['id'], 'a')

    def test_failed_rom_and_suspended_system_stay_excluded(self):
        pick = self.choose(0, banned={('a', 'a1.zip')})
        self.assertNotEqual(pick, (self.a, Path('a1.zip')))
        self.assertNotEqual(self.choose(0, suspended={'A'})[0]['id'], 'a')

    def test_no_capacity_returns_empty_without_oversubscription(self):
        for system in self.systems:
            system['max_concurrent'] = 0
        self.assertIsNone(self.choose(0))

    def test_random_replacements_keep_global_budgets(self):
        rng = random.Random(7)
        slots = [None] * 6
        for _ in range(200):
            index = rng.randrange(len(slots))
            slots[index] = None
            slots[index] = select_slot(index, self.systems, self.catalogs, self.cfg,
                [s for s in slots if s], [(self.a, Path('a1.zip'))], set(), set(), rng)
            occupied = [s for s in slots if s]
            self.assertLessEqual(sum(s.get('resource_weight', 0) for s, _ in occupied), 3)
            self.assertLessEqual(sum(s['id'] == 'a' for s, _ in occupied), 1)
            self.assertLessEqual(sum(s['id'] == 'b' for s, _ in occupied), 2)


if __name__ == '__main__':
    unittest.main()
