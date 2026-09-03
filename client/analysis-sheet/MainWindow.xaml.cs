using Microsoft.Win32;
using System.Collections.ObjectModel;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace Oxsas.AnalysisSheet;

public partial class MainWindow : Window
{
    private readonly ObservableCollection<OxsasAnalysis> _samples4A = [];
    private readonly ObservableCollection<OxsasAnalysis> _samples4B = [];
    private readonly List<OxsasAnalysis> _analyses = [];
    private readonly List<TemplateDefinition> _templates = [];
    private readonly OxsasReader _reader = new();
    private string TemplatesDirectory => Path.Combine(AppContext.BaseDirectory, "templates");

    public MainWindow()
    {
        InitializeComponent();
        SampleABox.ItemsSource = _samples4A;
        SampleBBox.ItemsSource = _samples4B;
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            foreach (var file in Directory.EnumerateFiles(TemplatesDirectory, "*.json")
                         .OrderBy(path => Path.GetFileName(path), StringComparer.OrdinalIgnoreCase))
            {
                var template = JsonSerializer.Deserialize<TemplateDefinition>(
                    File.ReadAllText(file), new JsonSerializerOptions(JsonSerializerDefaults.Web));
                if (template is not null) _templates.Add(template);
            }
            TemplateBox.ItemsSource = _templates;
            if (_templates.Count > 0)
                TemplateBox.SelectedItem = _templates.FirstOrDefault(template => template.Name.Contains("默认"))
                    ?? _templates[0];
            DateBox.SelectedDate = DateTime.Today;
            TimeBox.Text = DateTime.Now.ToString("HH:mm");
            OutputPathBox.Text = DefaultOutputPath();
            Directory.CreateDirectory(Path.Combine(AppContext.BaseDirectory, "分析单"));
            await LoadSamplesAsync(showErrors: false);
        }
        catch (Exception ex)
        {
            SetStatus("启动失败：" + ex.Message, true);
        }
    }

    private async void RefreshSamples_Click(object sender, RoutedEventArgs e) => await LoadSamplesAsync(showErrors: true);

    private async Task LoadSamplesAsync(bool showErrors)
    {
        try
        {
            SampleLoadText.Text = "正在只读查询 OXSAS 数据库……";
            SetStatus("正在读取数据库……");
            var analyses = await _reader.ReadAnalysisSheetAsync();
            _analyses.Clear();
            _analyses.AddRange(analyses);
            PopulateSampleSelectors();
            SetStatus("数据库列表已更新");
        }
        catch (Exception ex)
        {
            SampleLoadText.Text = "数据库读取失败";
            SetStatus("数据库读取失败：" + ex.Message, true);
            if (showErrors)
                MessageBox.Show(ex.Message, "OXSAS 数据库读取失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void Template_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        PopulateSampleSelectors();
        OutputPathBox.Text = DefaultOutputPath();
    }

    private void PopulateSampleSelectors()
    {
        if (TemplateBox.SelectedItem is not TemplateDefinition template || template.Slots.Count < 2) return;
        var first = template.Slots[0].Name;
        var second = template.Slots[1].Name;
        SampleALabel.Text = first;
        SampleBLabel.Text = second;
        _samples4A.Clear();
        _samples4B.Clear();
        foreach (var analysis in _analyses)
        {
            if (analysis.SampleName.Contains(first, StringComparison.OrdinalIgnoreCase)) _samples4A.Add(analysis);
            if (analysis.SampleName.Contains(second, StringComparison.OrdinalIgnoreCase)) _samples4B.Add(analysis);
        }
        if (_samples4A.Count > 0) SampleABox.SelectedIndex = 0;
        if (_samples4B.Count > 0) SampleBBox.SelectedIndex = 0;
        SampleLoadText.Text = $"已读取：{first} {_samples4A.Count} 条，{second} {_samples4B.Count} 条";
    }

    private void Sample_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var selected = new[] { SampleABox.SelectedItem as OxsasAnalysis, SampleBBox.SelectedItem as OxsasAnalysis }
            .Where(item => item is not null).Cast<OxsasAnalysis>()
            .OrderByDescending(item => item.AnalyzedAt).FirstOrDefault();
        if (selected is null) return;
        DateBox.SelectedDate = selected.AnalyzedAt.Date;
        TimeBox.Text = selected.AnalyzedAt.ToString("HH:mm");
        OutputPathBox.Text = DefaultOutputPath();
    }

    private void Blank_Changed(object sender, RoutedEventArgs e)
    {
        SampleABox.IsEnabled = SampleABlankBox.IsChecked != true;
        SampleBBox.IsEnabled = SampleBBlankBox.IsChecked != true;
        OutputPathBox.Text = DefaultOutputPath();
    }

    private void BrowseOutput_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new SaveFileDialog
        {
            Filter = "Excel 工作簿 (*.xlsx)|*.xlsx",
            FileName = Path.GetFileName(OutputPathBox.Text),
            InitialDirectory = Path.GetDirectoryName(OutputPathBox.Text),
            AddExtension = true,
            DefaultExt = ".xlsx",
        };
        if (dialog.ShowDialog(this) == true) OutputPathBox.Text = dialog.FileName;
    }

    private void Generate_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var (output, missing) = GenerateWorkbook();
            SetStatus($"已生成：{output}");
            MessageBox.Show($"分析单已生成：\n{output}" + MissingMessage(missing), "完成",
                MessageBoxButton.OK, missing.Count == 0 ? MessageBoxImage.Information : MessageBoxImage.Warning);
        }
        catch (Exception ex)
        {
            SetStatus("生成失败：" + ex.Message, true);
            MessageBox.Show(ex.Message, "生成失败", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void Print_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var (output, missing) = GenerateWorkbook();
            if (missing.Count > 0)
            {
                var answer = MessageBox.Show("数据库中有模板项目没有结果：" + MissingMessage(missing) +
                    "\n\n仍然发送到默认打印机吗？", "结果不完整",
                    MessageBoxButton.YesNo, MessageBoxImage.Warning);
                if (answer != MessageBoxResult.Yes) return;
            }
            SetStatus("正在发送到默认打印机……");
            ExcelPrintService.PrintToDefaultPrinter(output);
            SetStatus("已发送到默认打印机");
            MessageBox.Show($"已生成并发送到默认打印机：\n{output}", "已打印",
                MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            SetStatus("打印失败：" + ex.Message, true);
            MessageBox.Show(ex.Message, "打印失败", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private (string Output, IReadOnlyList<string> Missing) GenerateWorkbook()
    {
        if (TemplateBox.SelectedItem is not TemplateDefinition template)
            throw new InvalidOperationException("找不到分析单模板。");
        if (template.Slots.Count < 2)
            throw new InvalidOperationException("当前模板没有配置两个样品位置。");
        var blankA = SampleABlankBox.IsChecked == true;
        var blankB = SampleBBlankBox.IsChecked == true;
        if (blankA && blankB)
            throw new InvalidOperationException("两个样品位置不能同时留空。");
        var sample4A = blankA ? null : SampleABox.SelectedItem as OxsasAnalysis;
        var sample4B = blankB ? null : SampleBBox.SelectedItem as OxsasAnalysis;
        if (sample4A is null && !blankA)
            throw new InvalidOperationException($"数据库列表中尚未选择 {template.Slots[0].Name} 样品，或勾选“空白”。");
        if (sample4B is null && !blankB)
            throw new InvalidOperationException($"数据库列表中尚未选择 {template.Slots[1].Name} 样品，或勾选“空白”。");
        var output = Path.GetFullPath(OutputPathBox.Text.Trim());
        if (!output.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase)) output += ".xlsx";
        var missing = WorkbookTemplateEngine.Generate(new GenerateRequest
        {
            Template = template,
            TemplatePath = Path.Combine(TemplatesDirectory, template.Workbook),
            OutputPath = output,
            Samples =
            [
                sample4A is null ? null : new GenerateSample { Name = sample4A.SampleName, Results = sample4A.Results },
                sample4B is null ? null : new GenerateSample { Name = sample4B.SampleName, Results = sample4B.Results },
            ],
            Date = DateBox.SelectedDate ?? sample4A?.AnalyzedAt.Date ?? sample4B?.AnalyzedAt.Date ?? DateTime.Today,
            SampleTime = TimeBox.Text,
        });
        OutputPathBox.Text = output;
        return (output, missing);
    }

    private string DefaultOutputPath()
    {
        var a = (SampleABox.SelectedItem as OxsasAnalysis)?.SampleName;
        var b = (SampleBBox.SelectedItem as OxsasAnalysis)?.SampleName;
        var names = string.Join("-", new[] { a, b }.Where(value => !string.IsNullOrWhiteSpace(value)));
        if (string.IsNullOrWhiteSpace(names)) names = DateTime.Now.ToString("yyyyMMdd-HHmm");
        foreach (var invalid in Path.GetInvalidFileNameChars()) names = names.Replace(invalid, '_');
        return Path.Combine(AppContext.BaseDirectory, "分析单", $"分析单-{names}.xlsx");
    }

    private static string MissingMessage(IReadOnlyList<string> missing) => missing.Count == 0
        ? ""
        : $"\n\n数据库未返回：{string.Join("、", missing)}";

    private void SetStatus(string message, bool error = false)
    {
        StatusText.Text = message;
        StatusText.Foreground = error
            ? System.Windows.Media.Brushes.Firebrick
            : System.Windows.Media.Brushes.DarkSlateGray;
    }
}
