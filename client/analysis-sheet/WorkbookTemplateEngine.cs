using System.IO;
using System.IO.Compression;
using System.Text;
using System.Xml.Linq;

namespace Oxsas.AnalysisSheet;

public static class WorkbookTemplateEngine
{
    private static readonly XNamespace Main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
    private static readonly XNamespace OfficeRel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    private static readonly XNamespace PackageRel = "http://schemas.openxmlformats.org/package/2006/relationships";
    private static readonly XNamespace ContentTypes = "http://schemas.openxmlformats.org/package/2006/content-types";

    public static IReadOnlyList<string> Generate(GenerateRequest request)
    {
        if (request.Template.Slots.Count == 0) throw new InvalidOperationException("模板没有样品位置配置。");
        foreach (var slot in request.Template.Slots)
        {
            var capacity = slot.EndRow - slot.StartRow + 1;
            if (slot.Elements.Count == 0)
                throw new InvalidOperationException($"模板位置 {slot.Name} 没有配置固定项目。");
            if (slot.Elements.Count > capacity)
                throw new InvalidOperationException($"模板位置 {slot.Name} 只能容纳 {capacity} 个项目。");
        }

        Directory.CreateDirectory(Path.GetDirectoryName(request.OutputPath)!);
        File.Copy(request.TemplatePath, request.OutputPath, overwrite: true);
        using var zip = ZipFile.Open(request.OutputPath, ZipArchiveMode.Update);

        var workbook = ReadXml(zip, "xl/workbook.xml");
        var workbookRels = ReadXml(zip, "xl/_rels/workbook.xml.rels");
        var sheets = workbook.Root!.Element(Main + "sheets")
                     ?? throw new InvalidOperationException("模板没有工作表。");
        var selected = sheets.Elements(Main + "sheet")
            .FirstOrDefault(sheet => string.Equals((string?)sheet.Attribute("name"),
                request.Template.Worksheet, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidOperationException($"模板中找不到工作表“{request.Template.Worksheet}”。");
        var selectedRelId = (string?)selected.Attribute(OfficeRel + "id")
                            ?? throw new InvalidOperationException("模板工作表关系无效。");
        var selectedRel = workbookRels.Root!.Elements(PackageRel + "Relationship")
            .First(rel => (string?)rel.Attribute("Id") == selectedRelId);
        var selectedPart = ResolveXlPart((string)selectedRel.Attribute("Target")!);
        var worksheet = ReadXml(zip, selectedPart);

        var missing = new List<string>();
        for (var index = 0; index < request.Template.Slots.Count; index++)
        {
            var slot = request.Template.Slots[index];
            var sample = index < request.Samples.Count ? request.Samples[index] : null;
            SetInlineString(worksheet, slot.SampleCell,
                sample?.Name.Trim() ?? "");
            for (var row = slot.StartRow; row <= slot.EndRow; row++)
            {
                var elementIndex = row - slot.StartRow;
                var element = elementIndex < slot.Elements.Count ? slot.Elements[elementIndex] : "";
                SetInlineString(worksheet, $"{slot.ElementColumn}{row}",
                    element);
                if (sample is not null && element.Length > 0 && sample.Results.TryGetValue(element, out var value))
                {
                    if (request.Template.ResultFormats.TryGetValue(element, out var format))
                    {
                        var converted = value * format.Multiplier;
                        var numberFormat = format.Decimals is int decimals
                            ? $"0.{new string('0', decimals)}"
                            : "0.###############";
                        SetInlineString(worksheet, $"{slot.ResultColumn}{row}",
                            converted.ToString(numberFormat,
                                System.Globalization.CultureInfo.InvariantCulture) + format.Suffix);
                    }
                    else SetNumber(worksheet, $"{slot.ResultColumn}{row}", value);
                }
                else
                {
                    ClearCell(worksheet, $"{slot.ResultColumn}{row}");
                    if (sample is not null && element.Length > 0) missing.Add($"{slot.Name} {element}");
                }
            }
        }
        if (!string.IsNullOrWhiteSpace(request.Template.DateCell))
            SetInlineString(worksheet, request.Template.DateCell, $"日期：{request.Date:yyyy.MM.dd}");
        if (!string.IsNullOrWhiteSpace(request.Template.TimeCell))
            SetInlineString(worksheet, request.Template.TimeCell,
                string.IsNullOrWhiteSpace(request.SampleTime) ? "" : $"送样时间{request.SampleTime.Trim()}");

        var dimension = worksheet.Root!.Element(Main + "dimension");
        if (dimension is not null && !string.IsNullOrWhiteSpace(request.Template.PrintArea))
            dimension.SetAttributeValue("ref", request.Template.PrintArea.Replace("$", ""));

        RebuildSharedStrings(zip, worksheet);
        RemoveOtherSheets(zip, workbook, workbookRels, selectedRelId);
        selected.SetAttributeValue("name", request.Template.OutputSheetName);
        RebuildDefinedNames(workbook, request.Template.OutputSheetName, request.Template.PrintArea);
        RemoveCalcChain(zip, workbookRels);
        UpdateContentTypes(zip);

        WriteXml(zip, selectedPart, worksheet);
        WriteXml(zip, "xl/workbook.xml", workbook);
        WriteXml(zip, "xl/_rels/workbook.xml.rels", workbookRels);
        return missing;
    }

    private static void RemoveOtherSheets(ZipArchive zip, XDocument workbook,
        XDocument relationships, string keepRelId)
    {
        var sheets = workbook.Root!.Element(Main + "sheets")!;
        foreach (var sheet in sheets.Elements(Main + "sheet").ToList())
        {
            var relId = (string?)sheet.Attribute(OfficeRel + "id");
            if (relId == keepRelId) continue;
            var rel = relationships.Root!.Elements(PackageRel + "Relationship")
                .FirstOrDefault(item => (string?)item.Attribute("Id") == relId);
            if (rel is not null)
            {
                var part = ResolveXlPart((string)rel.Attribute("Target")!);
                zip.GetEntry(part)?.Delete();
                var fileName = Path.GetFileName(part);
                var relPart = $"xl/worksheets/_rels/{fileName}.rels";
                zip.GetEntry(relPart)?.Delete();
                rel.Remove();
            }
            sheet.Remove();
        }
        var view = workbook.Descendants(Main + "workbookView").FirstOrDefault();
        view?.SetAttributeValue("activeTab", 0);
    }

    private static void RebuildDefinedNames(XDocument workbook, string sheetName, string printArea)
    {
        workbook.Root!.Element(Main + "definedNames")?.Remove();
        if (string.IsNullOrWhiteSpace(printArea)) return;
        var names = new XElement(Main + "definedNames",
            new XElement(Main + "definedName",
                new XAttribute("name", "_xlnm.Print_Area"),
                new XAttribute("localSheetId", "0"),
                $"'{sheetName.Replace("'", "''")}'!{printArea}"));
        var calcPr = workbook.Root!.Element(Main + "calcPr");
        if (calcPr is not null) calcPr.AddBeforeSelf(names);
        else workbook.Root!.Add(names);
    }

    private static void RemoveCalcChain(ZipArchive zip, XDocument relationships)
    {
        foreach (var rel in relationships.Root!.Elements(PackageRel + "Relationship")
                     .Where(item => ((string?)item.Attribute("Type"))?.EndsWith("/calcChain") == true).ToList())
            rel.Remove();
        zip.GetEntry("xl/calcChain.xml")?.Delete();
    }

    private static void UpdateContentTypes(ZipArchive zip)
    {
        const string name = "[Content_Types].xml";
        var types = ReadXml(zip, name);
        var existingParts = zip.Entries.Select(entry => "/" + entry.FullName.Replace('\\', '/'))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var item in types.Root!.Elements(ContentTypes + "Override").ToList())
        {
            var part = (string?)item.Attribute("PartName");
            if (part is not null && !existingParts.Contains(part)) item.Remove();
        }
        WriteXml(zip, name, types);
    }

    private static void RebuildSharedStrings(ZipArchive zip, XDocument worksheet)
    {
        var entry = zip.GetEntry("xl/sharedStrings.xml");
        if (entry is null) return;
        var shared = ReadXml(zip, "xl/sharedStrings.xml");
        var source = shared.Root!.Elements(Main + "si").ToList();
        var cells = worksheet.Descendants(Main + "c")
            .Where(cell => (string?)cell.Attribute("t") == "s" && cell.Element(Main + "v") is not null).ToList();
        var oldIndexes = cells.Select(cell => int.Parse(cell.Element(Main + "v")!.Value)).Distinct().ToList();
        var map = oldIndexes.Select((oldIndex, newIndex) => (oldIndex, newIndex))
            .ToDictionary(item => item.oldIndex, item => item.newIndex);
        foreach (var cell in cells)
        {
            var oldIndex = int.Parse(cell.Element(Main + "v")!.Value);
            cell.Element(Main + "v")!.Value = map[oldIndex].ToString();
        }
        var root = new XElement(Main + "sst",
            new XAttribute("count", cells.Count),
            new XAttribute("uniqueCount", oldIndexes.Count),
            oldIndexes.Select(index => new XElement(source[index])));
        WriteXml(zip, "xl/sharedStrings.xml", new XDocument(new XDeclaration("1.0", "UTF-8", "yes"), root));
    }

    private static void SetInlineString(XDocument worksheet, string reference, string value)
    {
        var cell = GetOrCreateCell(worksheet, reference);
        cell.RemoveNodes();
        cell.SetAttributeValue("t", "inlineStr");
        var text = new XElement(Main + "t", value);
        if (value.StartsWith(' ') || value.EndsWith(' '))
            text.SetAttributeValue(XNamespace.Xml + "space", "preserve");
        cell.Add(new XElement(Main + "is", text));
    }

    private static void ClearCell(XDocument worksheet, string reference)
    {
        var cell = GetOrCreateCell(worksheet, reference);
        cell.RemoveNodes();
        cell.Attribute("t")?.Remove();
    }

    private static void SetNumber(XDocument worksheet, string reference, double value)
    {
        var cell = GetOrCreateCell(worksheet, reference);
        cell.RemoveNodes();
        cell.Attribute("t")?.Remove();
        cell.Add(new XElement(Main + "v", value.ToString("G17", System.Globalization.CultureInfo.InvariantCulture)));
    }

    private static XElement GetOrCreateCell(XDocument worksheet, string reference)
    {
        var rowNumber = int.Parse(new string(reference.Where(char.IsDigit).ToArray()));
        var sheetData = worksheet.Root!.Element(Main + "sheetData")
                        ?? throw new InvalidOperationException("模板工作表没有单元格数据。");
        var row = sheetData.Elements(Main + "row")
            .FirstOrDefault(item => (int?)item.Attribute("r") == rowNumber);
        if (row is null)
        {
            row = new XElement(Main + "row", new XAttribute("r", rowNumber));
            var next = sheetData.Elements(Main + "row")
                .FirstOrDefault(item => (int?)item.Attribute("r") > rowNumber);
            if (next is null) sheetData.Add(row); else next.AddBeforeSelf(row);
        }
        var cell = row.Elements(Main + "c")
            .FirstOrDefault(item => string.Equals((string?)item.Attribute("r"), reference,
                StringComparison.OrdinalIgnoreCase));
        if (cell is not null) return cell;
        cell = new XElement(Main + "c", new XAttribute("r", reference.ToUpperInvariant()));
        var targetColumn = ColumnNumber(reference);
        var nextCell = row.Elements(Main + "c")
            .FirstOrDefault(item => ColumnNumber((string)item.Attribute("r")!) > targetColumn);
        if (nextCell is null) row.Add(cell); else nextCell.AddBeforeSelf(cell);
        return cell;
    }

    private static int ColumnNumber(string reference)
    {
        var number = 0;
        foreach (var ch in reference.ToUpperInvariant().TakeWhile(char.IsLetter))
            number = number * 26 + ch - 'A' + 1;
        return number;
    }

    private static string ResolveXlPart(string target) =>
        "xl/" + target.Replace('\\', '/').TrimStart('/');

    private static XDocument ReadXml(ZipArchive zip, string name)
    {
        var entry = zip.GetEntry(name) ?? throw new InvalidOperationException($"模板缺少 {name}");
        using var stream = entry.Open();
        return XDocument.Load(stream, LoadOptions.PreserveWhitespace);
    }

    private static void WriteXml(ZipArchive zip, string name, XDocument document)
    {
        zip.GetEntry(name)?.Delete();
        var entry = zip.CreateEntry(name, CompressionLevel.Optimal);
        using var stream = entry.Open();
        using var writer = new StreamWriter(stream, new UTF8Encoding(false));
        document.Save(writer, SaveOptions.DisableFormatting);
    }
}
