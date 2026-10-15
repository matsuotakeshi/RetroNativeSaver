import unittest
from startup_input import StartTwice


class StartupInputTests(unittest.TestCase):
    def test_two_presses_at_one_second_intervals(self):
        inputs=StartTwice()
        for now,down in [(10,False),(14.99,False),(15,True),(15.05,True),
                         (15.11,False),(15.99,False),(16,True),(16.11,False),(99,False)]:
            inputs.advance(now)
            self.assertEqual(inputs.state(0,1,0,3),int(down))
            self.assertEqual(inputs.state(0,1,0,256),8 if down else 0)
        self.assertEqual(inputs.count,2)

    def test_stalled_worker_still_releases_between_presses(self):
        inputs=StartTwice()
        for now,down in [(0,False),(10,True),(20,False),(21,True),(22,False),(23,False)]:
            inputs.advance(now)
            self.assertEqual(inputs.down,down)
        self.assertEqual(inputs.count,2)

    def test_no_input_to_other_buttons_devices_or_ports(self):
        inputs=StartTwice(); inputs.advance(0); inputs.advance(5)
        for args in [(1,1,0,3),(0,3,0,3),(0,1,1,3),(0,1,0,0),(0,1,0,8)]:
            self.assertEqual(inputs.state(*args),0)
        self.assertEqual(StartTwice().state(0,1,0,3),0)

    def test_late_first_press_keeps_one_second_gap(self):
        inputs=StartTwice()
        for now,down in [(0,False),(5.5,True),(5.7,False),(6,False),(6.5,True),(6.7,False)]:
            inputs.advance(now)
            self.assertEqual(inputs.down,down)
        self.assertEqual(inputs.count,2)
