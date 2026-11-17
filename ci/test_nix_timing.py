"""Parallel Nix activities must count wall intervals once."""
import unittest
from nix_setup import union_seconds


class ActivityTiming(unittest.TestCase):
    def test_overlapping_and_nested_parallel_activities(self):
        self.assertEqual(union_seconds([(2, 6), (0, 4), (1, 3), (8, 9)]), 7)

    def test_no_activities_means_no_measured_activity(self):
        self.assertEqual(union_seconds([]), 0)


if __name__ == "__main__":
    unittest.main()
