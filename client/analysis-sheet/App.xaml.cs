using System.IO;
using System.Windows;
using System.Text.Json;

namespace Oxsas.AnalysisSheet;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        if (e.Args.Length is 2 or 3 && e.Args[0] == "--generate-sample")
        {
            try
            {
                var directory = Path.Combine(AppContext.BaseDirectory, "templates");
                var templateName = e.Args.Length == 3 ? e.Args[2] : "4A4B";
                var definition = JsonSerializer.Deserialize<TemplateDefinition>(
                    File.ReadAllText(Path.Combine(directory, templateName + ".json")),
                    new JsonSerializerOptions(JsonSerializerDefaults.Web))
                    ?? throw new InvalidOperationException("默认模板配置无效");
                WorkbookTemplateEngine.Generate(new GenerateRequest
                {
                    Template = definition,
                    TemplatePath = Path.Combine(directory, definition.Workbook),
                    OutputPath = Path.GetFullPath(e.Args[1]),
                    Samples =
                    [
                        new GenerateSample
                        {
                            Name = $"RC-TEST-{definition.Slots[0].Name}",
                            Results = definition.Slots[0].Elements.ToDictionary(
                                name => name, name => name == "Ag" ? 0.01219425162516 : 1.2),
                        },
                        new GenerateSample
                        {
                            Name = $"RC-TEST-{definition.Slots[1].Name}",
                            Results = definition.Slots[1].Elements.ToDictionary(
                                name => name, name => name == "Ag" ? 0.01219425162516 : 2.3),
                        },
                    ],
                    Date = new DateTime(2026, 8, 27),
                    SampleTime = "15:30",
                });
                Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.GetFullPath(e.Args[1]) + ".error.txt", ex.ToString());
                Shutdown(1);
            }
            return;
        }
        base.OnStartup(e);
    }
}
