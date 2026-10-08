import unittest
from datetime import date
from ariadne import week_name


class WeekTests(unittest.TestCase):
    def test_iso_year_boundary(self):
        self.assertEqual(week_name(date(2021, 1, 1)), '2020_W53')
        self.assertEqual(week_name(date(2026, 9, 30)), '2026_W40')
