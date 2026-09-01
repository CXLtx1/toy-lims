using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace ToyLims.StandardClient;

public partial class FloatingWindow : Window
{
    public ObservableCollection<SampleJob> Jobs { get; }
    private readonly Func<Task> _submit;
    private readonly Func<Task> _refresh;
    private readonly Action _showMain;
    private bool _closeFromOwner;

    public FloatingWindow(ObservableCollection<SampleJob> jobs, Func<Task> submit,
        Func<Task> refresh, Action showMain)
    {
        Jobs = jobs;
        _submit = submit;
        _refresh = refresh;
        _showMain = showMain;
        InitializeComponent();
        DataContext = this;
        Jobs.CollectionChanged += Jobs_CollectionChanged;
        UpdateSummary();
    }

    public void UpdateSummary()
    {
        if (!IsInitialized) return;
        var visibleJobs = Jobs.Where(job => job.FloatingVisible).ToList();
        var tasks = visibleJobs.SelectMany(job => job.Tasks).Where(task => task.FloatingVisible).ToList();
        var draftCount = tasks.Count(task => task.HasDraft);
        SummaryText.Text = $"{visibleJobs.Count} 个样品 · {tasks.Count} 个项目 · {draftCount} 条草稿";
        EmptyText.Visibility = visibleJobs.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        SubmitButton.IsEnabled = tasks.Any(task => task.CanEdit && task.Selected && task.HasDraft);
    }

    public void CloseFromOwner()
    {
        _closeFromOwner = true;
        Close();
    }

    private void Jobs_CollectionChanged(object? sender, NotifyCollectionChangedEventArgs e) => UpdateSummary();
    private async void Submit_Click(object sender, RoutedEventArgs e) => await _submit();
    private async void Refresh_Click(object sender, RoutedEventArgs e) => await _refresh();
    private void Main_Click(object sender, RoutedEventArgs e) => _showMain();

    private void Window_Closing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        Jobs.CollectionChanged -= Jobs_CollectionChanged;
        if (!_closeFromOwner) _showMain();
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
            .Where(box => box.DataContext is InstrumentTask { CanEdit: true, FloatingVisible: true }).ToList();
        var index = inputs.IndexOf((TextBox)sender);
        if (index >= 0 && index + 1 < inputs.Count) inputs[index + 1].Focus();
    }

    private async void Window_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key != Key.Enter || !Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) return;
        e.Handled = true;
        await _submit();
    }

    private bool PasteDraftColumn(TextBox current)
    {
        var values = Clipboard.GetText().Split(["\r\n", "\n", "\r", "\t"],
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (values.Length <= 1) return false;
        var inputs = FindVisualChildren<TextBox>(this)
            .Where(box => box.DataContext is InstrumentTask { CanEdit: true, FloatingVisible: true }).ToList();
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
