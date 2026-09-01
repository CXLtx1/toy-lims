using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

namespace ToyLims.StandardClient;

public partial class MainWindow : Window
{
    private static readonly TimeSpan InactivityLimit = TimeSpan.FromMinutes(10);
    private static readonly TimeSpan TouchInterval = TimeSpan.FromMinutes(1);

    public ObservableCollection<SampleJob> Jobs { get; } = [];

    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(3) };
    private LimsApiClient? _api;
    private InstrumentInfo? _selectedInstrument;
    private AuthorizedUser? _currentUser;
    private FloatingWindow? _floating;
    private DateTime _lastActivityUtc;
    private DateTime _lastTouchUtc;
    private bool _busy;
    private bool _touching;
    private bool _reportingStatus;
    private string _tasksSignature = "";
    private DateTime _lastStatusReportUtc;

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;
        _timer.Tick += Timer_Tick;
    }

    private bool IsAuthorized => _currentUser is not null;
    private bool ShowCompleted => ShowCompletedCheckBox.IsChecked == true;
    private IEnumerable<InstrumentTask> AllTasks => Jobs.SelectMany(job => job.Tasks);
    private Window DialogOwner => _floating is { IsVisible: true, IsActive: true } ? _floating : this;

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        var settings = ClientSettingsStore.Load();
        ServerDisplayText.Text = settings.ServerUrl;
        await ConnectAsync(settings);
        _timer.Start();
        if (_selectedInstrument is not null && await LoginAsync()) ShowFloatingWindow();
    }

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        _timer.Stop();
        if (_floating is { IsLoaded: true }) _floating.CloseFromOwner();
        _api?.Dispose();
    }

    private async Task ConnectAsync(ClientSettings settings)
    {
        if (_busy) return;
        SetBusy(true, "正在连接 LIMS...");
        try
        {
            if (string.IsNullOrWhiteSpace(settings.ServerUrl) || settings.InstrumentId is null)
                throw new InvalidOperationException($"配置文件缺少 ServerUrl 或 InstrumentId：{ClientSettingsStore.FilePath}");
            _api?.Dispose();
            _api = new LimsApiClient(settings.ServerUrl, settings.Token);
            var response = await _api.GetInstrumentsAsync();
            _selectedInstrument = response.Instruments.FirstOrDefault(item => item.Id == settings.InstrumentId);
            if (_selectedInstrument is null)
                throw new InvalidOperationException($"配置的仪器编号 {settings.InstrumentId} 不存在或不支持标准单值录入");
            InstrumentDisplayText.Text = $"{_selectedInstrument.Name} · {_selectedInstrument.InputUnit}";
            ConnectionText.Text = "连接正常";
            ConnectionText.Foreground = new System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromRgb(36, 126, 91));
            SetStatus("设备已连接，请登录用户");
            await ReportClientStatusAsync(force: true);
        }
        catch (Exception ex)
        {
            _selectedInstrument = null;
            InstrumentDisplayText.Text = "配置不可用";
            ConnectionText.Text = "连接失败";
            SetStatus(ex.Message, true);
        }
        finally { SetBusy(false); }
    }

    private async Task<bool> LoginAsync()
    {
        if (_api is null || _selectedInstrument is null || _busy) return false;
        var restoreFloating = _floating is { IsLoaded: true };
        if (restoreFloating) _floating!.Hide();
        var error = "";
        while (true)
        {
            var dialog = new LoginWindow(error) { Owner = this };
            if (dialog.ShowDialog() != true) return false;
            SetBusy(true, "正在验证用户...");
            try
            {
                var response = await _api.AuthorizeAsync(dialog.Password);
                if (response.User is null || string.IsNullOrWhiteSpace(response.Token))
                    throw new InvalidOperationException("LIMS 未返回有效的用户会话");
                _api.SetUserAuthorization(response.Token);
                _currentUser = response.User;
                _lastActivityUtc = _lastTouchUtc = DateTime.UtcNow;
                UserText.Text = string.IsNullOrWhiteSpace(response.User.DisplayName)
                    ? response.User.Username : response.User.DisplayName;
                UserText.Foreground = new System.Windows.Media.SolidColorBrush(
                    System.Windows.Media.Color.FromRgb(36, 126, 91));
                LoginButton.Content = "退出登录";
                FloatingButton.IsEnabled = true;
                ApplyViewState();
                SetStatus($"{UserText.Text} 已登录");
                SetBusy(false);
                await ReportClientStatusAsync(force: true);
                await RefreshTasksAsync(false);
                if (restoreFloating) _floating!.Show();
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                SetBusy(false);
            }
        }
    }

    private async Task LogoutAsync()
    {
        if (_api is not null && IsAuthorized)
        {
            try { await _api.LogoutAsync(); }
            catch { }
        }
        ExpireAuthorization("用户已退出");
    }

    private void ExpireAuthorization(string message)
    {
        _api?.SetUserAuthorization(null);
        _currentUser = null;
        UserText.Text = "未登录";
        UserText.Foreground = new System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(154, 98, 54));
        LoginButton.Content = "用户登录";
        FloatingButton.IsEnabled = false;
        if (_floating is { IsLoaded: true }) _floating.Hide();
        ShowMainWindow();
        ApplyViewState();
        SetStatus(message, true);
        _ = ReportClientStatusAsync(force: true);
    }

    private async void Timer_Tick(object? sender, EventArgs e)
    {
        if (IsAuthorized && DateTime.UtcNow - _lastActivityUtc >= InactivityLimit)
        {
            ExpireAuthorization("连续 10 分钟没有录入操作，请重新登录");
            return;
        }
        await ReportClientStatusAsync();
        if (IsAuthorized && AutoRefreshCheckBox.IsChecked == true && !_busy && _selectedInstrument is not null)
            await RefreshTasksAsync(false);
    }

    private async Task ReportClientStatusAsync(bool force = false)
    {
        if (_api is null || _selectedInstrument is null || _reportingStatus ||
            (!force && DateTime.UtcNow - _lastStatusReportUtc < TimeSpan.FromSeconds(10))) return;
        _reportingStatus = true;
        try
        {
            await _api.ReportStatusAsync(_selectedInstrument.Id);
            _lastStatusReportUtc = DateTime.UtcNow;
        }
        catch { }
        finally { _reportingStatus = false; }
    }

    private async Task RefreshTasksAsync(bool showStatus = true)
    {
        if (_api is null || _selectedInstrument is null || _busy || !IsAuthorized) return;
        var drafts = AllTasks.Where(task => task.HasDraft)
            .ToDictionary(task => task.TaskId, task => (task.DraftValue, task.Selected));
        SetBusy(true, showStatus ? "正在刷新待测任务..." : null);
        try
        {
            var response = await _api.GetTasksAsync(_selectedInstrument.Id);
            var signature = JsonSerializer.Serialize(response.Samples);
            if (signature == _tasksSignature)
            {
                if (showStatus) SetStatus($"已刷新 · 服务器 {response.ServerTime}");
                return;
            }
            _tasksSignature = signature;
            Jobs.Clear();
            foreach (var job in response.Samples)
            {
                foreach (var task in job.Tasks)
                {
                    if (drafts.TryGetValue(task.TaskId, out var draft))
                    {
                        task.DraftValue = draft.DraftValue;
                        task.Selected = draft.Selected;
                    }
                    task.PropertyChanged += Task_PropertyChanged;
                }
                job.SetViewState(ShowCompleted, IsAuthorized);
                Jobs.Add(job);
            }
            UpdateCounts();
            if (showStatus) SetStatus($"已刷新 · 服务器 {response.ServerTime}");
        }
        catch (UnauthorizedAccessException)
        {
            ExpireAuthorization("用户登录已失效，请重新输入密码");
        }
        catch (Exception ex) { SetStatus(ex.Message, true); }
        finally { SetBusy(false); }
    }

    public async Task SubmitDraftsAsync()
    {
        if (_api is null || _selectedInstrument is null || _busy) return;
        if (!IsAuthorized && !await LoginAsync()) return;
        var selected = AllTasks.Where(task => task.CanEdit && task.Selected && task.HasDraft).ToList();
        if (selected.Count == 0)
        {
            PromptWindow.ShowInfo(DialogOwner, "没有可提交内容", "请先填写并勾选至少一条读数。");
            return;
        }
        var readings = new List<ReadingSubmission>();
        foreach (var task in selected)
        {
            if (!double.TryParse(task.DraftValue, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) &&
                !double.TryParse(task.DraftValue, NumberStyles.Float, CultureInfo.CurrentCulture, out value))
            {
                PromptWindow.ShowInfo(DialogOwner, "请检查输入",
                    $"{task.Analyte} 的读数“{task.DraftValue}”不是有效数字。");
                return;
            }
            readings.Add(new ReadingSubmission { TaskId = task.TaskId, Value = value });
        }
        RegisterUserActivity();
        SetBusy(true, "正在提交读数...");
        try
        {
            var response = await _api.SubmitAsync(_selectedInstrument.Id, readings, Guid.NewGuid().ToString("N"));
            foreach (var task in selected) { task.DraftValue = ""; task.Selected = false; }
            SetStatus($"已提交 {response.Imported.Count} 条读数");
            await ReportClientStatusAsync(force: true);
            SetBusy(false);
            await RefreshTasksAsync(false);
        }
        catch (UnauthorizedAccessException)
        {
            ExpireAuthorization("用户登录已失效，草稿已保留，请重新登录后提交");
        }
        catch (Exception ex) { SetStatus(ex.Message, true); }
        finally { SetBusy(false); }
    }

    public async Task RefreshFromFloatingAsync()
    {
        if (!IsAuthorized && !await LoginAsync()) return;
        await RefreshTasksAsync();
    }

    private void Task_PropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is not (nameof(InstrumentTask.DraftValue) or nameof(InstrumentTask.Selected))) return;
        if (sender is InstrumentTask { CanEdit: true }) RegisterUserActivity();
        UpdateCounts();
    }

    private void RegisterUserActivity()
    {
        if (!IsAuthorized) return;
        _lastActivityUtc = DateTime.UtcNow;
        if (!_touching && _lastActivityUtc - _lastTouchUtc >= TouchInterval) _ = TouchAuthorizationAsync();
    }

    private async Task TouchAuthorizationAsync()
    {
        if (_api is null || !IsAuthorized || _touching) return;
        _touching = true;
        try
        {
            await _api.TouchAuthorizationAsync();
            _lastTouchUtc = DateTime.UtcNow;
        }
        catch (UnauthorizedAccessException)
        {
            ExpireAuthorization("用户登录已失效，请重新输入密码");
        }
        catch { }
        finally { _touching = false; }
    }

    private void ApplyViewState()
    {
        foreach (var job in Jobs) job.SetViewState(ShowCompleted, IsAuthorized);
        UpdateCounts();
    }

    private void UpdateCounts()
    {
        SampleCountText.Text = Jobs.Count(job => job.MainVisible).ToString();
        TaskCountText.Text = AllTasks.Count(task => task.MainVisible).ToString();
        DraftCountText.Text = AllTasks.Count(task => task.HasDraft).ToString();
        SubmitButton.IsEnabled = IsAuthorized && !_busy &&
            AllTasks.Any(task => task.CanEdit && task.Selected && task.HasDraft);
        EmptyText.Visibility = Jobs.Any(job => job.MainVisible) ? Visibility.Collapsed : Visibility.Visible;
        _floating?.UpdateSummary();
    }

    private void SetBusy(bool busy, string? message = null)
    {
        _busy = busy;
        if (message is not null) SetStatus(message);
        LoginButton.IsEnabled = !busy;
        FloatingButton.IsEnabled = IsAuthorized && !busy;
        SubmitButton.IsEnabled = IsAuthorized && !busy &&
            AllTasks.Any(task => task.CanEdit && task.Selected && task.HasDraft);
    }

    private void SetStatus(string message, bool error = false)
    {
        StatusText.Text = message;
        StatusText.Foreground = new System.Windows.Media.SolidColorBrush(error
            ? System.Windows.Media.Color.FromRgb(177, 60, 49)
            : System.Windows.Media.Color.FromRgb(68, 111, 131));
    }

    private void ShowFloatingWindow()
    {
        if (_selectedInstrument is null || !IsAuthorized)
        {
            SetStatus("连接 LIMS 并登录用户后才能打开小浮窗", true);
            return;
        }
        if (_floating is { IsLoaded: true })
        {
            if (_floating.WindowState == WindowState.Minimized) _floating.WindowState = WindowState.Normal;
            _floating.Activate();
            return;
        }
        _floating = new FloatingWindow(Jobs, SubmitDraftsAsync, RefreshFromFloatingAsync, ShowMainWindow);
        _floating.Show();
    }

    private void ShowMainWindow()
    {
        Show();
        if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal;
        Activate();
    }

    private async void Login_Click(object sender, RoutedEventArgs e)
    {
        if (IsAuthorized) await LogoutAsync();
        else await LoginAsync();
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        if (!IsAuthorized && !await LoginAsync()) return;
        await RefreshTasksAsync();
    }

    private async void Submit_Click(object sender, RoutedEventArgs e) => await SubmitDraftsAsync();
    private async void ShowFloating_Click(object sender, RoutedEventArgs e)
    {
        if (!IsAuthorized && !await LoginAsync()) return;
        ShowFloatingWindow();
    }
    private void ShowCompleted_Changed(object sender, RoutedEventArgs e)
    {
        if (IsLoaded) ApplyViewState();
    }

    private async void StartSample_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not SampleJob job || _api is null ||
            _selectedInstrument is null || _busy) return;
        if (!IsAuthorized && !await LoginAsync()) return;
        if (!PromptWindow.Confirm(this, "开始测量",
                $"将“{job.DisplayName}”切换为开始测量。", "开始测量")) return;
        RegisterUserActivity();
        SetBusy(true, "正在开始测量...");
        try
        {
            await _api.StartMeasurementAsync(job.SampleId, _selectedInstrument.Id);
            SetStatus($"{job.DisplayName} 已开始测量");
            SetBusy(false);
            await RefreshTasksAsync(false);
        }
        catch (UnauthorizedAccessException)
        {
            ExpireAuthorization("用户登录已失效，请重新输入密码");
        }
        catch (Exception ex) { SetStatus(ex.Message, true); }
        finally { SetBusy(false); }
    }

    private void ClearDrafts_Click(object sender, RoutedEventArgs e)
    {
        if (!AllTasks.Any(task => task.HasDraft)) return;
        if (!PromptWindow.Confirm(this, "清空草稿", "清空当前所有未提交读数？", "清空")) return;
        foreach (var task in AllTasks) { task.DraftValue = ""; task.Selected = false; }
        UpdateCounts();
    }

    private void Draft_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.V && Keyboard.Modifiers.HasFlag(ModifierKeys.Control) && PasteDraftColumn((TextBox)sender))
        {
            e.Handled = true;
            return;
        }
        if (e.Key != Key.Enter) return;
        e.Handled = true;
        var inputs = FindVisualChildren<TextBox>(this)
            .Where(box => box.DataContext is InstrumentTask { CanEdit: true }).ToList();
        var index = inputs.IndexOf((TextBox)sender);
        if (index >= 0 && index + 1 < inputs.Count) inputs[index + 1].Focus();
    }

    private async void Window_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key != Key.Enter || !Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) return;
        e.Handled = true;
        await SubmitDraftsAsync();
    }

    private bool PasteDraftColumn(TextBox current)
    {
        var values = Clipboard.GetText().Split(["\r\n", "\n", "\r", "\t"],
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (values.Length <= 1) return false;
        var inputs = FindVisualChildren<TextBox>(this)
            .Where(box => box.DataContext is InstrumentTask { CanEdit: true }).ToList();
        var index = inputs.IndexOf(current);
        if (index < 0) return false;
        for (var offset = 0; offset < values.Length && index + offset < inputs.Count; offset++)
        {
            inputs[index + offset].Text = values[offset];
            inputs[index + offset].GetBindingExpression(TextBox.TextProperty)?.UpdateSource();
        }
        inputs[Math.Min(index + values.Length, inputs.Count) - 1].Focus();
        return true;
    }

    private static IEnumerable<T> FindVisualChildren<T>(DependencyObject root) where T : DependencyObject
    {
        for (var i = 0; i < System.Windows.Media.VisualTreeHelper.GetChildrenCount(root); i++)
        {
            var child = System.Windows.Media.VisualTreeHelper.GetChild(root, i);
            if (child is T match) yield return match;
            foreach (var nested in FindVisualChildren<T>(child)) yield return nested;
        }
    }
}
