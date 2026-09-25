from __future__ import annotations

import unittest

from mchose_tray import battery_color, make_icon


class TrayHelpersTests(unittest.TestCase):
    def test_battery_color_thresholds(self) -> None:
        self.assertEqual(battery_color(20), (239, 68, 68))
        self.assertEqual(battery_color(21), (245, 158, 11))
        self.assertEqual(battery_color(50), (245, 158, 11))
        self.assertEqual(battery_color(51), (34, 197, 94))

    def test_icon_dimensions(self) -> None:
        self.assertEqual(make_icon("100", (34, 197, 94)).size, (64, 64))


if __name__ == "__main__":
    unittest.main()
