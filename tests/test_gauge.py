import math
import unittest
from inspection_system.perception.gauge import read_pointer_gauge, GaugeGeometryError

def point(angle_deg, radius=1.0):
    angle = math.radians(angle_deg)
    return (radius * math.cos(angle), radius * math.sin(angle))

class GaugeReaderTests(unittest.TestCase):
    def test_reads_linear_scale_from_keypoints(self):
        center = (0.0, 0.0)
        zero = point(135.0)
        max_tick = point(45.0)  # clockwise 270 degree scale span
        pointer = point(135.0 + (0.86 / 1.6) * 270.0, 0.8)
        result = read_pointer_gauge(center, zero, max_tick, pointer, 0.0, 1.6)
        self.assertAlmostEqual(result.value, 0.86, places=3)
        self.assertTrue(result.in_range)

    def test_invalid_scale_range_raises(self):
        with self.assertRaises(GaugeGeometryError):
            read_pointer_gauge((0, 0), (1, 0), (0, 1), (1, 1), 2.0, 1.0)

if __name__ == "__main__":
    unittest.main()
