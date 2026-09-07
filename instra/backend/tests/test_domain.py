import unittest

from domain.ordering import normalize, order_items
from domain.conversion import (composition_pair_key, composition_pair_label,
                               composition_pairs, conversion_factor, convert_value,
                               name_kind, to_basis)
from domain.compute import (calc_result, convert_result_unit, result_unit_options,
                            rounded_display_value, normalized_result_unit)
from domain.format import (convert_percent, default_xrf_unit, fmt_export_number,
                           round_significant)


class TestOrdering(unittest.TestCase):
    def test_known_first_then_unknown_by_name(self):
        order = ["Fe", "Cu", "Zn"]
        self.assertEqual(order_items(["Pb", "Cu", "Ag", "Fe"], order),
                         ["Fe", "Cu", "Ag", "Pb"])

    def test_case_insensitive_and_dedupe(self):
        self.assertEqual(order_items(["fe", "Fe", "CU"], ["Fe", "Cu"]), ["fe", "CU"])

    def test_channel_names_fall_back_to_name_sort(self):
        # 原始通道名不在模板里，排尾部
        self.assertEqual(order_items(["Ag Ka 1,2net", "Fe"], ["Fe"]),
                         ["Fe", "Ag Ka 1,2net"])

    def test_empty_order_keeps_name_sort(self):
        self.assertEqual(order_items(["Zn", "Al2O3", "Fe"], []), ["Al2O3", "Fe", "Zn"])

    def test_none_and_blank_ignored(self):
        self.assertEqual(order_items(["Fe", "", None], ["Fe"]), ["Fe"])


OXIDES = {
    "fe2o3": {"formula": "Fe2O3", "element": "Fe", "factor": 1.4297},
    "cuo": {"formula": "CuO", "element": "Cu", "factor": 1.2518},
}
ELEMENTS = {"fe": "Fe", "cu": "Cu"}


class TestConversion(unittest.TestCase):
    def test_name_kind(self):
        self.assertEqual(name_kind("Fe", ELEMENTS, OXIDES), "element")
        self.assertEqual(name_kind("Fe2O3", ELEMENTS, OXIDES), "oxide")
        self.assertEqual(name_kind("Ag Ka 1,2net", ELEMENTS, OXIDES), "unknown")

    def test_element_to_oxide(self):
        factor, note = conversion_factor("Fe", "Fe2O3", OXIDES)
        self.assertAlmostEqual(factor, 1.4297)
        self.assertIn("×", note)

    def test_oxide_to_element(self):
        factor, note = conversion_factor("Fe2O3", "Fe", OXIDES)
        self.assertAlmostEqual(factor, 1 / 1.4297)
        self.assertIn("÷", note)

    def test_unrelated_returns_none(self):
        factor, _ = conversion_factor("Fe", "CuO", OXIDES)
        self.assertIsNone(factor)

    def test_convert_value(self):
        value, note = convert_value("Fe", "Fe2O3", 10.0, OXIDES)
        self.assertAlmostEqual(value, 14.297)

    def test_same_name_identity(self):
        factor, note = conversion_factor("Fe", "fe", OXIDES)
        self.assertEqual(factor, 1.0)
        self.assertEqual(note, "")


OXIDES_CONV = {
    "fe2o3": {"formula": "Fe2O3", "element": "Fe", "factor": 1.4297, "conventional": True},
    "feo": {"formula": "FeO", "element": "Fe", "factor": 1.2865, "conventional": False},
    "cuo": {"formula": "CuO", "element": "Cu", "factor": 1.2518, "conventional": True},
}


class TestToBasis(unittest.TestCase):
    def test_native_basis_asis(self):
        name, value, note = to_basis("CaO", "", 38.593, "oxide", ELEMENTS, OXIDES_CONV)
        self.assertEqual((name, value, note), ("CaO", 38.593, ""))

    def test_oxide_to_element_without_alt(self):
        name, value, note = to_basis("Fe2O3", "", 10.0, "element", ELEMENTS, OXIDES_CONV)
        self.assertEqual(name, "Fe")
        self.assertAlmostEqual(value, 10.0 / 1.4297)
        self.assertIn("÷", note)

    def test_element_to_conventional_oxide(self):
        name, value, note = to_basis("Fe", "", 10.0, "oxide", ELEMENTS, OXIDES_CONV)
        self.assertEqual(name, "Fe2O3")  # 惯用氧化物优先
        self.assertAlmostEqual(value, 14.297)

    def test_alt_name_preferred(self):
        name, value, _ = to_basis("Fe2O3", "Fe", 10.0, "element", ELEMENTS, OXIDES_CONV)
        self.assertEqual(name, "Fe")
        self.assertAlmostEqual(value, 10.0 / 1.4297)

    def test_unknown_stays(self):
        name, value, note = to_basis("Ag Ka 1,2net", "", 0.003, "element", ELEMENTS, OXIDES_CONV)
        self.assertEqual((name, value), ("Ag Ka 1,2net", 0.003))


class TestCompositionPairs(unittest.TestCase):
    def test_oxide_pairs_with_element(self):
        pairs = composition_pairs(
            [{"name": "SO3", "value": 16.494}], ELEMENTS, OXIDES_CONV)
        self.assertIsNone(pairs[0]["element_name"])  # SO3 不在参考表 → 原样
        self.assertEqual(pairs[0]["oxide_value"], 16.494)

    def test_known_oxide_divides_factor(self):
        oxides = dict(OXIDES_CONV)
        oxides["sio2"] = {"formula": "SiO2", "element": "Si", "factor": 2.1393,
                          "conventional": True}
        pairs = composition_pairs([{"name": "SiO2", "value": 2.1393}], ELEMENTS, oxides)
        self.assertEqual(pairs[0]["element_name"], "Si")
        self.assertAlmostEqual(pairs[0]["element_value"], 1.0)

    def test_element_uses_conventional_oxide(self):
        pairs = composition_pairs([{"name": "Fe", "value": 7.0}], ELEMENTS, OXIDES_CONV)
        self.assertEqual(pairs[0]["oxide_name"], "Fe2O3")
        self.assertAlmostEqual(pairs[0]["oxide_value"], 7.0 * 1.4297)
        self.assertEqual(pairs[0]["element_name"], "Fe")

    def test_element_without_oxide_repeats_on_both_sides(self):
        elements = dict(ELEMENTS, br="Br")
        pairs = composition_pairs([{"name": "Br", "value": 0.011}], elements, OXIDES_CONV)
        self.assertEqual(pairs[0]["oxide_name"], "Br")
        self.assertEqual(pairs[0]["oxide_value"], 0.011)
        self.assertEqual(pairs[0]["element_name"], "Br")
        self.assertEqual(pairs[0]["element_value"], 0.011)

    def test_unknown_goes_left_asis(self):
        pairs = composition_pairs([{"name": "Ag Ka 1,2net", "value": 0.003}],
                                  ELEMENTS, OXIDES_CONV)
        self.assertEqual(pairs[0]["oxide_name"], "Ag Ka 1,2net")
        self.assertIsNone(pairs[0]["element_name"])

    def test_null_value_keeps_names(self):
        pairs = composition_pairs([{"name": "CuO", "value": None}], ELEMENTS, OXIDES_CONV)
        self.assertEqual((pairs[0]["oxide_name"], pairs[0]["element_name"]), ("CuO", "Cu"))
        self.assertIsNone(pairs[0]["element_value"])

    def test_pair_key_and_label(self):
        pair = {"oxide_name": "Fe2O3", "element_name": "Fe"}
        self.assertEqual(composition_pair_key(pair), "fe2o3|fe")
        self.assertEqual(composition_pair_label(pair), "Fe2O3 / Fe")
        pure = {"oxide_name": "Cl", "element_name": "Cl"}
        self.assertEqual(composition_pair_label(pure), "Cl")


class TestUnits(unittest.TestCase):
    def test_mass_chain(self):
        self.assertEqual(convert_result_unit(1.0, "%", "ppm"), 10000.0)
        self.assertEqual(convert_result_unit(10000.0, "ppm", "%"), 1.0)

    def test_volume_needs_density(self):
        self.assertEqual(convert_result_unit(1.0, "%", "mg/L", density=1.0), 10000.0)
        with self.assertRaises(ValueError):
            convert_result_unit(1.0, "%", "mg/L")

    def test_options(self):
        self.assertEqual(result_unit_options("%"), ["%", "ppm", "ppb"])
        self.assertEqual(result_unit_options("mg/L", density=1.2),
                         ["g/L", "mg/L", "ug/L", "%", "ppm", "ppb"])

    def test_normalize_micro(self):
        self.assertEqual(normalized_result_unit("μg/L"), "ug/L")

    def test_rounded_display(self):
        self.assertEqual(rounded_display_value(17.85234, "%", xrf=True), 17.852)
        self.assertEqual(rounded_display_value(0.123456789, "mg/L"), 0.1235)

    def test_xrf_default_unit_boundaries(self):
        self.assertEqual(default_xrf_unit(0.1), "%")
        self.assertEqual(default_xrf_unit(0.09999), "ppm")
        self.assertEqual(default_xrf_unit(0.0001), "ppm")
        self.assertEqual(default_xrf_unit(0.00009999), "ppb")
        self.assertEqual(default_xrf_unit(0), "ppb")

    def test_xrf_percent_conversion(self):
        self.assertEqual(convert_percent(0.1, "%"), 0.1)
        self.assertEqual(convert_percent(0.1, "ppm"), 1000)
        self.assertEqual(convert_percent(0.1, "ppb"), 1_000_000)

    def test_significant_digit_rounding(self):
        self.assertEqual(round_significant(12.34567, 4), 12.35)
        self.assertEqual(round_significant(0.001234567, 4), 0.001235)
        self.assertEqual(round_significant(0, 4), 0)
        self.assertEqual(fmt_export_number(1_234_567, 4), "1235000")
        self.assertEqual(fmt_export_number(12.34567, 4), "12.35")
        self.assertEqual(fmt_export_number(0.001234567, 4), "0.001235")


class TestCalcResult(unittest.TestCase):
    def test_average_of_used_readings(self):
        sa = {"itype": "percent", "prep_factor": 1, "formula": "",
              "method_constants": "{}", "prep_mass": 1, "prep_vol": 250,
              "raw": None, "extra": "{}", "aux": "{}",
              "readings": [{"raw": 1.0, "extra": {}, "use_avg": 1, "is_final": 0},
                           {"raw": 3.0, "extra": {}, "use_avg": 1, "is_final": 0},
                           {"raw": 99.0, "extra": {}, "use_avg": 0, "is_final": 0}]}
        value, unit, details = calc_result(sa, False)
        self.assertEqual((value, unit), (2.0, "%"))
        self.assertEqual([d["used"] for d in details], [True, True, False])

    def test_aux_coefficient_applied_once(self):
        sa = {"itype": "percent", "prep_factor": 1, "formula": "",
              "method_constants": "{}", "prep_mass": 1, "prep_vol": 250,
              "raw": None, "extra": "{}", "aux": '{"use": 1, "coefficient": 2}',
              "readings": [{"raw": 1.0, "extra": {}, "use_avg": 1, "is_final": 0}]}
        value, unit, _ = calc_result(sa, False)
        self.assertEqual(value, 2.0)

    def test_ppm_solid_to_percent(self):
        sa = {"itype": "ppm", "prep_factor": 2, "formula": "",
              "method_constants": "{}", "prep_mass": 1, "prep_vol": 250,
              "raw": None, "extra": "{}", "aux": "{}",
              "readings": [{"raw": 100.0, "extra": {}, "use_avg": 1, "is_final": 0}]}
        value, unit, _ = calc_result(sa, False)
        # 100 mg/L * 250 mL * 2 / (1 g * 10^4) = 5 %
        self.assertEqual((value, unit), (5.0, "%"))

    def test_unrecorded(self):
        sa = {"itype": "percent", "prep_factor": 1, "formula": "",
              "method_constants": "{}", "prep_mass": None, "prep_vol": None,
              "raw": None, "extra": "{}", "aux": "{}", "readings": []}
        value, note, _ = calc_result(sa, False)
        self.assertIsNone(value)
        self.assertEqual(note, "未录入")


if __name__ == "__main__":
    unittest.main()
