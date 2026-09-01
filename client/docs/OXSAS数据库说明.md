# OXSAS 数据库说明（脚本开发参考）

> 整理日期：2026-08-21 ~ 2026-08-24
> 用途：赛默飞 OXSAS 软件（ARL 系列光谱仪）辅助脚本开发的数据库参考
> 验证环境：PFX-9964208（本机），SQL Server 2022 Express (64-bit)

---

## 1. 连接信息

| 项目 | 值 |
|---|---|
| Server | `PFX-9964208`（本机机器名，也可用 `.` 或 `localhost`） |
| 认证 | SQL Server 认证 |
| 账号 | `OXSAS` |
| 密码 | `Oxsas369852147!` |
| 版本 | Microsoft SQL Server 2022 Express |

本机已安装 `sqlcmd`，路径：

```
C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd
```

连接示例（`-C` 信任自签名证书）：

```bash
sqlcmd -S PFX-9964208 -U OXSAS -P 'Oxsas369852147!' -C -d ANALYSES -Q "SELECT 1"
```

Python 脚本建议用 `pyodbc`，连接串：

```
Driver={ODBC Driver 17 for SQL Server};Server=PFX-9964208;Database=ANALYSES;UID=OXSAS;PWD=Oxsas369852147!;TrustServerCertificate=yes;
```

**安全原则：脚本只做 SELECT。禁止 UPDATE/DELETE/INSERT（除非明确测试目的）。OXSAS 运行时会持续写库。**

---

## 2. 数据库总览

| 数据库 | 用途 | 脚本相关度 |
|---|---|---|
| **ANALYSES** | 分析结果主库（结果快照） | ★★★ 最常用 |
| **UniQuant** | UniQuant 无标样半定量任务（选项+强度+浓度全套） | ★★★ UQ 必用 |
| **oxsas_db** | 主配置库：批次、方法、校准、仪器参数（数百张表） | ★★ 批次/方法信息 |
| MasterOxsasDB | 仪器/事件/方法定义（模板性质） | ★ |
| ANAPOOL | 分析池（Analyses/Elements/Programs/Version 4 张表） | ★ |
| ARCHIVE | 归档 | ★ |
| LngMgtOXSAS | 多语言资源 | - |
| IOPProcsClient | 内部过程 | - |

---

## 3. ANALYSES 库（分析结果）

共 10 张表，核心 5 张：

### 3.1 表结构

**Analyses** — 每条分析一行

| 列 | 类型 | 说明 |
|---|---|---|
| ID | int | 主键 |
| Location | nvarchar | 位置 |
| Ana_ID | nvarchar | 时间字符串（如 `21-08-2026 13:58:48.557`） |
| Flags | int | 标志位 |
| AnaDateTime | datetime | 分析时间 |

**Elements** — 元素/组分含量（数值型结果）

| 列 | 类型 | 说明 |
|---|---|---|
| LinkAnalyses | int | → Analyses.ID |
| LinkName | int | → **DisplayName**.ID（注意不是 AttributeName！） |
| Value | float | 含量（%），全精度 |

**Attributes** — 属性（字符型信息：样品名、批次、方法等）

| 列 | 类型 | 说明 |
|---|---|---|
| LinkAnalyses | int | → Analyses.ID |
| LinkName | int | → **AttributeName**.ID |
| Value | nvarchar | 文本值 |

**AttributeName** — 属性名称字典（仅 12 行，ID 1~12）

| ID | Name | 含义 |
|---|---|---|
| 1 | `$AN$` | 分析名 |
| 2 | `$TA$` | 分析类型（如 ARL） |
| 3 | `$BA$` | **Batch（批次名）** |
| 4 | `$ME$` | **Method（方法名）** |
| 5 | `$CA$` | - |
| 6 | `$SI$` | 样品 ID（带 " - " 后缀） |
| 7/8 | `Sample Id1:` / `Sample Id2:` | 用户样品编号 |
| 9 | `Sample Name` | **样品名（查询主键）** |
| 11 | `$SU$` | - |
| 12 | `Sample Description` | 样品描述 |

**DisplayName** — 元素/谱线名称字典（如 `Fe`、`SiO2`、`CuKa`）

其余表 `SearchAnalyses / SearchAttributes / SearchElements / SearchSimple` 是界面查询条件的保存，与分析数据无关。

### 3.2 关系图

```
Analyses (ID)
   ├──< Elements.LinkAnalyses     ──> DisplayName.ID  (元素名)
   └──< Attributes.LinkAnalyses   ──> AttributeName.ID (属性名)
```

### 3.3 常用查询

按样品名找分析：

```sql
SELECT a.LinkAnalyses AS AnaID, an.AnaDateTime
FROM Attributes a
JOIN Analyses an ON an.ID = a.LinkAnalyses
JOIN AttributeName n ON n.ID = a.LinkName
WHERE n.Name = 'Sample Name' AND a.Value LIKE '%RY262494%'
ORDER BY an.AnaDateTime;
```

取某条分析的批次/方法/样品信息：

```sql
SELECT n.Name AS Attr, a.Value
FROM Attributes a JOIN AttributeName n ON n.ID = a.LinkName
WHERE a.LinkAnalyses = 11310;
```

取某条分析的元素结果：

```sql
SELECT d.Name, e.Value
FROM Elements e JOIN DisplayName d ON d.ID = e.LinkName
WHERE e.LinkAnalyses = 11310;
```

按日期范围透视导出（每样品一行）：

```sql
SELECT a.ID, a.AnaDateTime, d.Name, e.Value
FROM Analyses a
JOIN Elements e ON e.LinkAnalyses = a.ID
JOIN DisplayName d ON d.ID = e.LinkName
WHERE a.AnaDateTime >= '2026-08-01'
ORDER BY a.ID;
```

### 3.4 注意事项

- 样品名等属性存 `Attributes`（nvarchar），元素含量存 `Elements`（float），两表都通过 `LinkAnalyses` 关联
- **`Elements.LinkName` 查 `DisplayName`，`Attributes.LinkName` 查 `AttributeName`，不要混用**（ID 空间重叠，错连会得到元素名）
- 定量方法（如 0820WUNI）结果为化合物/元素名（Fe、SiO2…）；X_UQ 方法结果为谱线名（CuKa、ErLa…）且含 `Sum Before Norm.` 行
- 正在采集的最新分析可能暂时没有 Elements 行
- 同一分析可能被复制存储成多条（数值逐位相同），重复数据需按数值去重

---

## 4. oxsas_db 库（批次与方法）

### 4.1 批次结构（4 张表，ID 均为 IDENTITY 自增）

```
Batch_Batches (批次)
   └──< Batch_BatchColls (批次↔集合关联)
          └──> Batch_Collections (集合，Name 格式 = 批次名$集合名)
                 └──< Batch_CollSamples (样品行)
```

**Batch_Batches** 关键列：`ID, Name, StartTime, RepeatCount, Scheduled, AutoDelete, UserEdit, ProtectUserModif, XXXLastModif, ScheduledDays, LastExecutionDate`

**Batch_Collections** 关键列：`ID, Name, BatchColl, UserEdit, Type, XXXLastModif`
- Type：0=分析列表(AnaList)、6=校准、7=程序、9=扫描、11=EPr

**Batch_CollSamples** 关键列（共 29 列）：

| 列 | 说明 |
|---|---|
| LinkCollection | → Batch_Collections.ID |
| Sequence | 样品顺序 |
| Status | 0=待测, 1, 3=进行中, 4=已完成 |
| LinkTask_Schem_Task | 任务类型 → Schem_Task.ID（2=ARL 常规分析） |
| **LinkProg_Prog_Hdr** | **方法 → Prog_Hdr.ID** |
| Cassette | 自动进样器样品位（手动可 NULL） |
| SerialSid | 样品 ID，XML 片段格式：`<1><v>样品名</v><t>1</t><v></v><t>1</t>` |
| SerialMip / SerialMethods / SerialSpotting / SerialChannels / SerialGeneralData | 序列化扩展数据（通常 NULL） |

**Prog_Hdr** — 方法（程序）字典：`ID, Name`。示例：102=X_UQ、103=X_UQ_Helium、149=RC2BC SiICP、171=0820WUNI

**Schem_Task** — 任务类型字典：2=ARL、4=QUANTAS、6=SUS、7=Control、8=TS

### 4.2 查询批次的样品及方法

```sql
SELECT b.Name AS Batch, c.Name AS Collection, p.Name AS Method,
       s.Sequence, s.Status, CAST(s.SerialSid AS nvarchar(max)) AS SampleSID
FROM Batch_Batches b
JOIN Batch_BatchColls bc ON bc.LinkBatch = b.ID
JOIN Batch_Collections c ON c.ID = bc.LinkColl_Batch_Collections
JOIN Batch_CollSamples s ON s.LinkCollection = c.ID
LEFT JOIN Prog_Hdr p ON p.ID = s.LinkProg_Prog_Hdr
WHERE b.Name = '01_TEST'
ORDER BY c.Name, s.Sequence;
```

---

## 5. UniQuant 库（无标样半定量）

界面一次 UQ 计算 = `GeneralData`（选项）+ `JobHdr`（任务）+ `JobChan`（谱线数据）。

### 5.1 表结构

**GeneralData** — 界面左侧全部选项（每次计算一行）

| 列 | 界面字段 |
|---|---|
| SampleId | 样品名（带 " - " 后缀） |
| CreationDate | 计算时间 |
| Chemistry | 化学表示（1=氧化物） |
| LinkShapeHdr | → ShapeHdr（Shape & Impurities，如 Teflon） |
| CaseNb | Case Number |
| LinkKappasHdr | → KappasHdr（Kappa List，如 AnySample） |
| Method | 方法（如 X_UQ） |
| Atmosphere | 环境（0=真空） |
| LinkFilmHdr | → FilmHdr（Film，如 PP 4mu） |
| ReportLevel | 报告限（ppm） |
| Sector / Area / Diameter / GrossDiameter | 扇形盒 / 可视面积 / 直径 |
| Mass / GrossMass / Height / Rho | 质量 / 高度 / 密度 |
| ShadowLoss / KnownConc / Rest / DoS | 阴影损耗 / 已知浓度 / 剩余量 / 稀释 |

**JobHdr** — 任务级结果

| 列 | 说明 |
|---|---|
| Name | 样品名 |
| LinkGeneralData | → GeneralData.ID |
| IsTemplate | 是否模板 |
| StrippedOxygen | 扣除氧（界面 "stripped Oxygen"） |
| PartRho | 计算密度 |
| CO2Conc / Result | - |

**JobChan** — 每条谱线一行（约 127 行/任务），原始+最终结果同表

| 列 | 说明 |
|---|---|
| LinkJobHdr | → JobHdr.ID |
| Name | 谱线名（CuKa、ErLa、BgSi…） |
| **IntCps** | **原始强度（cps）** |
| **Conc / StdErr** | **最终浓度（Wt%）/ 标准误差** |
| IsReported | 是否通过报告条件过滤（界面 Reporting Criteria） |
| LinkChannel / LinkLine | → Channel / Line |
| CalcBg / EqBg / CountingTime / TwoSigmaPeak / OverlappingElements | 背景/计数时间/干扰等中间量 |
| IsAlternativeLine / IsFixedConc / IsForcedElement / IsAddedToHundred | 各种标志 |

辅助字典表：`ShapeHdr`、`FilmHdr`、`KappasHdr`、`Channel`、`Line`、`Material`、`Settings`（全局设置）。

### 5.2 完整查询（样品名 → 选项+结果）

```sql
-- 选项 + 任务
SELECT g.ID, g.SampleId, g.CreationDate, g.Method,
       s.Name AS Shape, k.Name AS KappaList, f.Name AS Film,
       g.Area, g.Diameter, g.Mass, g.Rho, g.Height,
       j.ID AS JobID, j.StrippedOxygen, j.PartRho
FROM GeneralData g
LEFT JOIN ShapeHdr s  ON s.ID = g.LinkShapeHdr
LEFT JOIN KappasHdr k ON k.ID = g.LinkKappasHdr
LEFT JOIN FilmHdr f   ON f.ID = g.LinkFilmHdr
JOIN JobHdr j ON j.LinkGeneralData = g.ID
WHERE g.SampleId LIKE '%RY262488%';

-- 谱线结果（强度 + 浓度）
SELECT jc.Name, jc.IntCps, jc.Conc, jc.StdErr, jc.IsReported
FROM JobChan jc
WHERE jc.LinkJobHdr = <JobID> AND jc.IsReported = 1
ORDER BY jc.Conc DESC;
```

### 5.3 注意事项

- UQ 结果**先在 UniQuant 库**，界面点"保存"后才写快照到 ANALYSES 库；两处参数/加和可能不同（重算过）
- ANALYSES 快照含 `Sum Before Norm.`，UniQuant 库中对应界面底部 "Sum Weight% before normalization"（需自行加和 Conc）
- JobChan 中 `Bg*` 行为背景通道，`Conc` 为 NULL

---

## 6. 本次验证过的操作记录（供回溯）

1. **删除重复分析**（2026-08-21）：RY262494 三条完全相同记录，删除 11281、11298，保留 11309。删除前已备份到 ANALYSES 库的 `Z_Backup_20260821_Analyses / _Elements / _Attributes` 三张表，确认无异常后可 DROP。
2. **直接建批次**（2026-08-24）：在 oxsas_db 创建批次 `CREATE`（Batch_Batches.ID=157，Collection ID=840 `CREATE$AnaList_1`，样品 TEST ID=3623，方法 X_UQ，Status=0），结构照 01_TEST 批次，界面可见。
3. **子表删除顺序**：`Elements`/`Attributes` 有外键指向 `Analyses`，删分析必须先删子表。

---

## 7. 开发建议

- **抓常规结果** → ANALYSES 库（Analyses + Elements + Attributes）
- **抓 UQ 全套（选项/强度/浓度）** → UniQuant 库（GeneralData + JobHdr + JobChan）
- **关联批次/方法定义** → oxsas_db（Batch_* + Prog_Hdr）
- 关联键：样品名。注意 ANALYSES 的 `Sample Name` 不带后缀，`$SI$` 和 UniQuant 的 `SampleId` 带 `" - "` 后缀，匹配时用 LIKE 或 TRIM
- 导出 Excel 推荐 Python：`pyodbc` 取数 → `pandas` 透视 → `openpyxl` 写出
- 所有查询加时间范围条件，ANALYSES.Analyses 已超 6000 行且持续增长
