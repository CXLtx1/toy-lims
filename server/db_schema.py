"""PostgreSQL schema and reference-data seeds."""

import json

from db_backend import connect_database


CHEMICAL_ELEMENT_SEEDS = [
    (1, "H", "氢", 1.008, 0), (2, "He", "氦", 4.0026, 0),
    (3, "Li", "锂", 6.94, 0), (4, "Be", "铍", 9.0122, 0),
    (5, "B", "硼", 10.81, 0), (6, "C", "碳", 12.011, 0),
    (7, "N", "氮", 14.007, 0), (8, "O", "氧", 15.999, 0),
    (9, "F", "氟", 18.998, 0), (10, "Ne", "氖", 20.18, 0),
    (11, "Na", "钠", 22.99, 0), (12, "Mg", "镁", 24.305, 0),
    (13, "Al", "铝", 26.982, 0), (14, "Si", "硅", 28.085, 0),
    (15, "P", "磷", 30.974, 0), (16, "S", "硫", 32.06, 0),
    (17, "Cl", "氯", 35.45, 0), (18, "Ar", "氩", 39.948, 0),
    (19, "K", "钾", 39.098, 0), (20, "Ca", "钙", 40.078, 0),
    (21, "Sc", "钪", 44.956, 0), (22, "Ti", "钛", 47.867, 0),
    (23, "V", "钒", 50.942, 0), (24, "Cr", "铬", 51.996, 0),
    (25, "Mn", "锰", 54.938, 0), (26, "Fe", "铁", 55.845, 0),
    (27, "Co", "钴", 58.933, 0), (28, "Ni", "镍", 58.693, 0),
    (29, "Cu", "铜", 63.546, 0), (30, "Zn", "锌", 65.38, 0),
    (31, "Ga", "镓", 69.723, 0), (32, "Ge", "锗", 72.63, 0),
    (33, "As", "砷", 74.922, 0), (34, "Se", "硒", 78.971, 0),
    (35, "Br", "溴", 79.904, 0), (36, "Kr", "氪", 83.798, 0),
    (37, "Rb", "铷", 85.468, 0), (38, "Sr", "锶", 87.62, 0),
    (39, "Y", "钇", 88.906, 0), (40, "Zr", "锆", 91.224, 0),
    (41, "Nb", "铌", 92.906, 0), (42, "Mo", "钼", 95.95, 0),
    (43, "Tc", "锝", 98.0, 1), (44, "Ru", "钌", 101.07, 0),
    (45, "Rh", "铑", 102.91, 0), (46, "Pd", "钯", 106.42, 0),
    (47, "Ag", "银", 107.87, 0), (48, "Cd", "镉", 112.41, 0),
    (49, "In", "铟", 114.82, 0), (50, "Sn", "锡", 118.71, 0),
    (51, "Sb", "锑", 121.76, 0), (52, "Te", "碲", 127.6, 0),
    (53, "I", "碘", 126.9, 0), (54, "Xe", "氙", 131.29, 0),
    (55, "Cs", "铯", 132.91, 0), (56, "Ba", "钡", 137.33, 0),
    (57, "La", "镧", 138.91, 0), (58, "Ce", "铈", 140.12, 0),
    (59, "Pr", "镨", 140.91, 0), (60, "Nd", "钕", 144.24, 0),
    (61, "Pm", "钷", 145.0, 1), (62, "Sm", "钐", 150.36, 0),
    (63, "Eu", "铕", 151.96, 0), (64, "Gd", "钆", 157.25, 0),
    (65, "Tb", "铽", 158.93, 0), (66, "Dy", "镝", 162.5, 0),
    (67, "Ho", "钬", 164.93, 0), (68, "Er", "铒", 167.26, 0),
    (69, "Tm", "铥", 168.93, 0), (70, "Yb", "镱", 173.05, 0),
    (71, "Lu", "镥", 174.97, 0), (72, "Hf", "铪", 178.49, 0),
    (73, "Ta", "钽", 180.95, 0), (74, "W", "钨", 183.84, 0),
    (75, "Re", "铼", 186.21, 0), (76, "Os", "锇", 190.23, 0),
    (77, "Ir", "铱", 192.22, 0), (78, "Pt", "铂", 195.08, 0),
    (79, "Au", "金", 196.97, 0), (80, "Hg", "汞", 200.59, 0),
    (81, "Tl", "铊", 204.38, 0), (82, "Pb", "铅", 207.2, 0),
    (83, "Bi", "铋", 208.98, 0),
    (90, "Th", "钍", 232.04, 0), (92, "U", "铀", 238.03, 0),
    (94, "Pu", "钚", 244.0, 1), (95, "Am", "镅", 243.0, 1),
]


COMMON_OXIDE_SEEDS = [
    ("Li2O", "氧化锂", "Li", 2, 1, 1, ""),
    ("BeO", "氧化铍", "Be", 1, 1, 1, ""),
    ("B2O3", "三氧化二硼", "B", 2, 3, 1, ""),
    ("Na2O", "氧化钠", "Na", 2, 1, 1, ""),
    ("MgO", "氧化镁", "Mg", 1, 1, 1, ""),
    ("Al2O3", "氧化铝", "Al", 2, 3, 1, ""),
    ("SiO2", "二氧化硅", "Si", 1, 2, 1, ""),
    ("P2O5", "五氧化二磷", "P", 2, 5, 1, "报告惯用式；实际分子常写作 P4O10"),
    ("SO3", "三氧化硫", "S", 1, 3, 1, ""),
    ("K2O", "氧化钾", "K", 2, 1, 1, ""),
    ("CaO", "氧化钙", "Ca", 1, 1, 1, ""),
    ("Sc2O3", "氧化钪", "Sc", 2, 3, 1, ""),
    ("TiO2", "二氧化钛", "Ti", 1, 2, 1, ""),
    ("V2O5", "五氧化二钒", "V", 2, 5, 1, ""),
    ("Cr2O3", "三氧化二铬", "Cr", 2, 3, 1, ""),
    ("MnO", "氧化锰", "Mn", 1, 1, 1, ""),
    ("MnO2", "二氧化锰", "Mn", 1, 2, 0, ""),
    ("Mn3O4", "四氧化三锰", "Mn", 3, 4, 0, ""),
    ("FeO", "氧化亚铁", "Fe", 1, 1, 0, ""),
    ("Fe2O3", "三氧化二铁", "Fe", 2, 3, 1, ""),
    ("Fe3O4", "四氧化三铁", "Fe", 3, 4, 0, ""),
    ("CoO", "氧化钴", "Co", 1, 1, 0, ""),
    ("Co3O4", "四氧化三钴", "Co", 3, 4, 1, ""),
    ("NiO", "氧化镍", "Ni", 1, 1, 1, ""),
    ("Cu2O", "氧化亚铜", "Cu", 2, 1, 0, ""),
    ("CuO", "氧化铜", "Cu", 1, 1, 1, ""),
    ("ZnO", "氧化锌", "Zn", 1, 1, 1, ""),
    ("Ga2O3", "氧化镓", "Ga", 2, 3, 1, ""),
    ("GeO2", "二氧化锗", "Ge", 1, 2, 1, ""),
    ("As2O3", "三氧化二砷", "As", 2, 3, 1, ""),
    ("As2O5", "五氧化二砷", "As", 2, 5, 0, ""),
    ("SeO2", "二氧化硒", "Se", 1, 2, 1, ""),
    ("Rb2O", "氧化铷", "Rb", 2, 1, 1, ""),
    ("SrO", "氧化锶", "Sr", 1, 1, 1, ""),
    ("Y2O3", "氧化钇", "Y", 2, 3, 1, ""),
    ("ZrO2", "二氧化锆", "Zr", 1, 2, 1, ""),
    ("Nb2O5", "五氧化二铌", "Nb", 2, 5, 1, ""),
    ("MoO3", "三氧化钼", "Mo", 1, 3, 1, ""),
    ("Ag2O", "氧化银", "Ag", 2, 1, 1, ""),
    ("CdO", "氧化镉", "Cd", 1, 1, 1, ""),
    ("In2O3", "氧化铟", "In", 2, 3, 1, ""),
    ("SnO2", "二氧化锡", "Sn", 1, 2, 1, ""),
    ("Sb2O3", "三氧化二锑", "Sb", 2, 3, 1, ""),
    ("Sb2O5", "五氧化二锑", "Sb", 2, 5, 0, ""),
    ("TeO2", "二氧化碲", "Te", 1, 2, 1, ""),
    ("Cs2O", "氧化铯", "Cs", 2, 1, 1, ""),
    ("BaO", "氧化钡", "Ba", 1, 1, 1, ""),
    ("La2O3", "氧化镧", "La", 2, 3, 1, ""),
    ("CeO2", "二氧化铈", "Ce", 1, 2, 1, ""),
    ("Pr6O11", "十一氧化六镨", "Pr", 6, 11, 1, ""),
    ("Nd2O3", "氧化钕", "Nd", 2, 3, 1, ""),
    ("Sm2O3", "氧化钐", "Sm", 2, 3, 1, ""),
    ("Eu2O3", "氧化铕", "Eu", 2, 3, 1, ""),
    ("Gd2O3", "氧化钆", "Gd", 2, 3, 1, ""),
    ("Tb4O7", "七氧化四铽", "Tb", 4, 7, 1, ""),
    ("Dy2O3", "氧化镝", "Dy", 2, 3, 1, ""),
    ("Ho2O3", "氧化钬", "Ho", 2, 3, 1, ""),
    ("Er2O3", "氧化铒", "Er", 2, 3, 1, ""),
    ("Tm2O3", "氧化铥", "Tm", 2, 3, 1, ""),
    ("Yb2O3", "氧化镱", "Yb", 2, 3, 1, ""),
    ("Lu2O3", "氧化镥", "Lu", 2, 3, 1, ""),
    ("HfO2", "二氧化铪", "Hf", 1, 2, 1, ""),
    ("Ta2O5", "五氧化二钽", "Ta", 2, 5, 1, ""),
    ("WO3", "三氧化钨", "W", 1, 3, 1, ""),
    ("Re2O7", "七氧化二铼", "Re", 2, 7, 1, ""),
    ("RuO4", "四氧化钌", "Ru", 1, 4, 1, ""),
    ("Rh2O3", "三氧化二铑", "Rh", 2, 3, 1, ""),
    ("OsO4", "四氧化锇", "Os", 1, 4, 1, ""),
    ("IrO2", "二氧化铱", "Ir", 1, 2, 1, ""),
    ("PtO2", "二氧化铂", "Pt", 1, 2, 1, ""),
    ("HgO", "氧化汞", "Hg", 1, 1, 1, ""),
    ("Tl2O3", "三氧化二铊", "Tl", 2, 3, 1, ""),
    ("PbO", "氧化铅", "Pb", 1, 1, 1, ""),
    ("PbO2", "二氧化铅", "Pb", 1, 2, 0, ""),
    ("Bi2O3", "氧化铋", "Bi", 2, 3, 1, ""),
    ("ThO2", "二氧化钍", "Th", 1, 2, 1, ""),
    ("U3O8", "八氧化三铀", "U", 3, 8, 1, ""),
    ("PuO2", "二氧化钚", "Pu", 1, 2, 1, ""),
    ("Am2O3", "三氧化二镅", "Am", 2, 3, 1, ""),
]


SPECIAL_METHOD_SEEDS = [
    ("moisture", "水分分析", "水分分析仪", {
        "title": "水分分析原始记录", "groups": [{"name": "水分测定", "fields": [
            {"key": "time", "label": "时间", "type": "time"}, {"key": "pan_no", "label": "盘号"},
            {"key": "pan_weight", "label": "盘重", "unit": "g", "required": True},
            {"key": "sample_weight", "label": "样重", "unit": "g", "required": True},
            {"key": "dry_total", "label": "干总重", "unit": "g", "required": True},
            {"key": "moisture", "label": "水分", "unit": "%", "formula": "(pan_weight+sample_weight-dry_total)/sample_weight*100", "decimals": 2}
        ]}]}),
    ("coal", "煤/炭精分析", "煤质分析设备", {
        "title": "煤-炭精分析原始记录", "groups": [
            {"name": "灰分", "fields": [{"key":"ash_boat","label":"舟重","unit":"g","required":True},{"key":"ash_sample","label":"样重","unit":"g","required":True},{"key":"ash_total","label":"烧后总重","unit":"g","required":True},{"key":"ash","label":"灰分","unit":"%","formula":"(ash_total-ash_boat)/ash_sample*100","decimals":2}]},
            {"name": "分析水", "fields": [{"key":"water_dish","label":"皿重","unit":"g","required":True},{"key":"water_sample","label":"样重","unit":"g","required":True},{"key":"water_total","label":"烘干后总重","unit":"g","required":True},{"key":"analysis_water","label":"分析水","unit":"%","formula":"(water_dish+water_sample-water_total)/water_sample*100","decimals":2}]},
            {"name": "挥发分", "fields": [{"key":"volatile_crucible","label":"坩埚重","unit":"g","required":True},{"key":"volatile_sample","label":"样重","unit":"g","required":True},{"key":"volatile_total","label":"烧后总重","unit":"g","required":True},{"key":"volatile","label":"挥发分","unit":"%","formula":"(volatile_crucible+volatile_sample-volatile_total)/volatile_sample*100-analysis_water","decimals":2},{"key":"sulfur","label":"S","unit":"%","required":True}]},
            {"name": "固定碳", "fields": [{"key":"fixed_carbon","label":"固定碳","unit":"%","formula":"100-ash-analysis_water-volatile","decimals":2}]}
        ]}),
    ("gypsum", "石膏分析", "石膏分析设备", {
        "title": "石膏分析原始记录", "groups": [
            {"name":"附着水", "fields":[{"key":"attached_pan","label":"盘重","unit":"g","required":True},{"key":"attached_sample","label":"样重","unit":"g","required":True},{"key":"attached_total","label":"45℃恒重总重","unit":"g","required":True},{"key":"attached_constant","label":"恒重样重","unit":"g","formula":"attached_total-attached_pan","decimals":4},{"key":"attached_water","label":"附着水","unit":"%","formula":"(attached_pan+attached_sample-attached_total)/attached_sample*100","decimals":2}]},
            {"name":"结晶水及二水硫酸钙", "fields":[{"key":"crystal_dish","label":"皿重","unit":"g","required":True},{"key":"crystal_sample","label":"样重","unit":"g","required":True},{"key":"crystal_total","label":"230℃恒重总重","unit":"g","required":True},{"key":"crystal_constant","label":"恒重样重","unit":"g","formula":"crystal_total-crystal_dish","decimals":4},{"key":"crystal_water","label":"结晶水","unit":"%","formula":"(crystal_dish+crystal_sample-crystal_total)/crystal_sample*100","decimals":2},{"key":"dihydrate","label":"二水硫酸钙","unit":"%","formula":"crystal_water*4.778","decimals":2}]},
            {"name":"氯离子", "fields":[{"key":"cl_sample","label":"样重","unit":"g","required":True},{"key":"cl_total_volume","label":"定容体积","unit":"mL","required":True},{"key":"cl_aliquot","label":"移取体积","unit":"mL","required":True},{"key":"agno3_c","label":"AgNO3浓度","unit":"mol/L","required":True},{"key":"agno3_v","label":"消耗标准液","unit":"mL","required":True},{"key":"chloride","label":"Cl-","unit":"ppm","formula":"agno3_c*agno3_v*35.45*cl_total_volume/cl_aliquot/cl_sample*1000","decimals":2}]}
        ]}),
    ("carbon_sulfur", "碳硫分析", "碳硫分析仪", {"title":"碳硫分析原始记录","groups":[{"name":"碳硫结果","fields":[{"key":"analysis_time","label":"分析时间","type":"datetime-local"},{"key":"sulfur","label":"S","unit":"%","required":True},{"key":"carbon","label":"C","unit":"%","required":True}]}]}),
    ("calorimeter", "量热分析", "量热仪", {"title":"量热仪分析原始记录","groups":[{"name":"热值结果","fields":[{"key":"analysis_time","label":"分析时间","type":"datetime-local"},{"key":"hhv","label":"高位热值 HHV","unit":"cal/g","required":True},{"key":"lhv","label":"低位热值 LHV","unit":"cal/g","required":True}]}]})
]

FORMULA_METHOD_CATALOG = [
    ("Cu-碘量法", "c*V*63.55/m/1000*100", "%", "c=硫代硫酸钠浓度(mol/L)，V=消耗体积(mL)，m=称样质量(g)。"),
    ("Zn-EDTA滴定法", "c*V*65.38*v/Va/m/1000*100", "%", "c=EDTA浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("Cl-硝酸银滴定法", "c*V*35.5*v/Va/m/1000*100", "%", "c=硝酸银浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("Al2O3-硫酸铜反滴定法", "c*V*50.98*v/Va/m/1000*100", "%", "c=硫酸铜浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("Cr-硫酸亚铁铵滴定法", "V2/V1*58.37", "%", "V1=58.37%铬标准样消耗体积(mL)，V2=样品消耗体积(mL)。"),
    ("P-铋盐钼蓝分光光度法", "A2/A1*0.073", "%", "A1=0.073%磷标准样吸光度，A2=样品吸光度。"),
    ("Ca-EDTA滴定法", "c*V*40.08*v/Va/m/1000*100", "%", "c=EDTA浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("CaO-EDTA滴定法", "c*V*56.08*v/Va/m/1000*100", "%", "c=EDTA浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("CaCO3-EDTA滴定法", "c*V*100.09*v/Va/m/1000*100", "%", "c=EDTA浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("Ca(OH)2-EDTA滴定法", "c*V*74.096*v/Va/m/1000*100", "%", "c=EDTA浓度(mol/L)，V=消耗体积(mL)，v=消解定容体积(mL)，Va=分取母液体积(mL)，m=称样质量(g)。"),
    ("Cu-分光光度法（一次稀释）", "c*V1*v*A2/(A1*V5*m*1000000)*100", "%", "c=铜标准液浓度(mg/L)，V1=标准液移取体积，v=样品定容体积，V5=显色取样量，A1/A2=标准/试样吸光度，m=称样质量。"),
    ("Cu-分光光度法（二次稀释）", "c*V1*v*A2*V3/(A1*V4*V5*m*1000000)*100", "%", "V3/V4=中间定容/分取体积；其余变量同一次稀释法。"),
    ("Ni-丁二酮肟分光光度法", "A2/A1*4.04", "%", "A1=4.04%镍标准样吸光度，A2=样品吸光度。"),
    ("H+-酸碱滴定法", "c*V2/V1", "mol/L", "c=NaOH浓度(mol/L)，V1=样品移取体积(mL)，V2=NaOH消耗体积(mL)。"),
    ("OH--酸碱滴定法", "c*V2/V1", "mol/L", "c=HCl浓度(mol/L)，V1=样品移取体积(mL)，V2=HCl消耗体积(mL)。"),
    ("HCl-酸碱滴定法", "c*V*36.45/m/1000*100", "%", "c=NaOH浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)。"),
    ("H2SO4-酸碱滴定法", "c*V*(98.08/2)/m/1000*100", "%", "c=NaOH浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)。"),
    ("NaClO-硫代硫酸钠滴定法", "c*V*37.221/m/1000*100", "%", "c=硫代硫酸钠浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)。"),
    ("NaOH-酸碱滴定法", "c*V*40/m/1000*100", "%", "c=HCl浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)。"),
    ("Na2CO3-酸碱滴定法", "c*V*105.98/m/1000*100", "%", "c=HCl浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)；按汇总文件原公式。"),
    ("NH3-酸碱滴定法", "c*V*17.03/m/1000*100", "%", "c=HCl浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)。"),
    ("H2O2-高锰酸钾滴定法", "c*V*34.01*2.5/m/1000*100", "%", "c=KMnO4物质的量浓度(mol/L)，V=消耗体积(mL)，m=试样质量(g)。"),
    ("水分-干燥失重法", "(m-(m3-m1))/m*100", "%", "m1=空白称量瓶质量(g)，m=试样质量(g)，m3=干燥后试样与称量瓶总质量(g)。"),
    ("COD-重铬酸钾法", "c*(V0-V1)*8000/V2*f", "ppm", "c=硫酸亚铁铵浓度(mol/L)，V0/V1=空白/水样消耗体积，V2=水样体积，f=人工录入稀释倍数；ppm按mg/L使用。"),
    ("Cl-比浊法（一次稀释）", "c*V1*v*A2/(A1*V5*m*1000000)*100", "%", "c=氯标准液浓度(mg/L)，V1=标准液移取体积，v=样品定容体积，V5=比浊取样量，A1/A2=标准/试样吸光度，m=称样质量。"),
    ("Cl-比浊法（二次稀释）", "c*V1*v*A2*V3/(A1*V4*V5*m*1000000)*100", "%", "V3/V4=中间定容/分取体积；其余变量同一次稀释法。"),
    ("TN-总氮浓度计算", "C/V*f", "ppm", "C=仪器测得总氮含量(μg)，V=对应样品体积(mL)，f=人工录入稀释倍数；ppm按mg/L使用。"),
]


SCHEMA = """
CREATE TABLE IF NOT EXISTS analytes(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    sort_order INTEGER DEFAULT 0,
    default_unit TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS chemical_elements(
    atomic_number INTEGER PRIMARY KEY,
    symbol TEXT UNIQUE NOT NULL,
    name_zh TEXT NOT NULL,
    atomic_weight DOUBLE PRECISION NOT NULL,
    is_mass_number INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS common_oxides(
    formula TEXT PRIMARY KEY,
    name_zh TEXT NOT NULL,
    element_symbol TEXT NOT NULL REFERENCES chemical_elements(symbol),
    element_count INTEGER NOT NULL,
    oxygen_count INTEGER NOT NULL,
    molar_mass DOUBLE PRECISION NOT NULL,
    element_mass_fraction DOUBLE PRECISION NOT NULL,
    element_to_oxide_factor DOUBLE PRECISION NOT NULL,
    is_conventional INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS instruments(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    itype TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0);
-- xrf | ppm | ppb | mol | percent | function | ph
CREATE TABLE IF NOT EXISTS instr_analytes(
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    analyte_id INTEGER NOT NULL REFERENCES analytes(id) ON DELETE CASCADE,
    PRIMARY KEY(instrument_id, analyte_id));
CREATE TABLE IF NOT EXISTS dilutions(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    label TEXT NOT NULL,
    factor DOUBLE PRECISION NOT NULL,
    active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS volume_presets(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    volume_ml DOUBLE PRECISION UNIQUE NOT NULL,
    active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS methods(           -- 仪器方法
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    itype TEXT DEFAULT 'function',
    formula TEXT NOT NULL,   -- 变量: V V0 c M m, 结果以质量分数%计
    constants TEXT DEFAULT '{}', -- 方法固定常数，如原子量 {"M":65.38}
    note TEXT DEFAULT '',
    output_unit TEXT DEFAULT '%',
    target TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS templates(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT DEFAULT '',
    tags_json TEXT DEFAULT '[]',
    is_liquid INTEGER DEFAULT 0,
    is_water_quality INTEGER DEFAULT 0,
    dilution_id INTEGER,
    xrf INTEGER DEFAULT 0,
    analyte_ids TEXT DEFAULT '[]',
    prep_config TEXT DEFAULT '[]',
    instrument_config TEXT DEFAULT '{}',
    order_template_id INTEGER);
CREATE TABLE IF NOT EXISTS preparation_combinations(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    config_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS report_profiles(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    company_name_cn TEXT NOT NULL,
    company_name_en TEXT DEFAULT '',
    raw_code TEXT DEFAULT '',
    final_code TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS result_order_templates(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    items_json TEXT NOT NULL DEFAULT '[]',
    is_default INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS special_methods(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    instrument TEXT DEFAULT '',
    schema_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS users(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    permissions TEXT NOT NULL DEFAULT '[]',
    active INTEGER DEFAULT 1,
    session_token TEXT DEFAULT '',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS samples(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT DEFAULT '',   -- 样品名称/描述, 如 Zn(OH)2沉淀
    is_liquid INTEGER DEFAULT 0,
    density_g_ml DOUBLE PRECISION,
    is_water_quality INTEGER DEFAULT 0,
    workflow_type TEXT DEFAULT 'regular',
    special_method_id INTEGER REFERENCES special_methods(id),
    dilution_id INTEGER,
    mass_g DOUBLE PRECISION,
    volume_ml DOUBLE PRECISION,
    xrf INTEGER DEFAULT 0,
    xrf_method_id INTEGER REFERENCES methods(id),
    xrf_report_items TEXT DEFAULT '',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    customer TEXT DEFAULT '',
    report_no TEXT DEFAULT '',
    analysis_date TEXT DEFAULT '',
    analyst TEXT DEFAULT '',
    reviewer TEXT DEFAULT '',
    report_profile_id INTEGER REFERENCES report_profiles(id) ON DELETE SET NULL,
    order_template_id INTEGER,
    report_order TEXT DEFAULT '[]',
    report_excludes TEXT DEFAULT '[]',
    result_units TEXT DEFAULT '{}',
    lims_no TEXT,
    status TEXT DEFAULT 'received',
    status_operator TEXT DEFAULT '',
    status_action TEXT DEFAULT '',
    status_changed_at TEXT,
    cancelled_at TEXT,
    cancelled_by INTEGER,
    cancel_reason TEXT DEFAULT '',
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS sample_tags(
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY(sample_id, tag));
CREATE TABLE IF NOT EXISTS special_results(
    sample_id INTEGER PRIMARY KEY REFERENCES samples(id) ON DELETE CASCADE,
    method_id INTEGER NOT NULL REFERENCES special_methods(id),
    raw_data TEXT NOT NULL DEFAULT '{}',
    calculated_data TEXT NOT NULL DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_by INTEGER);
CREATE TABLE IF NOT EXISTS preparations(      -- 一路溶样: 称样->定容->稀释
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    name TEXT NOT NULL,           -- 如 AB2602-1*50
    mass_g DOUBLE PRECISION,
    volume_ml DOUBLE PRECISION,
    dilution_id INTEGER REFERENCES dilutions(id),
    dilution_steps TEXT NOT NULL DEFAULT '[]',
    dilution_factor DOUBLE PRECISION NOT NULL DEFAULT 1,
    dilution_label TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS sample_analytes(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    preparation_id INTEGER REFERENCES preparations(id) ON DELETE CASCADE,  -- NULL=原样直测(XRF)
    analyte_id INTEGER NOT NULL REFERENCES analytes(id),
    instrument_id INTEGER REFERENCES instruments(id),   -- 录入数据时才确定
    method_id INTEGER REFERENCES methods(id),
    selection TEXT DEFAULT NULL,
    status TEXT DEFAULT 'pending');
-- pending | in_progress | completed | cancelled
CREATE TABLE IF NOT EXISTS results(
    sample_analyte_id INTEGER PRIMARY KEY REFERENCES sample_analytes(id) ON DELETE CASCADE,
    aux TEXT DEFAULT '{}');
-- 回标等辅助数据 {use, expected, measured}
CREATE TABLE IF NOT EXISTS readings(        -- 平行读数: 同一任务测多遍
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    sample_analyte_id INTEGER NOT NULL REFERENCES sample_analytes(id) ON DELETE CASCADE,
    raw DOUBLE PRECISION,
    extra TEXT DEFAULT '{}',   -- 滴定读数的 V/V0/c 等
    use_avg INTEGER DEFAULT 1,  -- 参与平均
    is_final INTEGER DEFAULT 0);
-- 作为该任务终值
CREATE TABLE IF NOT EXISTS reading_create_requests(
    client_reading_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    reading_id INTEGER,
    version TEXT);
CREATE TABLE IF NOT EXISTS instrument_imports(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(source, external_id));
CREATE TABLE IF NOT EXISTS standard_client_submissions(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    client_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    payload_json TEXT NOT NULL DEFAULT '{}',
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(client_id, submission_id));
CREATE TABLE IF NOT EXISTS standard_client_sessions(
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL,
    last_activity DOUBLE PRECISION NOT NULL,
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS standard_client_status(
    client_id TEXT PRIMARY KEY,
    machine_name TEXT NOT NULL DEFAULT '',
    client_version TEXT NOT NULL DEFAULT '',
    instrument_id INTEGER REFERENCES instruments(id) ON DELETE SET NULL,
    network_position TEXT NOT NULL DEFAULT '',
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    seen_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS xrf_analyses(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    sample_id INTEGER REFERENCES samples(id) ON DELETE CASCADE,
    sample_name TEXT DEFAULT '',
    external_id TEXT NOT NULL,
    method TEXT DEFAULT '',
    batch TEXT DEFAULT '',
    analyzed_at TEXT,
    source TEXT DEFAULT 'OXSAS',
    kind TEXT DEFAULT '',
    remark TEXT DEFAULT '',
    options_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(source, external_id));
CREATE TABLE IF NOT EXISTS xrf_values(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES xrf_analyses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    use_report INTEGER DEFAULT 0,
    alt_name TEXT DEFAULT '',   -- UniQuant 名称对的另一口径(元素↔氧化物)
    UNIQUE(analysis_id, name));
CREATE TABLE IF NOT EXISTS xrf_report_targets(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    family TEXT NOT NULL,          -- 元素族, 如 fe
    target TEXT NOT NULL,          -- 报告目标, 如 Fe 或 Fe2O3
    include INTEGER DEFAULT 1,     -- 是否参与最终报告
    allow_conversion INTEGER DEFAULT 1,  -- 直取缺失时是否允许化学计量换算
    UNIQUE(sample_id, family));
CREATE TABLE IF NOT EXISTS uq_analyses(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    external_id TEXT UNIQUE NOT NULL,
    general_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    sample_name TEXT DEFAULT '',
    normalized_sample_name TEXT DEFAULT '',
    analyzed_at TEXT,
    method TEXT DEFAULT '',
    film TEXT,
    processed INTEGER DEFAULT 0,
    sample_id INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    xrf_analysis_id INTEGER REFERENCES xrf_analyses(id) ON DELETE SET NULL,
    job_result TEXT DEFAULT '',
    options_json TEXT DEFAULT '{}',
    job_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS uq_channels(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    uq_analysis_id INTEGER NOT NULL REFERENCES uq_analyses(id) ON DELETE CASCADE,
    external_channel_id TEXT,
    name TEXT DEFAULT '',
    int_cps DOUBLE PRECISION,
    conc DOUBLE PRECISION,
    sigma_conc DOUBLE PRECISION,
    std_err DOUBLE PRECISION,
    calc_bg DOUBLE PRECISION,
    eq_bg DOUBLE PRECISION,
    counting_time DOUBLE PRECISION,
    two_sigma_peak DOUBLE PRECISION,
    overlapping_elements TEXT DEFAULT '',
    is_reported INTEGER DEFAULT 0,
    is_alternative_line INTEGER DEFAULT 0,
    is_fixed_conc INTEGER DEFAULT 0,
    is_forced_element INTEGER DEFAULT 0,
    is_added_to_hundred INTEGER DEFAULT 0,
    payload_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS xrf_client_status(
    client_id TEXT PRIMARY KEY,
    machine_name TEXT DEFAULT '',
    client_version TEXT DEFAULT '',
    state TEXT NOT NULL DEFAULT 'idle',
    current_sample TEXT DEFAULT '',
    current_method TEXT DEFAULT '',
    current_batch TEXT DEFAULT '',
    current_run_id TEXT DEFAULT '',
    current_position TEXT DEFAULT '',
    current_started_at TEXT DEFAULT '',
    message TEXT DEFAULT '',
    seen_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS terminals(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('standard','admin')),
    active INTEGER DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    session_token TEXT DEFAULT '',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS audit_logs(
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id INTEGER,
    username TEXT NOT NULL DEFAULT 'system',
    terminal_id INTEGER,
    terminal_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    before_json TEXT,
    after_json TEXT,
    reason TEXT DEFAULT '',
    ip_address TEXT DEFAULT '',
    created_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS report_overrides(
    sample_id INTEGER PRIMARY KEY REFERENCES samples(id) ON DELETE CASCADE,
    rows_json TEXT NOT NULL DEFAULT '[]',
    updated_by INTEGER REFERENCES users(id),
    updated_at TEXT DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS'));
CREATE TABLE IF NOT EXISTS number_sequences(
    day TEXT PRIMARY KEY,
    last_number INTEGER NOT NULL);
"""


def _install_formula_method_catalog(db):
    """Install missing approved formulas without changing configured methods."""
    next_order = db.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM methods").fetchone()[0]
    for offset, (name, formula, output_unit, note) in enumerate(FORMULA_METHOD_CATALOG):
        target = name.split("-", 1)[0]
        db.execute("""INSERT INTO methods(
            name,itype,formula,constants,note,output_unit,target,active,sort_order)
            SELECT %s,'function',%s,'{}',%s,%s,%s,1,%s
            WHERE NOT EXISTS(SELECT 1 FROM methods WHERE name=%s AND itype='function')""",
            (name, formula, note, output_unit, target, next_order + offset, name))


def _seed_reference_data(db):
    """插入或刷新系统参考数据。"""
    first_run = not db.execute("SELECT COUNT(*) FROM analytes").fetchone()[0]
    db.executemany("""INSERT INTO chemical_elements(
        atomic_number,symbol,name_zh,atomic_weight,is_mass_number) VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT(atomic_number) DO UPDATE SET symbol=excluded.symbol,
        name_zh=excluded.name_zh,atomic_weight=excluded.atomic_weight,
        is_mass_number=excluded.is_mass_number""", CHEMICAL_ELEMENT_SEEDS)
    atomic_weights = {row["symbol"]: float(row["atomic_weight"]) for row in db.execute(
        "SELECT symbol,atomic_weight FROM chemical_elements").fetchall()}
    oxygen_weight = atomic_weights["O"]
    oxide_rows = []
    for formula, name_zh, symbol, element_count, oxygen_count, conventional, note in COMMON_OXIDE_SEEDS:
        element_mass = element_count * atomic_weights[symbol]
        molar_mass = element_mass + oxygen_count * oxygen_weight
        oxide_rows.append((formula, name_zh, symbol, element_count, oxygen_count,
                           molar_mass, element_mass / molar_mass,
                           molar_mass / element_mass, conventional, note))
    db.executemany("""INSERT INTO common_oxides(
        formula,name_zh,element_symbol,element_count,oxygen_count,molar_mass,
        element_mass_fraction,element_to_oxide_factor,is_conventional,note)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(formula) DO UPDATE SET
        name_zh=excluded.name_zh,element_symbol=excluded.element_symbol,
        element_count=excluded.element_count,oxygen_count=excluded.oxygen_count,
        molar_mass=excluded.molar_mass,element_mass_fraction=excluded.element_mass_fraction,
        element_to_oxide_factor=excluded.element_to_oxide_factor,
        is_conventional=excluded.is_conventional,note=excluded.note""", oxide_rows)
    # ---- 种子数据(幂等: 已存在的不会重复插入) ----
    # 全周期表元素(1-83号, 去掉无稳定同位素的 Tc/Pm) + 常规指标
    elements = ("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn "
                "Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Ru Rh Pd Ag Cd "
                "In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Sm Eu Gd Tb Dy Ho Er Tm Yb Lu "
                "Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi").split()
    analytes = elements + ["pH", "TOC", "NPOC", "H+", "OH-", "HCl", "H2SO4",
        "NaClO", "NaOH", "Na2CO3", "NH3", "H2O2", "水分", "COD", "TN",
        "Al2O3", "CaO", "CaCO3", "Ca(OH)2"]
    db.executemany("INSERT INTO analytes(name) VALUES(%s) ON CONFLICT(name) DO NOTHING",
                   [(a,) for a in analytes])
    instruments = [
        ("X射线荧光光谱仪(XRF)", "xrf"),
        ("ICP-OES", "ppm"),
        ("ICP-MS", "ppb"),
        ("原子吸收光谱(AAS)", "ppm"),
        ("TOC分析仪", "ppm"),
        ("pH计", "ph"),
        ("氟离子选择电极", "ppm"),
        ("滴定", "function"),
    ]
    for name, itype in instruments:
        db.execute("INSERT INTO instruments(name,itype) SELECT %s,%s "
                   "WHERE NOT EXISTS(SELECT 1 FROM instruments WHERE name=%s)",
                   (name, itype, name))
    db.execute("UPDATE analytes SET sort_order=id WHERE sort_order IS NULL OR sort_order=0")
    db.execute("UPDATE instruments SET sort_order=id WHERE sort_order IS NULL OR sort_order=0")
    aid = {r[1]: r[0] for r in db.execute("SELECT id,name FROM analytes")}
    iid = {r[1]: r[0] for r in db.execute("SELECT id,name FROM instruments")}
    caps = {
        "X射线荧光光谱仪(XRF)": ("Na Mg Al Si P S Cl K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
            "Ga Ge As Se Br Rb Sr Y Zr Nb Mo Ru Rh Pd Ag Cd In Sn Sb Te I Cs Ba "
            "La Ce Pr Nd Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg "
            "Tl Pb Bi").split(),
        "ICP-OES": ("Li Be B Na Mg Al Si P S K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
            "Ga Ge As Se Rb Sr Y Zr Nb Mo Ru Rh Pd Ag Cd In Sn Sb Te Ba "
            "La Ce Pr Nd Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg "
            "Tl Pb Bi").split(),
        "ICP-MS": ("Li Be B Na Mg Al Si P K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
            "Ga Ge As Se Rb Sr Y Zr Nb Mo Ru Rh Pd Ag Cd In Sn Sb Te Cs Ba "
            "La Ce Pr Nd Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg "
            "Tl Pb Bi").split(),
        "原子吸收光谱(AAS)": ["Li", "Na", "Mg", "K", "Ca", "Cr", "Mn", "Fe", "Co",
                          "Ni", "Cu", "Zn", "Ag", "Cd", "Ba", "Pb"],
        "TOC分析仪": ["TOC", "NPOC"],
        "pH计": ["pH"],
        "氟离子选择电极": ["F"],
        "滴定": ["Fe", "Al", "Ca", "Mg", "Cl", "F", "Cu", "Zn", "Mn", "Cr", "P",
               "Ni", "H+", "OH-", "HCl", "H2SO4", "NaClO", "NaOH", "Na2CO3",
               "NH3", "H2O2", "水分", "COD", "TN", "Al2O3", "CaO", "CaCO3", "Ca(OH)2"],
    }
    for iname, alist in caps.items():
        db.executemany("INSERT INTO instr_analytes VALUES(%s,%s) ON CONFLICT DO NOTHING",
                       [(iid[iname], aid[a]) for a in alist])
    if first_run:
        db.executemany("INSERT INTO dilutions(label,factor) VALUES(%s,%s)", [
            ("原液", 1), ("2倍", 2), ("5倍", 5), ("10倍", 10), ("20倍", 20),
            ("50倍", 50), ("100倍", 100), ("200倍", 200), ("500倍", 500), ("1000倍", 1000)])
        db.execute("INSERT INTO templates(name,is_liquid,dilution_id,xrf,analyte_ids) VALUES(%s,%s,%s,%s,%s)",
                   ("水泥全分析", 0, 1, 1,
                    json.dumps([aid[a] for a in ["Fe", "Al", "Ca", "Mg", "Si", "Ti", "S"]])))
    # 实验室常用二次稀释写法：移取体积/再次定容体积。
    for label, factor in (("5/100", 20), ("5/250", 50),
                          ("10/100", 10), ("10/250", 25)):
        db.execute("""INSERT INTO dilutions(label,factor) SELECT %s,%s
                      WHERE NOT EXISTS(SELECT 1 FROM dilutions WHERE label=%s)""",
                   (label, factor, label))
    for volume_ml in (100, 250):
        db.execute("""INSERT INTO volume_presets(volume_ml) SELECT %s
                      WHERE NOT EXISTS(SELECT 1 FROM volume_presets WHERE volume_ml=%s)""",
                   (volume_ml, volume_ml))
    _install_formula_method_catalog(db)
    db.execute("""INSERT INTO methods(name,itype,formula,constants,note,sort_order)
                   SELECT 'WUNI0820','xrf','', '{}','XRF 定量方法',
                          COALESCE((SELECT MAX(sort_order)+1 FROM methods),1)
                   WHERE NOT EXISTS(SELECT 1 FROM methods WHERE name='WUNI0820')""")
    for sort_order, (code, name, instrument, schema) in enumerate(SPECIAL_METHOD_SEEDS, 1):
        db.execute("""INSERT INTO special_methods(code,name,instrument,schema_json,sort_order)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(code) DO UPDATE SET name=excluded.name,
            instrument=excluded.instrument,schema_json=excluded.schema_json,sort_order=excluded.sort_order""",
            (code, name, instrument, json.dumps(schema, ensure_ascii=False), sort_order))



def _ensure_default_order_template(db):
    """Install one editable universal fallback without disturbing existing templates."""
    default = db.execute(
        "SELECT id FROM result_order_templates WHERE is_default=1 ORDER BY id LIMIT 1").fetchone()
    if default:
        db.execute("UPDATE result_order_templates SET is_default=0 WHERE is_default=1 AND id!=%s",
                   (default["id"],))
        return
    named = db.execute(
        "SELECT id FROM result_order_templates WHERE name='系统默认' ORDER BY id LIMIT 1").fetchone()
    if named:
        db.execute("UPDATE result_order_templates SET is_default=1 WHERE id=%s", (named["id"],))
        return
    items = [row["name"] for row in db.execute(
        "SELECT name FROM analytes ORDER BY sort_order,id").fetchall()]
    db.execute("INSERT INTO result_order_templates(name,items_json,is_default) VALUES(%s,%s,1)",
               ("系统默认", json.dumps(items, ensure_ascii=False)))


def initialize_database(database):
    db = connect_database(database)
    try:
        db.execute(SCHEMA)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_samples_lims_no ON samples(lims_no)")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_sample_analyte_prep
            ON sample_analytes(sample_id, preparation_id, analyte_id)
            WHERE preparation_id IS NOT NULL""")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_sample_analyte_direct
            ON sample_analytes(sample_id, analyte_id)
            WHERE preparation_id IS NULL""")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_xrf_analysis_sample
            ON xrf_analyses(sample_id) WHERE sample_id IS NOT NULL""")
        db.execute("""CREATE INDEX IF NOT EXISTS idx_audit_logs_entity
            ON audit_logs(entity_type, entity_id, action)""")
        _seed_reference_data(db)
        _ensure_default_order_template(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
