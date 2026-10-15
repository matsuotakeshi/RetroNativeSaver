import random
from types import SimpleNamespace
import unittest
import runtime_policy as current
from tests_fixtures import legacy_timing_v079 as old


def outcome(fn, *args):
    try:
        return ('ok', fn(*args))
    except Exception as exc:
        return ('error', type(exc).__name__, str(exc))


def avs(values):
    return [SimpleNamespace(timing=SimpleNamespace(fps=value)) for value in values]


class CycleTimingTests(unittest.TestCase):
    def compare(self, name, *args):
        result = outcome(getattr(current, name), *args)
        self.assertEqual(result, outcome(getattr(old, name), *args))
        return result

    def test_rate_boundaries_and_fallback(self):
        cases = [[], [0], [1], [1.0001], [240], [240.001], [50, 60],
                 [float('nan'), float('inf'), -float('inf')], ['59.94'], [True]]
        for values in cases:
            self.compare('cycle_frame_timing', avs(values))
        self.assertEqual(current.cycle_frame_timing(avs([1, 241])), (60.0, 1/60.0))
        self.assertEqual(current.cycle_frame_timing(avs([50, 59.94])), (59.94, 1/59.94))

    def test_conversion_errors_and_missing_attributes(self):
        for values in ([None], ['bad'], [60, object()]):
            self.compare('cycle_frame_timing', avs(values))
        for values in ([None], [SimpleNamespace()], [SimpleNamespace(timing=None)]):
            self.compare('cycle_frame_timing', values)

    def test_timing_read_order_and_error_stop(self):
        outcomes = []
        for module in (old, current):
            events = []
            class Timing:
                def __init__(self, value): self.value = value
                @property
                def fps(self):
                    events.append(self.value)
                    if self.value == 'bad': raise ValueError('bad fps')
                    return self.value
            values = [SimpleNamespace(timing=Timing(v)) for v in (50, 'bad', 60)]
            outcomes.append((outcome(module.cycle_frame_timing, values), events))
        self.assertEqual(*outcomes)
        self.assertEqual(outcomes[1][1], [50, 'bad'])

    def test_fade_endpoints_disabled_and_overlap(self):
        for elapsed in (-1, 0, .4, .8, 1, 179.2, 179.6, 180, 181):
            for enabled in (False, True):
                self.compare('cycle_fade_alpha', elapsed, True, .8, enabled, 180)
        self.assertEqual(current.cycle_fade_alpha(0, True, .8, True, 180), 255)
        self.assertEqual(current.cycle_fade_alpha(90, True, .8, True, 180), 0)
        self.assertEqual(current.cycle_fade_alpha(180, True, .8, True, 180), 255)
        for duration in (-1, 0, .8, 4):
            for elapsed in (0, .2, .5, 1, 2):
                self.compare('cycle_fade_alpha', elapsed, True, duration, True, 1)
                self.compare('cycle_fade_alpha', elapsed, False, duration, True, 1)

    def test_nonfinite_and_invalid_fade_values(self):
        for value in (float('nan'), float('inf'), -float('inf'), None, 'bad'):
            for index in (0, 2, 4):
                args = [0.2, True, .8, True, 180]
                args[index] = value
                self.compare('cycle_fade_alpha', *args)
        # Disabled fading must not evaluate unrelated invalid arguments.
        self.assertEqual(current.cycle_fade_alpha(None, False, None, True, None), 0)

    def test_generated_fade_and_rate_cases(self):
        rng = random.Random(80)
        for _ in range(1000):
            self.compare('cycle_frame_timing', avs([rng.uniform(-5, 250) for _ in range(rng.randrange(8))]))
            self.compare('cycle_fade_alpha', rng.uniform(-2, 200), rng.choice([True,False]),
                         rng.uniform(-1, 10), rng.choice([True,False]), rng.uniform(0, 200))
