using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ToyLims.StandardClient;

public sealed class InstrumentInfo
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public string Itype { get; set; } = "";
    public string InputUnit { get; set; } = "";
    public override string ToString() => $"{Name} · {InputUnit}";
}

public sealed class InstrumentListResponse
{
    public bool Ok { get; set; }
    public string? Error { get; set; }
    public List<InstrumentInfo> Instruments { get; set; } = [];
}

public sealed class ExistingReading
{
    public int Id { get; set; }
    public double? Raw { get; set; }
    [JsonConverter(typeof(FlexibleBooleanConverter))]
    public bool UseAvg { get; set; }
    [JsonConverter(typeof(FlexibleBooleanConverter))]
    public bool IsFinal { get; set; }
}

public sealed class FlexibleBooleanConverter : JsonConverter<bool>
{
    public override bool Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        reader.TokenType switch
        {
            JsonTokenType.True => true,
            JsonTokenType.False => false,
            JsonTokenType.Number => reader.TryGetInt32(out var value) && value != 0,
            JsonTokenType.String => reader.GetString() is "1" or "true" or "True",
            _ => throw new JsonException("布尔字段必须是 true/false 或 0/1"),
        };

    public override void Write(Utf8JsonWriter writer, bool value, JsonSerializerOptions options) =>
        writer.WriteBooleanValue(value);
}

public sealed class InstrumentTask : INotifyPropertyChanged
{
    private string _draftValue = "";
    private bool _selected;
    private bool _showCompleted;
    private bool _authorized;

    public int TaskId { get; set; }
    public string TaskStatus { get; set; } = "";
    public string Analyte { get; set; } = "";
    public string PrepName { get; set; } = "";
    public double? MassG { get; set; }
    public double? VolumeMl { get; set; }
    public string DilutionLabel { get; set; } = "";
    public string InputUnit { get; set; } = "";
    public string SampleStatus { get; set; } = "";
    public List<ExistingReading> Readings { get; set; } = [];

    [JsonIgnore]
    public string ExistingDisplay => Readings.Count == 0
        ? "尚无读数"
        : string.Join(" / ", Readings.Where(item => item.Raw.HasValue).Select(item => item.Raw!.Value.ToString("G10")));

    [JsonIgnore]
    public string PrepDisplay
    {
        get
        {
            var details = new List<string>();
            if (MassG.HasValue) details.Add($"{MassG:G} g");
            if (VolumeMl.HasValue) details.Add($"{VolumeMl:G} mL");
            if (!string.IsNullOrWhiteSpace(DilutionLabel)) details.Add(DilutionLabel);
            return details.Count == 0 ? PrepName : $"{PrepName} · {string.Join(" / ", details)}";
        }
    }

    [JsonIgnore]
    public string DraftValue
    {
        get => _draftValue;
        set
        {
            if (_draftValue == value) return;
            _draftValue = value;
            if (!string.IsNullOrWhiteSpace(value)) Selected = true;
            OnPropertyChanged();
            OnPropertyChanged(nameof(HasDraft));
        }
    }

    [JsonIgnore]
    public bool Selected
    {
        get => _selected;
        set { if (_selected != value) { _selected = value; OnPropertyChanged(); } }
    }

    [JsonIgnore]
    public bool HasDraft => !string.IsNullOrWhiteSpace(DraftValue);
    [JsonIgnore]
    public bool IsCompleted => Readings.Any(item => item.Raw.HasValue);
    [JsonIgnore]
    public bool MainVisible => !IsCompleted || _showCompleted;
    [JsonIgnore]
    public bool FloatingVisible => SampleStatus != "queued" && !IsCompleted;
    [JsonIgnore]
    public bool CanEdit => _authorized && SampleStatus != "queued";
    [JsonIgnore]
    public string TaskStatusDisplay => TaskStatus switch
    {
        "completed" => "已有数据", "in_progress" => "录入中", "cancelled" => "已取消", _ => "待录入",
    };

    public event PropertyChangedEventHandler? PropertyChanged;
    public void SetViewState(bool showCompleted, bool authorized, string sampleStatus)
    {
        _showCompleted = showCompleted;
        _authorized = authorized;
        SampleStatus = sampleStatus;
        OnPropertyChanged(nameof(MainVisible));
        OnPropertyChanged(nameof(FloatingVisible));
        OnPropertyChanged(nameof(CanEdit));
    }
    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public sealed class SampleJob : INotifyPropertyChanged
{
    private bool _showCompleted;
    private bool _authorized;
    public int SampleId { get; set; }
    public string LimsNo { get; set; } = "";
    public string SampleName { get; set; } = "";
    public string Category { get; set; } = "";
    public string SampleStatus { get; set; } = "";
    public ObservableCollection<InstrumentTask> Tasks { get; set; } = [];

    [JsonIgnore]
    public string DisplayName => string.IsNullOrWhiteSpace(LimsNo) ? SampleName : $"{LimsNo}  {SampleName}";
    [JsonIgnore]
    public string AnalytesDisplay => string.Join(" · ", Tasks.Select(task => task.Analyte));
    [JsonIgnore]
    public string SampleStatusDisplay => SampleStatus switch
    {
        "queued" => "已制样 / 未测量", "completed" => "已测量", "partially_done" => "部分完成",
        "measuring" => "测量中", _ => SampleStatus,
    };
    [JsonIgnore]
    public bool CanStartMeasurement => _authorized && SampleStatus == "queued";
    [JsonIgnore]
    public bool MainVisible => Tasks.Any(task => !task.IsCompleted) || _showCompleted || SampleStatus == "queued";
    [JsonIgnore]
    public bool FloatingVisible => Tasks.Any(task => task.FloatingVisible);

    public event PropertyChangedEventHandler? PropertyChanged;
    public void SetViewState(bool showCompleted, bool authorized)
    {
        _showCompleted = showCompleted;
        _authorized = authorized;
        foreach (var task in Tasks) task.SetViewState(showCompleted, authorized, SampleStatus);
        OnPropertyChanged(nameof(CanStartMeasurement));
        OnPropertyChanged(nameof(MainVisible));
        OnPropertyChanged(nameof(FloatingVisible));
    }
    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public sealed class TaskListResponse
{
    public bool Ok { get; set; }
    public string? Error { get; set; }
    public InstrumentInfo? Instrument { get; set; }
    public List<SampleJob> Samples { get; set; } = [];
    public string ServerTime { get; set; } = "";
}

public sealed class ReadingSubmission
{
    public int TaskId { get; set; }
    public double Value { get; set; }
}

public sealed class SubmitResponse
{
    public bool Ok { get; set; }
    public bool Duplicate { get; set; }
    public string? Error { get; set; }
    public string SubmissionId { get; set; } = "";
    public List<ImportedReading> Imported { get; set; } = [];
}

public sealed class AuthorizationResponse
{
    public bool Ok { get; set; }
    public string? Error { get; set; }
    public string Token { get; set; } = "";
    public int ExpiresIn { get; set; }
    public AuthorizedUser? User { get; set; }
}

public sealed class BasicResponse
{
    public bool Ok { get; set; }
    public string? Error { get; set; }
}

public sealed class AuthorizedUser
{
    public int Id { get; set; }
    public string Username { get; set; } = "";
    public string DisplayName { get; set; } = "";
}

public sealed class ImportedReading
{
    public int TaskId { get; set; }
    public int ReadingId { get; set; }
    public string Analyte { get; set; } = "";
    public double Value { get; set; }
}
