import unittest
from inspection_system.models import Severity
from inspection_system.perception.thermal import analyze_temperature_matrix

class ThermalAnalyzerTests(unittest.TestCase):
    def test_extracts_and_ranks_hotspots(self):
        matrix = [
            [25, 25, 25, 25],
            [25, 61, 62, 25],
            [25, 25, 25, 25],
            [25, 25, 25, 58],
        ]
        results = analyze_temperature_matrix(matrix, ambient_temp_c=25, min_area_px=1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].max_temp_c, 62)
        self.assertEqual(results[0].severity, Severity.CRITICAL)
        self.assertEqual(results[1].severity, Severity.WARNING)

    def test_rejects_ragged_matrix(self):
        with self.assertRaises(ValueError):
            analyze_temperature_matrix([[1, 2], [3]], ambient_temp_c=20)

if __name__ == "__main__":
    unittest.main()
