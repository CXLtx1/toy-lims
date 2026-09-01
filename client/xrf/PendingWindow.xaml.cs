using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.Windows;

namespace ToyLims.XrfClient;

public partial class PendingWindow : Window
{
    private readonly ObservableCollection<XrfSample> _samples;

    public PendingWindow(ObservableCollection<XrfSample> samples)
    {
        InitializeComponent();
        _samples = samples;
        SamplesList.ItemsSource = samples;
        _samples.CollectionChanged += Samples_CollectionChanged;
        Closed += (_, _) => _samples.CollectionChanged -= Samples_CollectionChanged;
        UpdateCount();
    }

    private void Samples_CollectionChanged(object? sender, NotifyCollectionChangedEventArgs e) =>
        UpdateCount();

    public void UpdateCount()
    {
        CountText.Text = $"{_samples.Count} 个待测";
        EmptyState.Visibility = _samples.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private void CopySampleName_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not XrfSample sample) return;
        Clipboard.SetText(sample.SampleName);
        StatusText.Text = $"已复制：{sample.SampleName}";
    }
}
