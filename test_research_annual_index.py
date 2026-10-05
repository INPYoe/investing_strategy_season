import unittest
from datetime import date
from research_annual_index import point


class AnnualIndexTests(unittest.TestCase):
    def test_normalized_price_and_display_date_use_same_position(self):
        dates=[date(2025,1,d) for d in (2,3,6,7)]
        prices=dict(zip(dates,(10,20,30,40)))
        day,price=point(prices,dates,2025,1,'normalized',size=3)
        self.assertEqual(price,25)
        self.assertEqual(day,date(2025,1,5))
        self.assertEqual(point(prices,dates,2025,1,'ordinal'),(date(2025,1,3),20))

    def test_unobserved_current_year_point_is_not_an_extra_sample(self):
        dates=[date(2025,1,d) for d in (2,3,6)]
        prices={dates[0]:10,dates[1]:20}
        self.assertIsNone(point(prices,dates,2025,2,'ordinal'))
