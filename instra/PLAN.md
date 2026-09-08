# insta 方案（MVP：XRF 定量/UniQuant 快速导出）

> 定位：与 toy-lims 共用数据库的**只读浏览 + 快速导出**实验站。技术栈 Vue 3 + TS 前端、Flask 后端。
> 本文档只覆盖第一阶段的**最核心功能**，其余（统计图表、移动端精修、电子签名、样品 Excel 导出等）明确缓做，见文末“缓做清单”。
> UI 全新设计，**不照搬** toy-lims 界面；但内容语义以其为准（见 §3）。

## 1. 核心功能范围

| # | 功能 | 说明 |
|---|------|------|
| 1 | 样品聚合数据浏览 | 网页直观展示样品的最终元素结果与 XRF 最终组成（按元素顺序格式化），**不做 xlsx 导出** |
| 2 | XRF 定量（quant）xlsx 导出 | OXSAS 定量方法（如 0820WUNI）导入数据，多样品并排、CSV 式扁平表 |
| 3 | XRF UniQuant（uq）xlsx 导出 | UQ 数据同样式导出（可选元素/氧化物口径，只出含量） |
| 4 | XRF UniQuant（uq）PDF 导出 | 正式版式完整 PDF 报告（元素版+氧化物版双表，预留签名栏） |

贯穿约束：**元素顺序**一律遵循 toy-lims 的规则（见 §7）。

## 2. 数据源（全部只读，直连现有 PostgreSQL）

| 表 | 用途 |
|---|---|
| `samples` / `sample_analytes` / `results` / `readings` | 样品聚合视图：最终值、平行读数、参与取舍、辅助数据 |
| `xrf_analyses` + `xrf_values` | 定量扫描：`kind='quant'`，`method`、`batch`、`analyzed_at`、`remark`；值表含 `use_report`、`alt_name` |
| `uq_analyses` + `uq_channels` | UniQuant：`general_id`/`job_id`、`film`、`processed`、`method`、`options_json`（关键选项）；通道表含 `conc`、`sigma_conc`、`std_err`、`is_reported` |
| `result_order_templates` | 元素顺序模板（`items_json`，`is_default` 为系统默认） |
| 样品级 `report_order` | 单样品的报告元素顺序覆盖 |
| `chemical_elements` / `common_oxides` | 元素/氧化物参考表：符号、中文名、原子序数、`element_to_oxide_factor` **换算系数在数据库里，不写死在代码** |
| `xrf_report_targets` | 样品级报告口径：按元素族（family）单选目标（元素或某氧化物），含 `include`、`allow_conversion` |

后端用**只读数据库账号**连接，从根上杜绝误写。

## 3. 内容语义要点（读自 toy-lims 现状，仅理解内容，不照搬 UI）

### 3.1 XRF 定量扫描（quant）
- 每条扫描的语义单元：**时间、原始样品名、扫描编号、方法（如 0820WUNI）、批次、LIMS 关联样品（可能未关联）、备注**。
- 最终组成是**混合命名**：单元素（Fe、Cu、Ni…）、氧化物（Al2O3、CaO、SiO2…）、以及原始通道名（如 `Ag Ka 1,2net`）会出现在同一张结果里——排序和导出都必须容忍“不像元素也不像氧化物”的名字（§7 兜底规则）。
- 值统一为质量分数（Wt% 口径）；**0% 值是合法数据**（如 Zn 0%、Sn 0%），导出不得丢弃。
- `use_report` 标记该项是否参与正式报告。

### 3.2 UniQuant（uq）
- 每条 UQ 的语义单元：**样品名、扫描编号（general_id:job_id）、方法（X_UQ）、film、processed（是否再处理）、化学表示模式（元素/氧化物）、分析时间**。
- `options_json` 里有一整套**关键选项**：Case、气氛（真空）、报告限(ppm)、Sector、面积/直径、质量、高度、密度、Shape（Teflon）、Kappa（AnySample）、已知浓度、Rest、DoS 等——PDF 完整版需要呈现，xlsx 不需要。
- 每个通道同时持有两种命名口径：`name`（当前化学表示）与 `alt_name`（另一口径）。注意：**换口径不只是换名**——`conc` 数值以数据本身的化学表示为准，展示另一口径时需按 `common_oxides.element_to_oxide_factor` 做化学计量换算（元素→氧化物 ×factor，反向 ÷factor），toy-lims 已有先例（直取优先、缺项换算、系数可追溯，见 §3.4）。

### 3.3 样品聚合（samples）
- 样品身份字段：**LIMS 编号、来样序号、名称/描述、标签、类型（固体/液体/水质/其他）、状态（测量中/待审核/已审核/作废）、溶样路数、XRF 粗扫标记、登记/制样/开始测量/审核人员与时间**。
- 每个分析项的最终值来自**溶样路**：每路有称样量、定容、稀释、平行份数、仪器分配（滴定/比色/比色公式/ICP-OES/ICP-MS/AAS 等）与平行读数，读数有“参与”取舍；路可能“未录入”。
- 样品可携带 **XRF 最终组成**块（来自关联扫描），展示时有**口径切换**（元素↔氧化物）与**显示单位切换**（% ↔ ppm）的概念——MVP 显示层先按原始口径与原始单位展示，切换交互缓做。
- 元素顺序在 toy-lims 中即有两级：样品自带“顺序模板”，结果页还可临时套用“全局默认”模板——insta 沿用同一规则（§7）。

### 3.4 可移植的领域逻辑（toy-lims 已验证，insta 后端照搬语义）

| 逻辑 | toy-lims 出处 | insta 移植点 |
|---|---|---|
| 元素↔氧化物换算 | `common_oxides` 表 + `_element_to_target_factor`：直取优先、缺项按化学计量换算、未知项目原样保留、系数写进说明可追溯 | `domain/conversion.py`，PDF 双版本与 UQ xlsx 换口径都用它 |
| 报告口径（元素族单选） | `xrf_report_targets` + `_derive_xrf_targets`：同族只保留一个口径、先出现为准、未知项目 `allow_conversion=0` | 样品聚合视图与导出口径解析 |
| 口径冲突警告 | `xrf_warnings`：同族多候选时提示“请明确换算来源” | 聚合视图顶部警告条 |
| 显示单位换算链 | `result_unit_options(unit, density)`：% ↔ ppm ↔ ppb ↔ mg/L 等，液体密度参与换算；样品可存 `result_units` 偏好 | 显示层单位切换（缓做，但 API 先返回 `available_units`） |
| 数值显示格式 | `xrfValueText`：`toPrecision(5)` 去尾零，空值显示 “—” | 前端 `domain/format.ts` |
| XRF 组成排序 | 结果页 XRF 块按**值降序**展示；报告/导出按元素顺序模板 | 网页展示按值降序，导出按 §7 |

## 4. 技术栈（精简版）

**前端 `instra/frontend/`**
- Vue 3.5 + TypeScript + Vite，`<script setup>`
- Naive UI（桌面优先；MVP 只做响应式基线，移动端单独精修缓做）
- Pinia + Vue Router + TanStack Query（列表缓存/秒回）
- dayjs、@vueuse/core

**后端 `instra/backend/`**
- Flask 3 蓝图；复用 `server/db_backend.py` 的连接封装（**仅面向 PostgreSQL**，数据库地址由 `INSTA_DATABASE_URL` / `LIMS_DATABASE_URL` 提供，不支持 SQLite）
- pydantic v2 校验导出参数
- **openpyxl** 生成 xlsx（与 toy-lims 导出同源，样式可控）
- **WeasyPrint** 生成 PDF（HTML 模板 → CSS 分页版式，中文字体、页眉页脚、签名栏）
- waitress + systemd 部署，nginx 发静态文件、`/api` 反代（沿用 labflow 模式，换端口）

## 5. 页面（MVP 三个视图）

1. **样品聚合** `/samples`：样品列表（关键字/日期筛选）→ 展开看聚合视图：样品身份字段、各分析项最终值与溶样路状态（参与/未录入）、关联的 XRF 最终组成块。仅展示，不提供导出。
2. **XRF 数据** `/xrf`：两个 Tab——**定量**与 **UniQuant**。
   - 列表筛选：关键字（样品名 / LIMS 编号 / 方法 / 批次 / 扫描编号）、关联样品、日期范围、分页。
   - 行内信息：时间、类型、原始样品名 + 扫描编号、LIMS 关联状态、方法/批次（UQ 为 film/processed/化学表示模式）、最终结果摘要；可展开看完整组成（定量含混合命名与 0 值；UQ 含关键选项）。
   - 勾选多条 → 导出 xlsx；UQ Tab 额外可导出 PDF。
3. **导出参数抽屉**：元素顺序模板选择（默认系统默认模板）、UQ xlsx 的元素/氧化物口径选择（PDF 恒为双版本完整输出）、文件名。

## 6. API 设计（草案）

```
GET  /api/samples?keyword=&date_from=&date_to=        # 样品列表
GET  /api/samples/<id>/aggregate                      # 聚合视图（身份字段+分析项最终值+溶样路+XRF 组成）
GET  /api/xrf/quant?keyword=&sample_id=&date_from=    # 定量扫描列表
GET  /api/xrf/quant/<id>                              # 定量详情（完整组成+扫描信息）
GET  /api/xrf/uq?keyword=&sample_id=&date_from=       # UQ 列表
GET  /api/xrf/uq/<id>                                 # UQ 详情（完整组成+关键选项）
GET  /api/order-templates                             # 元素顺序模板
POST /api/export/xrf/quant.xlsx   {ids:[], order_template_id}
POST /api/export/xrf/uq.xlsx      {ids:[], order_template_id, basis:"element"|"oxide"}
POST /api/export/xrf/uq.pdf       {ids:[], order_template_id}   # 完整双版本；单样品一份或合并一份，待定
```

导出为 POST 流式返回文件；参数由 pydantic 模型校验。

## 7. 元素顺序规则（与 toy-lims 一致）

1. 导出可选**顺序模板**或**按含量**；定量默认顺序模板，UQ 默认按含量。
2. 顺序模板优先级：样品级 `report_order` 覆盖 > 导出时选定模板 > 系统默认模板（`result_order_templates.is_default=1`）。
3. 按含量导出多样品 xlsx 时，取每个元素在任意所选样品中的最大元素含量降序；单样品 PDF 只按该样品自身元素含量降序，不同 PDF 顺序可不同。
4. 未出现在顺序表里的名字排在已知名字之后，按名称排序——**定量结果中的氧化物名、原始通道名（如 `Ag Ka 1,2net`）都走这条兜底**。
5. UQ 的 `alt_name`（元素↔氧化物另一口径）参与排序匹配：按显示口径的名字去匹配顺序表。
6. 排序由后端统一计算，前端只做模式选择和展示。

## 8. xlsx 格式约定

**统一样式**（定量与 UQ 完全相同）：**首行为结果项名（按 §7 顺序横排做表头），第二行为单位，第 1 列为样品名，每个样品一行**，不合并单元格。

- **定量 xlsx**（一个 Sheet）：样品名 | 项1 | 项2 | …（含量值）
  - 表头原样保留混合命名（元素、氧化物、原始通道名）；**全量输出，不看 `use_report`，0 值照常**。
- **UQ xlsx**（一个 Sheet）：布局与定量完全一致；导出参数 `basis` 选 **元素** 或 **氧化物** 口径（表头用 `name` 或 `alt_name`）；与数据化学表示不同的口径按 `common_oxides` 系数换算数值（直取优先）；**不含** film、general_id、sigma、关键选项等 UQ 详细信息，只出含量值。
- 每个元素/氧化物对共用一个 `% / ppm / ppb` 单位选择；默认按所选扫描中该对的最大绝对值分档：`≥0.1%` 用 `%`，`≥1 ppm` 用 `ppm`，其余用 `ppb`。
- 有效数字为一次导出统一设置（1–8，默认 5）；xlsx 保存换算并按有效数字舍入后的数值型单元格。
- 表头项集合 = 勾选样品的全部结果项按 §7 顺序取并集；某样品没有的项留空。

## 9. UQ PDF 版式

PDF 是**单页紧凑报告**：

- A4 纵向、小页边距；页脚仅保留生成时间与页码。
- 样品信息压缩为两行：样品名、LIMS 编号、方法、原始名、分析时间、膜片。
- 主体三栏比例约 `3 : 3 : 1.35`：左侧氧化物、中间对应元素、右侧 UQ 参数。
- 氧化物与元素逐行严格对应，数值按 `common_oxides` 换算；Cl/Br/Ar/I 等无惯用氧化物的元素在左右两栏重复显示。
- 每行含量后预留窄单位列，与导出抽屉逐对单位设置一致；有效数字使用本次导出统一设置。
- 两个结果栏末尾分别显示原始 Wt% 合计；不显示表格线、换算说明、谱线通道附录或通道备注。
- UQ 参数严格白名单，仅保留中文标签项：化学表示、气氛、报告限、面积、直径/总直径、质量/总质量、高度、密度、阴影损耗、已知浓度、膜片；Shape/Case/Kappa/Sector/Rest/DoS 和内部 link/id 字段不输出。
- 底部保留检测 / 审核 / 批准签字栏；实现为 Jinja2 HTML 模板 → WeasyPrint。

## 10. 目录结构

```
instra/
├── PLAN.md                  # 本文档
├── backend/
│   ├── run.py               # waitress 入口
│   ├── app.py               # Flask app 工厂
│   ├── api/                 # samples / xrf / export 蓝图
│   ├── domain/              # ordering.py（元素顺序）、format.py（单位/报出）
│   ├── export/              # xlsx.py（openpyxl）、uq_pdf.py + templates/uq_report.html
│   └── db.py                # 复用 server/db_backend.py 的只读连接
└── frontend/
    ├── src/api/             # 类型化 API client
    ├── src/stores/
    ├── src/views/           # SamplesView / XrfView
    └── src/components/      # 结果表、筛选栏、导出抽屉
```

## 11. 开发步骤

1. 后端骨架：只读连接 + `/api/samples` + `/api/xrf/*` 列表与详情打通
2. `domain/ordering.py`：移植 toy-lims 元素顺序逻辑（含混合命名兜底）+ 单测
3. 前端三视图（样品聚合 + XRF 双 Tab 列表/详情 + 勾选导出）
4. 定量 xlsx 导出 → UQ xlsx 导出
5. UQ PDF（WeasyPrint 模板）
6. 部署：systemd 单元 + nginx 站点。Ubuntu 上 PDF 依赖：
   `apt install weasyprint fonts-noto-cjk`（WeasyPrint 需要 Pango；PDF 中文字体用 Noto Sans CJK）；
   Windows 本机开发：`pip install weasyprint` 后还需装 GTK3 运行库
   （tschoonj/GTK-for-Windows-Runtime-Environment-Installer 静默安装 `/VERYSILENT`，
   装完新开的终端才能拿到更新后的 PATH；已装 3.24.31 验证通过，中文字体走 Microsoft YaHei）。
   环境变量 `INSTA_DATABASE_URL`（或复用 `LIMS_DATABASE_URL`；缺省用 `backend/db.py` 写死的内网连接）、`INSTA_PORT`（默认 5100）。

## 12. 缓做清单（明确不在本阶段）

- 样品聚合数据的 xlsx 导出；统计图表页（ECharts）
- 移动端独立布局（Vant）与 PWA
- 电子签名（signature_pad 手写签名嵌 PDF / pyHanko 数字签名）
- 网页详情中的口径/单位切换（导出单位与有效数字已实现）
- 认证体系（MVP 内网裸奔或复用 labflow 反代后的一层 Basic Auth，待定）

## 13. 已拍板的决策（2026-09-06）

1. **定量 xlsx 全量导出**：只要有 XRF 数据一视同仁，不看 `use_report`，0 值与通道名项照常输出。
2. **UQ PDF 逐条下载**：勾选 N 条就连续下载 N 份独立 PDF（前端循环逐个请求）。
3. **访问控制**：MVP 暂时裸奔（内网）。
4. **UQ PDF 单页三栏**：氧化物与元素左右对应、双合计，右侧只显示中文参数白名单。
5. **XRF 导出单位与有效数字**：每个元素/氧化物对独立选 `% / ppm / ppb`，两侧共用单位；一次导出统一选择有效数字。
6. **导出排序模式**：UQ 默认按含量、定量默认顺序模板；多样品 xlsx 取跨样品最大元素含量，PDF 每份独立排序。

## 14. 实验星港（2026-09-07）

- 入口 `/observatory`，旧页导航新增「实验星港」；独立石墨黑、拉丝金属视觉，按路由懒加载，不改变原有页面布局。
- 星港用 CSS 3D 甲板、仪器舱体和样品胶囊表现关联。位置仅是可视化布局，不是物理位置；每页 24 个样品，可搜索、按状态/仪器筛选和翻页访问全部样品。
- `/api/overview` 提供全局样品状态计数、仪器任务量、未分配任务、XRF 待关联及最近审计事件。页面每 30 秒同步，不是实时遥测。
- 仪器工作量来自 `sample_analytes`，不表示在线、空闲或正在运行。XRF 按样品独立统计，不能虚构到具体仪器档案的归属。
- 点击样品进入「时间深井」，以穿越机械舱门的运镜衔接；展示当前结果及当前关联对象最近 300 条审计，支持旧值/新值对照，Esc 返回星港。
- 全局时间深井使用 `/api/overview/audits` 的 ID 游标分页加载更早记录；不返回原始快照和 IP。单样品沿用现有审计接口，删除或重新关联的对象可能不在其轨迹中。
- 适配窄屏及 `prefers-reduced-motion`，动画不影响键盘操作，全部请求保持只读。沿用现有内网访问控制边界，部署到公网前必须增加认证。
