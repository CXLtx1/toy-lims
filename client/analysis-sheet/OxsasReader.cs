using Microsoft.Data.SqlClient;

namespace Oxsas.AnalysisSheet;

public sealed class OxsasReader
{
    // 本工具只部署在仪器电脑，按需求固定连接信息，不在界面暴露配置。
    private const string Server = ".";
    private const string Database = "ANALYSES";
    private const string User = "OXSAS";
    private const string Password = "Oxsas369852147!";

    public async Task<List<OxsasAnalysis>> ReadAnalysisSheetAsync(CancellationToken cancellationToken = default)
    {
        var connectionString = new SqlConnectionStringBuilder
        {
            DataSource = Server,
            InitialCatalog = Database,
            UserID = User,
            Password = Password,
            Encrypt = true,
            TrustServerCertificate = true,
            ConnectTimeout = 6,
            ApplicationName = "OXSAS Analysis Sheet",
        }.ConnectionString;

        const string sql = """
            ;WITH AttrPivot AS (
                SELECT attrs.LinkAnalyses,
                    MAX(CASE WHEN names.Name = 'Sample Name' THEN attrs.Value END) AS SampleName,
                    MAX(CASE WHEN names.Name = '$ME$' THEN attrs.Value END) AS MethodName
                FROM Attributes attrs
                JOIN AttributeName names ON names.ID = attrs.LinkName
                WHERE names.Name IN ('Sample Name', '$ME$')
                GROUP BY attrs.LinkAnalyses
            ), Matching AS (
                SELECT TOP (1000) analyses.ID, analyses.AnaDateTime,
                    attrs.SampleName, attrs.MethodName
                FROM Analyses analyses
                JOIN AttrPivot attrs ON attrs.LinkAnalyses = analyses.ID
                WHERE analyses.AnaDateTime >= @since
                  AND attrs.SampleName IS NOT NULL
                  AND (attrs.SampleName LIKE '%4A%' OR attrs.SampleName LIKE '%4B%'
                       OR attrs.SampleName LIKE '%2B%' OR attrs.SampleName LIKE '%2C%')
                  AND COALESCE(attrs.MethodName, '') NOT LIKE 'X[_]UQ%'
                ORDER BY analyses.AnaDateTime DESC, analyses.ID DESC
            )
            SELECT matching.ID, matching.AnaDateTime, matching.SampleName, matching.MethodName,
                   displayNames.Name, elements.Value
            FROM Matching matching
            JOIN Elements elements ON elements.LinkAnalyses = matching.ID
            JOIN DisplayName displayNames ON displayNames.ID = elements.LinkName
            ORDER BY matching.AnaDateTime DESC, matching.ID DESC, displayNames.Name;
            """;

        await using var connection = new SqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);
        await using var command = new SqlCommand(sql, connection) { CommandTimeout = 20 };
        command.Parameters.AddWithValue("@since", DateTime.Now.AddYears(-10));
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        var analyses = new Dictionary<int, OxsasAnalysis>();
        while (await reader.ReadAsync(cancellationToken))
        {
            var id = reader.GetInt32(0);
            if (!analyses.TryGetValue(id, out var analysis))
            {
                analysis = new OxsasAnalysis
                {
                    AnalysisId = id,
                    AnalyzedAt = reader.GetDateTime(1),
                    SampleName = reader.GetString(2).Trim(),
                    Method = reader.IsDBNull(3) ? "" : reader.GetString(3).Trim(),
                };
                analyses.Add(id, analysis);
            }
            if (!reader.IsDBNull(4) && !reader.IsDBNull(5))
                analysis.Results[reader.GetString(4).Trim()] = reader.GetDouble(5);
        }
        return analyses.Values
            .OrderByDescending(item => item.AnalyzedAt)
            .ThenByDescending(item => item.AnalysisId)
            .ToList();
    }
}
