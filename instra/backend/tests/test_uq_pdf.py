import unittest

from export.uq_pdf import _option_items, _report_pairs


ELEMENTS = {"ca": "Ca", "cl": "Cl"}
OXIDES = {
    "cao": {
        "formula": "CaO",
        "element": "Ca",
        "factor": 1.4,
        "conventional": True,
    },
}


class TestUqPdfOptions(unittest.TestCase):
    def test_only_chinese_option_whitelist_is_shown(self):
        rows = _option_items({
            "chemistry": 1,
            "atmosphere": 0,
            "shape": "Teflon",
            "case_nb": 2,
            "kappas": "AnySample",
            "sector": 360,
            "rest": 1,
            "do_s": 0,
            "area": 660.5198554194,
            "shadow_loss": 0,
            "film": "PP 4mu",
            "link_shape_hdr": 1,
        }, {})
        shown = dict(rows)
        self.assertEqual(shown["化学表示"], "氧化物")
        self.assertEqual(shown["气氛"], "真空")
        self.assertEqual(shown["面积"], "660.52")
        self.assertEqual(shown["阴影损耗"], 0)
        self.assertEqual(shown["膜片"], "PP 4mu")
        for excluded in ("Shape", "Case", "Kappa", "Sector", "Rest", "DoS",
                         "shape", "case_nb", "link_shape_hdr"):
            self.assertNotIn(excluded, shown)


class TestUqPdfPairs(unittest.TestCase):
    def test_pairs_are_aligned_and_totals_include_element_only_items(self):
        pairs, oxide_total, element_total = _report_pairs([
            {"name": "CaO", "value": 14.0},
            {"name": "Cl", "value": 2.0},
        ], ELEMENTS, OXIDES, [])
        self.assertEqual((pairs[0]["oxide_name"], pairs[0]["oxide_value"],
                          pairs[0]["element_name"], pairs[0]["element_value"]),
                         ("CaO", 14.0, "Ca", 10.0))
        self.assertEqual((pairs[1]["oxide_name"], pairs[1]["oxide_value"],
                          pairs[1]["element_name"], pairs[1]["element_value"]),
                         ("Cl", 2.0, "Cl", 2.0))
        self.assertEqual((pairs[0]["unit"], pairs[0]["oxide_display"],
                          pairs[0]["element_display"]), ("%", "14", "10"))
        self.assertEqual(oxide_total, 16.0)
        self.assertEqual(element_total, 12.0)

    def test_unit_override_and_significant_digits(self):
        pairs, _, _ = _report_pairs(
            [{"name": "CaO", "value": 0.00014}], ELEMENTS, OXIDES, [],
            {"cao|ca": "ppb"}, 3)
        self.assertEqual(pairs[0]["unit"], "ppb")
        self.assertEqual(pairs[0]["oxide_display"], "1400")
        self.assertEqual(pairs[0]["element_display"], "1000")


if __name__ == "__main__":
    unittest.main()
