using System.Collections.ObjectModel;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Extensions.Configuration;

namespace ToyLims.XrfClient;

public sealed class ClientConfig
{
    public string LimsUrl { get; set; } = "http://127.0.0.1:5000";
    public string OxsasServer { get; set; } = ".";
    public int AutoReadDays { get; set; } = 2;
    public int MaxRecentScans { get; set; } = 50;
    public int MaxBackfillPerRun { get; set; } = 50;
}

public partial class MainWindow : Window
{
    private const string OxsasUser = "OXSAS";
    private const string OxsasPassword = "Oxsas369852147!";
    private readonly ClientConfig _config;
    private readonly ObservableCollection<XrfSample> _samples = [];
    private readonly ObservableCollection<LocalScanRow> _scans = [];
    private readonly Dictionary<string, string> _syncedVersions = [];
    private readonly OxsasReader _oxsasReader = new();
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(5) };
    private LimsApiClient? _limsClient;
    private PendingWindow? _pendingWindow;
    private bool _connected;
    private bool _refreshing;
    private bool _polling;
    private bool _syncing;

    public MainWindow()
    {
        _config = LoadConfig();
        InitializeComponent();
        ScansGrid.ItemsSource = _scans;
        _timer.Tick += async (_, _) =>
        {
            if (!_connected || _polling) return;
            _polling = true;
            try
            {
                if (AutoRefreshCheckBox.IsChecked == true)
                    await RefreshLimsAsync(showErrors: false);
                await SyncRecentAsync(showErrors: false);
                await RefreshRuntimeStatusAsync();
            }
            finally { _polling = false; }
        };
    }

    private static ClientConfig LoadConfig()
    {
        var baseDir = AppContext.BaseDirectory;
        var configuration = new ConfigurationBuilder()
            .SetBasePath(baseDir)
            .AddJsonFile("appsettings.json", optional: true, reloadOnChange: false)
            .Build();
        var config = configuration.Get<ClientConfig>() ?? new ClientConfig();
        config.AutoReadDays = Math.Clamp(config.AutoReadDays, 1, 30);
        config.MaxRecentScans = Math.Clamp(config.MaxRecentScans, 1, 250);
        config.MaxBackfillPerRun = Math.Clamp(config.MaxBackfillPerRun, 1, 250);
        return config;
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        _timer.Start();
        CreateLimsClient();
        if (await RefreshLimsAsync(showErrors: false))
        {
            await SynchronizeHistoryAsync(showErrors: false);
            await SyncRecentAsync(showErrors: false);
            await RefreshRuntimeStatusAsync();
            ShowPendingWindow();
        }
    }

    private void Window_Closed(object? sender, EventArgs e)
    {
        _timer.Stop();
        _pendingWindow?.Close();
        _limsClient?.Dispose();
    }

    private LimsApiClient CreateLimsClient()
    {
        _limsClient?.Dispose();
        _limsClient = new LimsApiClient(_config.LimsUrl, "");
        return _limsClient;
    }

    private async Task<bool> RefreshLimsAsync(bool showErrors)
    {
        if (_refreshing) return _connected;
        _refreshing = true;
        try
        {
            SetStatus("正在读取 LIMS 待测样品……");
            var client = _limsClient ?? CreateLimsClient();
            var response = await client.GetTasksAsync();
            Replace(_samples, response.Samples);
            _connected = true;
            ShowPendingButton.IsEnabled = true;
            LoginStateText.Text = $"已连接 · {_samples.Count} 个待测";
            LoginStateText.Foreground = System.Windows.Media.Brushes.SeaGreen;
            SetStatus($"LIMS 已连接：{_samples.Count} 个待测 XRF 样品");
            LastRefreshText.Text = $"待测刷新 {DateTime.Now:HH:mm:ss}";
            _pendingWindow?.UpdateCount();
            return true;
        }
        catch (Exception ex)
        {
            _connected = false;
            ShowPendingButton.IsEnabled = false;
            LoginStateText.Text = "连接失败";
            LoginStateText.Foreground = System.Windows.Media.Brushes.Firebrick;
            SetStatus("LIMS 连接失败：" + ex.Message, true);
            if (showErrors)
                MessageBox.Show(ex.Message, "LIMS 连接失败", MessageBoxButton.OK, MessageBoxImage.Warning);
            return false;
        }
        finally
        {
            _refreshing = false;
        }
    }

    private async Task SendHeartbeatAsync(
        string state, string message = "", string sample = "",
        string method = "", string batch = "", string runId = "",
        string position = "", string startedAt = "")
    {
        if (_limsClient is null) return;
        var version = typeof(MainWindow).Assembly.GetName().Version?.ToString() ?? "";
        await _limsClient.PostStatusAsync(
            state,
            currentSample: sample,
            currentMethod: method,
            currentBatch: batch,
            currentRunId: runId,
            currentPosition: position,
            currentStartedAt: startedAt,
            message: message,
            version: version);
    }

    private async Task RefreshRuntimeStatusAsync()
    {
        try
        {
            var current = await _oxsasReader.ReadRuntimeStatusAsync(
                _config.OxsasServer, OxsasUser, OxsasPassword);
            if (current?.IsRunning == true)
            {
                await SendHeartbeatAsync("reading",
                    $"位置 {current.Position} · {current.XRayKv:F1} kV / {current.XRayMa:F1} mA",
                    current.SampleName, current.Method, current.Batch, current.RunId,
                    current.Position, current.ActivityAt.ToString("yyyy-MM-dd HH:mm:ss"));
            }
            else
            {
                await SendHeartbeatAsync("idle", "仪器待机");
            }
        }
        catch (Exception ex)
        {
            await SendHeartbeatAsync("error", "实时状态读取失败：" + ex.Message);
        }
    }

    private async void Connect_Click(object sender, RoutedEventArgs e)
    {
        CreateLimsClient();
        if (await RefreshLimsAsync(showErrors: true))
        {
            await SynchronizeHistoryAsync(showErrors: true);
            await SyncRecentAsync(showErrors: false);
            await RefreshRuntimeStatusAsync();
            ShowPendingWindow();
        }
    }

    private void ShowPending_Click(object sender, RoutedEventArgs e) => ShowPendingWindow();

    private void ShowPendingWindow()
    {
        if (!_connected) return;
        if (_pendingWindow is null)
        {
            _pendingWindow = new PendingWindow(_samples);
            _pendingWindow.Closed += (_, _) => _pendingWindow = null;
            _pendingWindow.Show();
        }
        else
        {
            if (_pendingWindow.WindowState == WindowState.Minimized)
                _pendingWindow.WindowState = WindowState.Normal;
            _pendingWindow.Activate();
        }
    }

    private async Task SynchronizeHistoryAsync(bool showErrors)
    {
        if (_syncing || !_connected || _limsClient is null) return;
        _syncing = true;
        try
        {
            var state = await _limsClient.GetSyncStateAsync();
            var knownOrdinary = state.OrdinaryIds.ToHashSet(StringComparer.OrdinalIgnoreCase);
            var knownUq = state.UqIds.ToHashSet(StringComparer.OrdinalIgnoreCase);
            var ordinaryAfter = 0;
            var uqAfter = 0;
            var scanned = 0;
            var total = 0;
            var maxBackfillPerRun = _config.MaxBackfillPerRun;
            while (true)
            {
                SetStatus($"正在核对普通定量历史：已扫描 {scanned} 条，已补传 {total} 条……");
                var batch = await _oxsasReader.ReadQuantitativeAfterAsync(
                    _config.OxsasServer, OxsasUser, OxsasPassword, ordinaryAfter);
                if (batch.Count == 0) break;
                var missing = batch.Where(item => !knownOrdinary.Contains(item.AnalysisId.ToString())).ToList();
                if (missing.Count > 0 && total < maxBackfillPerRun)
                {
                    var remaining = maxBackfillPerRun - total;
                    await _limsClient.ImportBatchAsync(missing.Take(remaining).ToList());
                }
                scanned += batch.Count;
                total += missing.Count;
                ordinaryAfter = batch.Max(item => item.AnalysisId);
                if (total >= maxBackfillPerRun) break;
            }
            while (true)
            {
                SetStatus($"正在核对人工完成的 UQ 历史：已扫描 {scanned} 条，已补传 {total} 条……");
                var batch = await _oxsasReader.ReadUqAfterAsync(
                    _config.OxsasServer, OxsasUser, OxsasPassword, uqAfter);
                if (batch.Count == 0) break;
                var missing = batch.Where(item => !knownUq.Contains(
                    $"{item.GeneralDataId}:{item.JobId}")).ToList();
                if (missing.Count > 0 && total < maxBackfillPerRun)
                {
                    var remaining = maxBackfillPerRun - total;
                    await _limsClient.ImportUqBatchAsync(missing.Take(remaining).ToList());
                }
                scanned += batch.Count;
                total += missing.Count;
                uqAfter = batch.Max(item => item.GeneralDataId);
                if (total >= maxBackfillPerRun) break;
            }
            SetStatus($"历史扫描核对完成：扫描 {scanned} 条，本次补传 {total} 条（单次最多 {maxBackfillPerRun} 条）");
        }
        catch (Exception ex)
        {
            SetStatus("历史补传失败：" + ex.Message, true);
            await SendHeartbeatAsync("error", "历史补传失败：" + ex.Message);
            if (showErrors)
                MessageBox.Show(ex.Message, "历史补传失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally { _syncing = false; }
    }

    private async Task SyncRecentAsync(bool showErrors)
    {
        if (_syncing || !_connected || _limsClient is null) return;
        _syncing = true;
        try
        {
            var ordinary = await _oxsasReader.ReadQuantitativeAsync(
                _config.OxsasServer, OxsasUser, OxsasPassword, DateTime.Now.AddDays(-_config.AutoReadDays),
                _config.MaxRecentScans);
            var uq = await _oxsasReader.ReadUqAsync(
                _config.OxsasServer, OxsasUser, OxsasPassword, DateTime.Now.AddDays(-_config.AutoReadDays),
                _config.MaxRecentScans);
            var ordinaryChanged = ordinary.Where(item => Changed(
                $"q:{item.AnalysisId}", new { item.SampleName, item.Method, item.Batch, item.Results })).ToList();
            var uqChanged = uq.Where(item => Changed(
                $"uq:{item.GeneralDataId}:{item.JobId}", new { item.Options, item.Job, item.Results })).ToList();
            var ordinaryResponse = ordinaryChanged.Count > 0
                ? await _limsClient.ImportBatchAsync(ordinaryChanged) : null;
            var uqResponse = uqChanged.Count > 0
                ? await _limsClient.ImportUqBatchAsync(uqChanged) : null;
            RememberLinked(ordinaryChanged, ordinaryResponse, item => $"q:{item.AnalysisId}",
                item => new { item.SampleName, item.Method, item.Batch, item.Results });
            RememberLinked(uqChanged, uqResponse, item => $"uq:{item.GeneralDataId}:{item.JobId}",
                item => new { item.Options, item.Job, item.Results });
            var rows = new List<LocalScanRow>();
            rows.AddRange(ordinary.Select(item => new LocalScanRow
            {
                Type = "普通定量", AnalyzedAt = item.AnalyzedAt, SampleName = item.SampleName,
                Method = item.Method, Detail = item.Batch.Length > 0 ? $"批次 {item.Batch}" : "—",
                ResultsText = item.ResultsText,
                SyncStatus = ResponseStatus(ordinaryChanged, ordinaryResponse, item),
            }));
            rows.AddRange(uq.Select(item => new LocalScanRow
            {
                Type = "UQ", AnalyzedAt = item.AnalyzedAt, SampleName = item.SampleName,
                Method = item.Options.Method, Detail = $"{item.ChemistryText} · {item.OptionsSummary}",
                ResultsText = item.ResultsSummary,
                SyncStatus = ResponseStatus(uqChanged, uqResponse, item),
            }));
            Replace(_scans, rows.OrderByDescending(item => item.AnalyzedAt));
            ScanCountText.Text = $"{_scans.Count} 条最近扫描";
            LastRefreshText.Text = $"自动同步 {DateTime.Now:HH:mm:ss}";
            SetStatus($"自动同步完成：普通定量 {ordinaryChanged.Count} 条，UQ {uqChanged.Count} 条");
        }
        catch (Exception ex)
        {
            SetStatus("自动同步失败：" + ex.Message, true);
            if (showErrors)
                MessageBox.Show(ex.Message, "自动同步失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally { _syncing = false; }
    }

    private bool Changed(string key, object value)
    {
        var version = Version(value);
        if (_syncedVersions.TryGetValue(key, out var previous) && previous == version) return false;
        return true;
    }

    private void RememberLinked<T>(IReadOnlyList<T> submitted, BatchImportResponse? response,
        Func<T, string> key, Func<T, object> value)
    {
        if (response is null) return;
        for (var index = 0; index < submitted.Count; index++)
        {
            var result = response.Results.ElementAtOrDefault(index);
            if (result?.Ok == true && (result.Matched || result.SampleLocked))
                _syncedVersions[key(submitted[index])] = Version(value(submitted[index]));
        }
    }

    private static string Version(object value) =>
        Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(value)));

    private static string ResponseStatus<T>(IReadOnlyList<T> changed, BatchImportResponse? response,
        T item)
    {
        var index = changed.ToList().IndexOf(item);
        if (index < 0) return "已同步";
        var result = response?.Results.ElementAtOrDefault(index);
        if (result is null) return "同步完成";
        if (!result.Ok) return "失败：" + result.Error;
        if (result.SampleLocked) return "已保存 · 样品锁定";
        return result.Matched ? "已同步并关联" : "已同步 · 未登记";
    }

    private async void ReadOxsas_Click(object sender, RoutedEventArgs e)
    {
        await SynchronizeHistoryAsync(showErrors: true);
        await SyncRecentAsync(showErrors: true);
        await RefreshRuntimeStatusAsync();
    }

    private static void Replace<T>(ObservableCollection<T> target, IEnumerable<T> values)
    {
        target.Clear();
        foreach (var value in values) target.Add(value);
    }

    private void SetStatus(string message, bool error = false)
    {
        StatusText.Text = message;
        StatusText.Foreground = error
            ? System.Windows.Media.Brushes.Firebrick
            : System.Windows.Media.Brushes.DarkSlateGray;
    }
}
