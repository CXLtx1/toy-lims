import os
import tempfile
import unittest

import app as lims


class SampleApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lims.DB = os.path.join(self.tmp.name, "test.db")
        lims.init_db()
        lims.app.config.update(TESTING=True, AUTH_DISABLED=True)
        self.client = lims.app.test_client()
        self.meta = self.client.get("/api/meta").get_json()

    def tearDown(self):
        self.tmp.cleanup()

    def create_sample(self):
        aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Ag")
        dilution_id = self.meta["dilutions"][0]["id"]
        response = self.client.post("/api/samples", json={
            "name": "Batch-001",
            "preps": [{
                "name": "Batch-001*1", "mass_g": 1.2, "volume_ml": 100,
                "dilution_id": dilution_id, "analyte_ids": [aid],
            }],
        })
        sid = response.get_json()["id"]
        self.client.put(f"/api/samples/{sid}/status", json={"status": "queued"})
        self.client.put(f"/api/samples/{sid}/status", json={"status": "measuring"})
        return sid, aid, dilution_id

    def test_search_finds_name_and_exact_id(self):
        sid, _, _ = self.create_sample()
        self.assertEqual([sid], [s["id"] for s in self.client.get(
            "/api/samples?q=Batch&limit=20").get_json()])
        self.assertEqual([sid], [s["id"] for s in self.client.get(
            f"/api/samples?q=%23{sid}&limit=20").get_json()])

    def test_update_preserves_unchanged_task_and_result(self):
        sid, aid, dilution_id = self.create_sample()
        detail = self.client.get(f"/api/samples/{sid}").get_json()
        prep = detail["preps"][0]
        task = detail["items"][0]
        added_aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Cu")
        instrument = next(i for i in self.meta["instruments"] if aid in i["analytes"])
        self.client.post("/api/results", json={
            "sample_analyte_id": task["id"], "instrument_id": instrument["id"],
        })
        self.client.post("/api/results", json={
            "sample_analyte_id": task["id"], "raw": 12.5, "extra": {},
        })

        response = self.client.put(f"/api/samples/{sid}", json={
            "name": "Batch-001-revised", "is_liquid": 0, "xrf": 0,
            "preps": [{
                "id": prep["id"], "name": "Batch-001-revised*1", "mass_g": 2,
                "volume_ml": 250, "dilution_id": dilution_id, "analyte_ids": [aid, added_aid],
            }],
            "xrf_analyte_ids": [],
        })
        self.assertTrue(response.get_json()["ok"])
        updated = self.client.get(f"/api/samples/{sid}").get_json()
        self.assertEqual("Batch-001-revised", updated["sample"]["name"])
        self.assertEqual(task["id"], updated["items"][0]["id"])
        self.assertEqual(12.5, updated["items"][0]["raw"])
        self.assertEqual({aid, added_aid}, {item["analyte_id"] for item in updated["items"]})

    def test_ratio_dilution_and_report_metadata(self):
        dilution = self.client.post("/api/dilutions", json={
            "aliquot_ml": 5, "final_volume_ml": 100,
        })
        # 5/100 已作为常用预设写入种子数据，因此重复添加会被明确拒绝。
        self.assertEqual(409, dilution.status_code)
        preset = next(d for d in self.meta["dilutions"] if d["label"] == "5/100")
        self.assertEqual(20, preset["factor"])

        custom = self.client.post("/api/dilutions", json={
            "aliquot_ml": 2.5, "final_volume_ml": 100,
        })
        self.assertEqual(200, custom.status_code)
        self.assertEqual("2.5/100", custom.get_json()["label"])
        self.assertEqual(40, custom.get_json()["factor"])

        sid, _, _ = self.create_sample()
        profile = self.client.post("/api/report-profiles", json={
            "name": "第二公司", "company_name_cn": "第二测试公司",
            "company_name_en": "SECOND TEST CO., LTD.",
            "raw_code": "RAW-02", "final_code": "FINAL-02",
        }).get_json()
        updated_profile = self.client.put(f"/api/report-profiles/{profile['id']}", json={
            "company_name_cn": "第二测试公司（新）", "final_code": "FINAL-02A",
        })
        self.assertTrue(updated_profile.get_json()["ok"])
        saved = self.client.put(f"/api/samples/{sid}/report-meta", json={
            "customer": "生产一部", "report_no": "0005547",
            "analysis_date": "2026-08-26", "analyst": "张三", "reviewer": "不能手填",
            "report_profile_id": profile["id"],
        })
        self.assertTrue(saved.get_json()["ok"])
        sample = self.client.get(f"/api/samples/{sid}").get_json()["sample"]
        self.assertEqual("生产一部", sample["customer"])
        self.assertEqual("0005547", sample["report_no"])
        self.assertEqual("2026-08-26", sample["analysis_date"])
        self.assertEqual("张三", sample["analyst"])
        self.assertEqual("", sample["reviewer"])
        payload = self.client.get(f"/api/report/{sid}").get_json()
        self.assertEqual("第二测试公司（新）", payload["report_profile"]["company_name_cn"])
        self.assertEqual("RAW-02", payload["report_profile"]["raw_code"])
        self.assertEqual("FINAL-02A", payload["report_profile"]["final_code"])

    def test_formula_auto_detects_variables_and_method_note_is_editable(self):
        created = self.client.post("/api/methods", json={
            "name": "自动变量公式", "itype": "function", "formula": "(A1/A2)*50",
            "constants": {}, "note": "先加入指示剂，再缓慢滴定。", "output_unit": "mol/L",
        })
        self.assertEqual(200, created.status_code, created.get_data(as_text=True))
        method = next(item for item in self.client.get("/api/meta").get_json()["methods"]
                      if item["name"] == "自动变量公式")
        updated = self.client.put(f"/api/methods/{method['id']}/note", json={
            "note": "滴定至终点颜色保持 30 秒。", "active": 0,
        })
        self.assertEqual(200, updated.status_code, updated.get_data(as_text=True))
        saved = next(item for item in self.client.get("/api/meta").get_json()["methods"]
                     if item["id"] == method["id"])
        self.assertEqual("滴定至终点颜色保持 30 秒。", saved["note"])
        self.assertEqual("mol/L", saved["output_unit"])
        self.assertEqual(0, saved["active"])

        task = {
            "itype": "function", "formula": "(A1/A2)*50", "method_constants": "{}",
            "method_output_unit": "mol/L", "prep_mass": 1, "prep_vol": 250,
            "prep_factor": 1,
        }
        self.assertEqual((100.0, "mol/L"), lims.reading_value(task, False, None, {"A1": 4, "A2": 2}))
        task["formula"] = "m/v*100"
        task["method_output_unit"] = "g/L"
        self.assertEqual((0.4, "g/L"), lims.reading_value(task, False, None, {}))

        rejected = self.client.post("/api/methods", json={
            "name": "非法公式", "itype": "function", "formula": "A1.__class__", "constants": {},
        })
        self.assertEqual(400, rejected.status_code)
        bad_unit = self.client.post("/api/methods", json={
            "name": "非法单位", "itype": "function", "formula": "V",
            "constants": {}, "output_unit": "kg/L",
        })
        self.assertEqual(400, bad_unit.status_code)

    def test_methods_can_be_reordered_for_picker(self):
        methods = self.client.get("/api/meta").get_json()["methods"]
        reversed_ids = [method["id"] for method in reversed(methods)]
        response = self.client.put("/api/methods/order", json={"ids": reversed_ids})
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        ordered = self.client.get("/api/meta").get_json()["methods"]
        self.assertEqual(reversed_ids, [method["id"] for method in ordered])
        self.assertEqual(list(range(1, len(ordered) + 1)),
                         [method["sort_order"] for method in ordered])

    def test_multistage_dilution_multiplies_factor_and_preserves_steps(self):
        dilution = next(d for d in self.meta["dilutions"] if d["label"] == "5/250")
        aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Ag")
        response = self.client.post("/api/samples", json={
            "name": "连续复稀样", "preps": [{
                "name": "连续复稀样*2500", "mass_g": 1, "volume_ml": 250,
                "dilution_ids": [dilution["id"], dilution["id"]], "analyte_ids": [aid],
            }],
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        prep = self.client.get(f"/api/samples/{response.get_json()['id']}").get_json()["preps"][0]
        self.assertEqual([dilution["id"], dilution["id"]], prep["dilution_ids"])
        self.assertEqual("5/250 × 5/250", prep["dilution_label"])
        self.assertEqual(2500, prep["factor"])

    def test_preparation_combination_crud(self):
        dilution = next(d for d in self.meta["dilutions"] if d["label"] == "5/250")
        created = self.client.post("/api/preparation-combinations", json={
            "name": "两级复稀", "rows": [{
                "name": "复稀液", "mass_g": 1, "volume_ml": 250,
                "dilution_ids": [dilution["id"], dilution["id"]],
            }],
        })
        self.assertEqual(200, created.status_code, created.get_data(as_text=True))
        combination_id = created.get_json()["id"]
        combination = next(item for item in self.client.get("/api/meta").get_json()["preparation_combinations"]
                           if item["id"] == combination_id)
        self.assertEqual([dilution["id"], dilution["id"]], combination["rows"][0]["dilution_ids"])

        updated = self.client.put(f"/api/preparation-combinations/{combination_id}", json={
            "name": "两路复稀", "rows": combination["rows"] * 2,
        })
        self.assertEqual(200, updated.status_code, updated.get_data(as_text=True))
        saved = next(item for item in self.client.get("/api/meta").get_json()["preparation_combinations"]
                     if item["id"] == combination_id)
        self.assertEqual(2, len(saved["rows"]))
        self.assertEqual(200, self.client.delete(
            f"/api/preparation-combinations/{combination_id}").status_code)

    def test_volume_presets_default_hide_and_restore_without_data_loss(self):
        self.assertEqual(250, self.meta["default_volume_ml"])
        self.assertIn(250, [item["volume_ml"] for item in self.meta["volume_presets"] if item["active"]])
        default_id = next(item["id"] for item in self.meta["volume_presets"] if item["volume_ml"] == 250)
        self.assertEqual(400, self.client.delete(f"/api/volume-presets/{default_id}").status_code)
        duplicate = self.client.post("/api/volume-presets", json={"volume_ml": 250})
        self.assertEqual(409, duplicate.status_code)

        created = self.client.post("/api/volume-presets", json={"volume_ml": 500})
        self.assertEqual(200, created.status_code)
        preset_id = created.get_json()["id"]
        aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Ag")
        dilution_id = self.meta["dilutions"][0]["id"]
        sample = self.client.post("/api/samples", json={
            "name": "500mL 定容样", "preps": [{
                "name": "500mL 定容样*1", "mass_g": 1, "volume_ml": 500,
                "dilution_id": dilution_id, "analyte_ids": [aid],
            }],
        }).get_json()

        hidden = self.client.delete(f"/api/volume-presets/{preset_id}")
        self.assertEqual(200, hidden.status_code)
        self.assertEqual(1, hidden.get_json()["historical_preparations"])
        preset = next(item for item in self.client.get("/api/meta").get_json()["volume_presets"]
                      if item["id"] == preset_id)
        self.assertEqual(0, preset["active"])
        detail = self.client.get(f"/api/samples/{sample['id']}").get_json()
        self.assertEqual(500, detail["preps"][0]["volume_ml"])

        restored = self.client.post("/api/volume-presets", json={"volume_ml": 500})
        self.assertEqual(200, restored.status_code)
        self.assertTrue(restored.get_json()["restored"])
        self.assertEqual(preset_id, restored.get_json()["id"])

    def test_used_dilution_can_be_hidden_and_restored_without_data_loss(self):
        preset = next(d for d in self.meta["dilutions"] if d["label"] == "5/100")
        aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Ag")
        created = self.client.post("/api/samples", json={
            "name": "自定义名称样品", "preps": [{
                "name": "消解液-A", "mass_g": 1, "volume_ml": 100,
                "dilution_id": preset["id"], "analyte_ids": [aid],
            }],
        })
        sid = created.get_json()["id"]

        deleted = self.client.delete(f'/api/dilutions/{preset["id"]}')
        self.assertEqual(200, deleted.status_code)
        self.assertEqual(1, deleted.get_json()["historical_preparations"])
        hidden = next(d for d in self.client.get("/api/meta").get_json()["dilutions"]
                      if d["id"] == preset["id"])
        self.assertEqual(0, hidden["active"])

        detail = self.client.get(f"/api/samples/{sid}").get_json()
        self.assertEqual("消解液-A", detail["preps"][0]["name"])
        self.assertEqual("5/100", detail["preps"][0]["dilution_label"])
        self.assertEqual(20, detail["preps"][0]["factor"])

        restored = self.client.post("/api/dilutions", json={
            "aliquot_ml": 5, "final_volume_ml": 100,
        })
        self.assertEqual(200, restored.status_code)
        self.assertTrue(restored.get_json()["restored"])
        self.assertEqual(preset["id"], restored.get_json()["id"])

    def test_sample_type_filter_keeps_solid_and_liquid_separate(self):
        self.create_sample()
        aid = next(a["id"] for a in self.meta["analytes"] if a["name"] == "Ag")
        dilution_id = self.meta["dilutions"][0]["id"]
        liquid = self.client.post("/api/samples", json={
            "name": "液体样", "is_liquid": 1,
            "preps": [{
                "name": "液体样*1", "dilution_id": dilution_id,
                "analyte_ids": [aid],
            }],
        }).get_json()["id"]
        solids = self.client.get("/api/samples?type=solid").get_json()
        liquids = self.client.get("/api/samples?type=liquid").get_json()
        self.assertTrue(solids)
        self.assertTrue(all(not sample["is_liquid"] for sample in solids))
        self.assertEqual([liquid], [sample["id"] for sample in liquids])


if __name__ == "__main__":
    unittest.main()
