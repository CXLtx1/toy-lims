using System.Runtime.InteropServices;
using System.IO;

namespace Oxsas.AnalysisSheet;

public static class ExcelPrintService
{
    public static void PrintToDefaultPrinter(string workbookPath)
    {
        var excelType = Type.GetTypeFromProgID("Excel.Application")
            ?? throw new InvalidOperationException("未检测到 Microsoft Excel，无法直接打印。仍可打开生成的 xlsx 手工打印。");
        object? excel = null;
        object? workbooks = null;
        object? workbook = null;
        try
        {
            excel = Activator.CreateInstance(excelType)
                ?? throw new InvalidOperationException("无法启动 Microsoft Excel。");
            dynamic app = excel;
            app.Visible = false;
            app.DisplayAlerts = false;
            workbooks = app.Workbooks;
            dynamic books = workbooks;
            workbook = books.Open(Path.GetFullPath(workbookPath), ReadOnly: true);
            dynamic book = workbook;
            book.PrintOut();
            book.Close(false);
            Release(workbook);
            workbook = null;
            app.Quit();
        }
        finally
        {
            if (workbook is not null)
            {
                try { ((dynamic)workbook).Close(false); } catch { }
                Release(workbook);
            }
            if (workbooks is not null) Release(workbooks);
            if (excel is not null)
            {
                try { ((dynamic)excel).Quit(); } catch { }
                Release(excel);
            }
        }
    }

    private static void Release(object value)
    {
        if (Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value);
    }
}
