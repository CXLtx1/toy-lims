import os
import tempfile
import unittest

import app as lims
from client_helpers import browser_client


class ResultUnitApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=True)
        self.client = browser_client(self, lims.app)
        self.meta = self.client.get("/api/meta").get_json()
        self.aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Ag")
        self.instrument = next(i for i in self.meta["instruments"]
                               if self.aid in i["analytes"] and i["itype"] == "ppm")

    def tearDown(self):
        self.tmp.cleanup()

    def create_sample(self, *, liquid=False, density=None, raw=100):
        payload = {
            "name": "单位测试样",
            "is_liquid": int(liquid),
            "density_g_ml": density,
            "preps": [{
                "name": "单位测试样*1",
                "mass_g": None if liquid else 1,
                "volume_ml": None if liquid else 100,
                "analyte_ids": [self.aid],
                "instrument_map": {str(self.aid): {"instrument_id": self.instrument["id"]}},
            }],
        }
        response = self.client.post("/api/samples", json=payload)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        sid = response.get_json()["id"]
        self.client.put(f"/api/samples/{sid}/status", json={"status": "queued"})
        self.client.put(f"/api/samples/{sid}/status", json={"status": "measuring"})
        task = self.client.get(f"/api/samples/{sid}").get_json()["items"][0]
        result = self.client.post("/api/results", json={"sample_analyte_id": task["id"], "raw": raw})
        self.assertEqual(200, result.status_code, result.get_data(as_text=True))
        return sid

    def group(self, sid):
        return self.client.get(f"/api/report/{sid}").get_json()["groups"][0]

    def test_solid_default_and_selected_mass_units(self):
        sid = self.create_sample()
        group = self.group(sid)
        self.assertEqual((1.0, "%"), (group["final"]["value"], group["final"]["unit"]))
        self.assertEqual(["%", "ppm", "ppb"], group["available_units"])

        response = self.client.put(f"/api/samples/{sid}/result-unit",
                                   json={"key": group["key"], "unit": "ppm"})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        converted = self.group(sid)
        self.assertEqual((10000.0, "ppm"),
                         (converted["final"]["value"], converted["final"]["unit"]))

    def test_liquid_units_require_density_for_mass_conversion(self):
        sid = self.create_sample(liquid=True, raw=1250)
        group = self.group(sid)
        self.assertEqual((1250.0, "mg/L"), (group["final"]["value"], group["final"]["unit"]))
        self.assertEqual(["g/L", "mg/L", "ug/L"], group["available_units"])
        rejected = self.client.put(f"/api/samples/{sid}/result-unit",
                                   json={"key": group["key"], "unit": "%"})
        self.assertEqual(400, rejected.status_code)

    def test_liquid_density_unlocks_mass_units(self):
        sid = self.create_sample(liquid=True, density=1.25, raw=1250)
        group = self.group(sid)
        self.assertEqual(["g/L", "mg/L", "ug/L", "%", "ppm", "ppb"],
                         group["available_units"])
        response = self.client.put(f"/api/samples/{sid}/result-unit",
                                   json={"key": group["key"], "unit": "%"})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        converted = self.group(sid)
        self.assertEqual((0.1, "%"), (converted["final"]["value"], converted["final"]["unit"]))
        report = self.client.get(f"/api/report/{sid}").get_json()
        self.assertEqual(1.25, report["sample"]["density_g_ml"])

    def test_analyte_default_unit_applies_without_overwriting_sample_choice(self):
        response = self.client.put(f"/api/analytes/{self.aid}", json={"default_unit": "ppm"})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        sid = self.create_sample()
        group = self.group(sid)
        self.assertEqual("ppm", group["final"]["unit"])

        self.client.put(f"/api/samples/{sid}/result-unit",
                        json={"key": group["key"], "unit": "ppb"})
        self.client.put(f"/api/analytes/{self.aid}", json={"default_unit": "%"})
        self.assertEqual("ppb", self.group(sid)["final"]["unit"])

    def test_xrf_composition_unit_is_selected_per_element(self):
        method_id = next(m["id"] for m in self.meta["methods"] if m["itype"] == "xrf")
        response = self.client.post("/api/samples", json={
            "name": "XRF单位测试", "xrf": 1, "xrf_method_id": method_id,
            "xrf_report_items": "Fe",
        })
        sid = response.get_json()["id"]
        imported = self.client.post("/api/instrument/xrf/import", json={
            "analysis_id": "unit-xrf-1", "oxsas_sample_name": "XRF单位测试",
            "method": "WUNI0820", "results": [{"name": "Fe", "value": 2.5}],
        }).get_json()
        assigned = self.client.put(f"/api/xrf/analyses/{imported['analysis_id']}/sample",
                                   json={"sample_id": sid})
        self.assertEqual(200, assigned.status_code, assigned.get_data(as_text=True))
        iron = next(group for group in self.client.get(f"/api/report/{sid}").get_json()["groups"]
                    if group["analyte"] == "Fe")
        self.assertEqual(["%", "ppm", "ppb"], iron["available_units"])
        changed = self.client.put(f"/api/samples/{sid}/result-unit",
                                  json={"key": iron["key"], "unit": "ppm"})
        self.assertEqual(200, changed.status_code, changed.get_data(as_text=True))
        converted = next(group for group in self.client.get(f"/api/report/{sid}").get_json()["groups"]
                         if group["analyte"] == "Fe")
        self.assertEqual((25000.0, "ppm"),
                         (converted["final"]["value"], converted["final"]["unit"]))


if __name__ == "__main__":
    unittest.main()
