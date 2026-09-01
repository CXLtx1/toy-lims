# OXSAS 实时状态验证

验证日期：2026-08-28

## 结论

`ANALYSES.Attributes` 只保存已经形成结果快照的样品。正在测量时，`ANALYSES`、`ARCHIVE` 和 `ANAPOOL` 都不会提前出现当前样品，因此不能用最新分析记录显示实时状态。

OXSAS 没有把“当前行”作为独立字段持久化。切换样品时软件执行以下动作：

1. 将刚完成的 `Batch_CollSamples.Status` 更新为 `4`。
2. 更新所属 `Batch_Collections.XXXLastModif`，该时间与下一样品开始时间相差约 1 秒。
3. 重新读取批次及集合，在进程内选择该集合中按 `Sequence` 排序的第一条 `Status=0` 行。
4. 当前样品完成后才写入 `ANALYSES`/`ARCHIVE`；如果是 UniQuant，还会同步写入 `UniQuant.GeneralData/JobHdr/JobChan`。

因此原说明中的状态解释需要修正：实测 `Status=0` 同时用于待测和当前运行行，`4` 表示已完成；旧批次可长期残留 `1/3`，不能据此判断实时运行。

## 连续验证

- `15:41:20` 开始 `TY260908`：批次 `01_TEST`、集合 621 的首条 `Status=0` 为 `TY260908`。
- `15:56:49` 完成后该行变为 `4`，集合修改时间更新；首条 `Status=0` 自动变为 `TY260910`，与 OXSAS 界面一致。
- 新客户端查询实测返回：`TY260910 / 01_TEST / X_UQ / 位置 106 / 60.0 kV / 39.9 mA / running=true`。

同名不能标识一次运行。`TY260910` 首次完成后为队列行 ID `1555`、Sequence `12`、Status `4`；重新测量生成新行 ID `1556`、Sequence `13`、Status `0`。全库没有其他表或外键引用该行 ID，因此客户端使用 `BatchID:CollectionID:RowID` 作为运行实例编号，本次为 `48:621:1556`；样品名只用于显示。

## 仪器状态

实时仪器工作信号在 `oxsas_db.dbo.Gen_InstrState`：

- `X-ray voltage`、`X-ray current`：当前高压和电流；本次测量约为 `60 kV / 40 mA`。
- `enter kV`、`enter mA`：待机设定；当前设备为 `40 kV / 20 mA`。
- `X-ray power-supply state/mode`、腔体压力等也在该表实时更新。

推荐判定：选择 `XXXLastModif` 最新且仍含 `Status=0` 的分析集合，取最小 `Sequence` 行作为当前候选；同时要求集合在一个最长方法周期内有活动，并且实时高压或电流高于待机值。样品名从 `SerialSid` 的第一个 `<v>` 读取，方法连接 `Prog_Hdr`，批次连接 `Batch_Batches`。这能得到当前样品、方法、批次、位置和开始时间。

## 探索范围

- Python 只读扫描了 8 个数据库中的 1033 个文本/XML 列；运行中的 `TY260910` 只在 `Batch_CollSamples.SerialSid` 命中。
- 扫描 16 个二进制/图像列，没有发现样品名副本。
- `tempdb` 没有 OXSAS 用户临时表。
- SQL Server 游标只用于 `ANALYSES.Ana_ID` 查重，不保存批处理当前位置。
- `IOPProcsClient.OxsasLogs`、`ProcsHistory` 当前为空。

当前行最终由 OXSAS 进程内存管理。如果操作者脱离队列顺序手工选择后续行，数据库只能重建队列候选；绝对精确状态需要厂家运行接口或读取 OXSAS 界面。
