namespace ToyLims.XrfClient;

public sealed class XrfTask
{
    public int TaskId { get; set; }
    public string TaskStatus { get; set; } = "";
    public int AnalyteId { get; set; }
    public string Analyte { get; set; } = "";
}

public sealed class XrfSample
{
    public int SampleId { get; set; }
    public string LimsNo { get; set; } = "";
    public string SampleName { get; set; } = "";
    public string CopyName { get; set; } = "";
    public string Category { get; set; } = "";
    public string SampleStatus { get; set; } = "";
    public int? MethodId { get; set; }
    public string MethodName { get; set; } = "";
    public string XrfReportItems { get; set; } = "";
    public List<XrfTask> Tasks { get; set; } = [];

    public string AnalytesText => string.Join(", ", Tasks.Select(task =>
        task.TaskStatus == "completed" ? $"{task.Analyte}✓" : task.Analyte));
    public string AnalytesDisplay => AnalytesText.Length > 0 ? AnalytesText : "检测项目待配置";
    public string MethodDisplay => MethodName.Length > 0 ? MethodName : "未指定方法";
}

public sealed class XrfTasksResponse
{
    public bool Ok { get; set; }
    public string Error { get; set; } = "";
    public DateTime? ServerTime { get; set; }
    public List<XrfSample> Samples { get; set; } = [];
}

public sealed class OxsasResult
{
    public string Name { get; set; } = "";
    public double Value { get; set; }
}

public sealed class OxsasAnalysis
{
    public int AnalysisId { get; set; }
    public DateTime AnalyzedAt { get; set; }
    public string SampleName { get; set; } = "";
    public string Method { get; set; } = "";
    public string Batch { get; set; } = "";
    public List<OxsasResult> Results { get; set; } = [];
    public string ResultsText => string.Join("  ", Results
        .OrderByDescending(result => result.Value)
        .Select(result => $"{result.Name}={result.Value:G6}"));
}

public sealed class UqOptions
{
    public int Id { get; set; }
    public string SampleId { get; set; } = "";
    public DateTime CreationDate { get; set; }
    public string Remark { get; set; } = "";
    public int? Chemistry { get; set; }
    public int? LinkShapeHdr { get; set; }
    public int? CaseNb { get; set; }
    public int? LinkKappasHdr { get; set; }
    public string Method { get; set; } = "";
    public int? Atmosphere { get; set; }
    public int? LinkFilmHdr { get; set; }
    public double? ReportLevel { get; set; }
    public double? Sector { get; set; }
    public double? Area { get; set; }
    public double? Diameter { get; set; }
    public double? GrossDiameter { get; set; }
    public double? Mass { get; set; }
    public double? GrossMass { get; set; }
    public double? Rho { get; set; }
    public double? Height { get; set; }
    public double? ShadowLoss { get; set; }
    public double? KnownConc { get; set; }
    public int? LinkKnownMaterial { get; set; }
    public double? Rest { get; set; }
    public int? LinkRestMaterial { get; set; }
    public double? DoS { get; set; }
    public int? LinkDoSMaterial { get; set; }
    public string Shape { get; set; } = "";
    public string Kappas { get; set; } = "";
    public string Film { get; set; } = "";
}

public sealed class UqJob
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public int LinkGeneralData { get; set; }
    public bool? IsTemplate { get; set; }
    public string Result { get; set; } = "";
    public double? PartRho { get; set; }
    public double? CO2Conc { get; set; }
    public double? StrippedOxygen { get; set; }
}

public sealed class UqChannel
{
    public int Id { get; set; }
    public int LinkJobHdr { get; set; }
    public int? LinkChannel { get; set; }
    public string Name { get; set; } = "";
    public int? LinkLine { get; set; }
    public double? IntCps { get; set; }
    public double? CalcBg { get; set; }
    public string BgToken { get; set; } = "";
    public double? YldC { get; set; }
    public double? MuComPerYield { get; set; }
    public double? YldE { get; set; }
    public double? MuEffPerYield { get; set; }
    public double? CountingTime { get; set; }
    public double? Conc { get; set; }
    public double? SigmaConc { get; set; }
    public int? LinkMaterial { get; set; }
    public int? MaterialType { get; set; }
    public bool? IsAlternativeLine { get; set; }
    public int? IsFixedIntBg { get; set; }
    public bool? IsFixedConc { get; set; }
    public bool? IsForcedElement { get; set; }
    public double? BlankInt { get; set; }
    public double? SelfAbsorptionRatio { get; set; }
    public double? SubstrateInt { get; set; }
    public double? StdErr { get; set; }
    public double? TotalCorr { get; set; }
    public double? EqBg { get; set; }
    public double? TwoSigmaPeak { get; set; }
    public string OverlappingElements { get; set; } = "";
    public bool? IsAddedToHundred { get; set; }
    public double? SpecifiedConc { get; set; }
    public bool? IsReported { get; set; }
}

public sealed class UqAnalysis
{
    public UqOptions Options { get; set; } = new();
    public UqJob Job { get; set; } = new();
    public List<OxsasResult> Results { get; set; } = [];
    public List<UqChannel> Channels { get; set; } = [];
    public string SyncStatus { get; set; } = "待同步";

    public int GeneralDataId => Options.Id;
    public int JobId => Job.Id;
    public DateTime AnalyzedAt => Options.CreationDate;
    public string SampleName => System.Text.RegularExpressions.Regex.Replace(
        Options.SampleId.Trim(), @"\s+-\s*(?:\(\d+\))?\s*$", "").Trim();
    public bool Processed
    {
        get
        {
            var film = Options.Film.ToLowerInvariant()
                .Replace(" ", "").Replace("µ", "u").Replace("μ", "u");
            return film is "pp4mu" or "pp4um";
        }
    }
    public string ProcessedText => Processed ? "已人工处理" : "未处理";
    public string ChemistryText => Options.Chemistry == 1 ? "氧化物" : "元素";
    public string OptionsSummary => string.Join(" · ", new[]
    {
        Options.Shape.Length > 0 ? $"Shape {Options.Shape}" : "",
        Options.Kappas.Length > 0 ? $"Kappa {Options.Kappas}" : "",
        Options.ReportLevel is not null ? $"报告限 {Options.ReportLevel:G6}" : "",
        Options.Rho is not null ? $"ρ {Options.Rho:G6}" : "",
    }.Where(value => value.Length > 0));
    public string ResultsSummary
    {
        get
        {
            var values = Results.OrderByDescending(result => result.Value)
                .Take(8)
                .Select(result => $"{result.Name}={result.Value:G6}");
            var summary = string.Join("  ", values);
            return Job.Result.Length == 0 ? summary : $"{Job.Result}  {summary}".Trim();
        }
    }
}

public sealed class LocalScanRow
{
    public string Type { get; set; } = "";
    public DateTime AnalyzedAt { get; set; }
    public string SampleName { get; set; } = "";
    public string Method { get; set; } = "";
    public string Detail { get; set; } = "";
    public string ResultsText { get; set; } = "";
    public string SyncStatus { get; set; } = "";
}

public sealed class XrfSyncStateResponse
{
    public bool Ok { get; set; }
    public string Error { get; set; } = "";
    public int OrdinaryAfter { get; set; }
    public int UqAfterGeneral { get; set; }
    public List<string> OrdinaryIds { get; set; } = [];
    public List<string> UqIds { get; set; } = [];
}

public sealed class BatchImportResponse
{
    public bool Ok { get; set; }
    public string Error { get; set; } = "";
    public int Imported { get; set; }
    public List<ImportResponse> Results { get; set; } = [];
}

public sealed class UqImportResponse
{
    public bool Ok { get; set; }
    public bool Duplicate { get; set; }
    public bool Processed { get; set; }
    public bool Matched { get; set; }
    public bool SampleLocked { get; set; }
    public int? UqAnalysisId { get; set; }
    public int? SampleId { get; set; }
    public string NormalizedSampleName { get; set; } = "";
    public string Error { get; set; } = "";
    public bool Linked => Matched;
}

public sealed class OxsasRuntimeStatus
{
    public int BatchId { get; set; }
    public int CollectionId { get; set; }
    public int RowId { get; set; }
    public DateTime ServerTime { get; set; }
    public DateTime ActivityAt { get; set; }
    public string Batch { get; set; } = "";
    public string Collection { get; set; } = "";
    public string SampleName { get; set; } = "";
    public string Method { get; set; } = "";
    public string Cassette { get; set; } = "";
    public int Sequence { get; set; }
    public double XRayKv { get; set; }
    public double XRayMa { get; set; }
    public double StandbyKv { get; set; }
    public double StandbyMa { get; set; }

    // OXSAS 不持久化当前行；运行状态由最近活动队列和实时高压共同确认。
    public bool IsRunning => ServerTime - ActivityAt <= TimeSpan.FromMinutes(20)
        && (XRayKv > StandbyKv + 0.5 || XRayMa > StandbyMa + 0.5);
    public string Position => int.TryParse(Cassette, out var value)
        ? (value % 1000).ToString() : Cassette;
    public string RunId => $"{BatchId}:{CollectionId}:{RowId}";
}

public sealed class ImportResponse
{
    public bool Ok { get; set; }
    public bool Duplicate { get; set; }
    public bool Matched { get; set; }
    public bool SampleLocked { get; set; }
    public string Error { get; set; } = "";
    public List<ImportedResult> Imported { get; set; } = [];
    public List<SkippedResult> Skipped { get; set; } = [];
}

public sealed class ImportedResult
{
    public string Name { get; set; } = "";
    public double Value { get; set; }
}

public sealed class SkippedResult
{
    public string Name { get; set; } = "";
    public string Reason { get; set; } = "";
}
