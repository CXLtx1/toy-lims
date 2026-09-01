namespace Oxsas.AnalysisSheet;

public sealed class TemplateDefinition
{
    public string Name { get; set; } = "";
    public string Workbook { get; set; } = "";
    public string Worksheet { get; set; } = "";
    public string OutputSheetName { get; set; } = "分析单";
    public string DateCell { get; set; } = "";
    public string TimeCell { get; set; } = "";
    public string PrintArea { get; set; } = "";
    public Dictionary<string, ResultFormatDefinition> ResultFormats { get; set; } = [];
    public List<TemplateSlot> Slots { get; set; } = [];
}

public sealed class ResultFormatDefinition
{
    public double Multiplier { get; set; } = 1;
    public string Suffix { get; set; } = "";
    public int? Decimals { get; set; }
}

public sealed class TemplateSlot
{
    public string Name { get; set; } = "";
    public string SampleCell { get; set; } = "";
    public string ElementColumn { get; set; } = "";
    public string ResultColumn { get; set; } = "";
    public int StartRow { get; set; }
    public int EndRow { get; set; }
    public List<string> Elements { get; set; } = [];
}

public sealed class OxsasAnalysis
{
    public int AnalysisId { get; set; }
    public DateTime AnalyzedAt { get; set; }
    public string SampleName { get; set; } = "";
    public string Method { get; set; } = "";
    public Dictionary<string, double> Results { get; } = new(StringComparer.OrdinalIgnoreCase);
    public string Label => $"{SampleName}　{AnalyzedAt:yyyy-MM-dd HH:mm}　{Method}　#{AnalysisId}";
}

public sealed class GenerateSample
{
    public required string Name { get; init; }
    public required IReadOnlyDictionary<string, double> Results { get; init; }
}

public sealed class GenerateRequest
{
    public required TemplateDefinition Template { get; init; }
    public required string TemplatePath { get; init; }
    public required string OutputPath { get; init; }
    public required IReadOnlyList<GenerateSample> Samples { get; init; }
    public required DateTime Date { get; init; }
    public required string SampleTime { get; init; }
}
