using Microsoft.Data.SqlClient;

namespace ToyLims.XrfClient;

public sealed class OxsasReader
{
    private static string BuildConnectionString(
        string server, string user, string password, string database) =>
        new SqlConnectionStringBuilder
        {
            DataSource = server.Trim(),
            InitialCatalog = database,
            UserID = user.Trim(),
            Password = password,
            Encrypt = true,
            TrustServerCertificate = true,
            ConnectTimeout = 6,
            ApplicationName = "ToyLims.XrfClient",
            ApplicationIntent = ApplicationIntent.ReadOnly,
        }.ConnectionString;

    public async Task<List<OxsasAnalysis>> ReadQuantitativeAsync(
        string server, string user, string password, DateTime since,
        int limit = 100,
        CancellationToken cancellationToken = default)
        => await ReadQuantitativeBatchAsync(server, user, password, since, -1, limit, cancellationToken);

    public async Task<List<OxsasAnalysis>> ReadQuantitativeAfterAsync(
        string server, string user, string password, int afterId, int limit = 250,
        CancellationToken cancellationToken = default)
        => await ReadQuantitativeBatchAsync(server, user, password, new DateTime(2000, 1, 1),
            afterId, limit, cancellationToken);

    private async Task<List<OxsasAnalysis>> ReadQuantitativeBatchAsync(
        string server, string user, string password, DateTime since, int afterId, int limit,
        CancellationToken cancellationToken)
    {
        var connectionString = BuildConnectionString(server, user, password, "ANALYSES");

        const string sql = """
            ;WITH AttrPivot AS (
                SELECT at.LinkAnalyses,
                    MAX(CASE WHEN names.Name = 'Sample Name' THEN at.Value END) AS SampleName,
                    MAX(CASE WHEN names.Name = '$ME$' THEN at.Value END) AS MethodName,
                    MAX(CASE WHEN names.Name = '$BA$' THEN at.Value END) AS BatchName
                FROM Attributes at
                JOIN AttributeName names ON names.ID = at.LinkName
                WHERE names.Name IN ('Sample Name', '$ME$', '$BA$')
                GROUP BY at.LinkAnalyses
            ), Latest AS (
                SELECT TOP (@limit) analyses.ID, analyses.AnaDateTime,
                    attrs.SampleName, attrs.MethodName, attrs.BatchName
                FROM Analyses analyses
                LEFT JOIN AttrPivot attrs ON attrs.LinkAnalyses = analyses.ID
                WHERE ((@afterId < 0 AND analyses.AnaDateTime >= @since)
                       OR (@afterId >= 0 AND analyses.ID > @afterId))
                  AND COALESCE(attrs.MethodName, '') NOT LIKE 'X[_]UQ%'
                ORDER BY CASE WHEN @afterId >= 0 THEN analyses.ID END ASC,
                         CASE WHEN @afterId < 0 THEN analyses.AnaDateTime END DESC,
                         analyses.ID DESC
            )
            SELECT latest.ID, latest.AnaDateTime, latest.SampleName, latest.MethodName,
                   latest.BatchName, displayNames.Name AS ElementName, elements.Value
            FROM Latest latest
            JOIN Elements elements ON elements.LinkAnalyses = latest.ID
            JOIN DisplayName displayNames ON displayNames.ID = elements.LinkName
            WHERE displayNames.Name NOT LIKE 'Bg%'
            ORDER BY latest.AnaDateTime DESC, latest.ID DESC, elements.Value DESC;
            """;

        await using var connection = new SqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);
        await using var command = new SqlCommand(sql, connection) { CommandTimeout = 15 };
        command.Parameters.AddWithValue("@since", since);
        command.Parameters.AddWithValue("@afterId", afterId);
        command.Parameters.AddWithValue("@limit", Math.Clamp(limit, 1, 250));
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
                    SampleName = reader.IsDBNull(2) ? "" : reader.GetString(2).Trim(),
                    Method = reader.IsDBNull(3) ? "" : reader.GetString(3).Trim(),
                    Batch = reader.IsDBNull(4) ? "" : reader.GetString(4).Trim(),
                };
                analyses.Add(id, analysis);
            }
            if (!reader.IsDBNull(5) && !reader.IsDBNull(6))
                analysis.Results.Add(new OxsasResult
                {
                    Name = reader.GetString(5).Trim(),
                    Value = reader.GetDouble(6),
                });
        }
        return analyses.Values
            .OrderByDescending(analysis => analysis.AnalyzedAt)
            .ThenByDescending(analysis => analysis.AnalysisId)
            .Take(limit)
            .ToList();
    }

    public async Task<List<UqAnalysis>> ReadUqAsync(
        string server, string user, string password, DateTime since,
        int limit = 100,
        CancellationToken cancellationToken = default)
        => await ReadUqBatchAsync(server, user, password, since, -1, limit, cancellationToken);

    public async Task<List<UqAnalysis>> ReadUqAfterAsync(
        string server, string user, string password, int afterGeneralId, int limit = 250,
        CancellationToken cancellationToken = default)
        => await ReadUqBatchAsync(server, user, password, new DateTime(2000, 1, 1),
            afterGeneralId, limit, cancellationToken);

    private async Task<List<UqAnalysis>> ReadUqBatchAsync(
        string server, string user, string password, DateTime since, int afterGeneralId, int limit,
        CancellationToken cancellationToken)
    {
        const string jobsSql = """
            ;WITH LatestGeneral AS (
                SELECT TOP (@limit) g.ID
                FROM GeneralData g
                JOIN FilmHdr f ON f.ID=g.LinkFilmHdr
                WHERE ((@afterId < 0 AND g.CreationDate>=@since)
                       OR (@afterId >= 0 AND g.ID>@afterId))
                  AND LOWER(REPLACE(f.Name,' ','')) IN ('pp4mu','pp4um',N'pp4µm',N'pp4μm')
                  AND EXISTS(SELECT 1 FROM JobHdr finalJob JOIN JobChan finalValue
                      ON finalValue.LinkJobHdr=finalJob.ID
                      WHERE finalJob.LinkGeneralData=g.ID
                        AND finalValue.IsAddedToHundred=1 AND finalValue.Conc IS NOT NULL)
                ORDER BY CASE WHEN @afterId >= 0 THEN g.ID END ASC,
                         CASE WHEN @afterId < 0 THEN g.CreationDate END DESC,g.ID DESC
            )
            SELECT
                g.ID,g.SampleId,g.CreationDate,g.Remark,g.Chemistry,g.LinkShapeHdr,g.CaseNb,
                g.LinkKappasHdr,g.Method,g.Atmosphere,g.LinkFilmHdr,g.ReportLevel,g.Sector,g.Area,
                g.Diameter,g.GrossDiameter,g.Mass,g.GrossMass,g.Rho,g.Height,g.ShadowLoss,g.KnownConc,
                g.LinkKnownMaterial,g.Rest,g.LinkRestMaterial,g.DoS,g.LinkDoSMaterial,
                s.Name,k.Name,f.Name,
                j.ID,j.Name,j.LinkGeneralData,j.IsTemplate,j.Result,j.PartRho,j.CO2Conc,j.StrippedOxygen
            FROM GeneralData g
            JOIN LatestGeneral latest ON latest.ID=g.ID
            JOIN JobHdr j ON j.LinkGeneralData=g.ID
            LEFT JOIN ShapeHdr s ON s.ID=g.LinkShapeHdr
            LEFT JOIN KappasHdr k ON k.ID=g.LinkKappasHdr
            LEFT JOIN FilmHdr f ON f.ID=g.LinkFilmHdr
            WHERE EXISTS(SELECT 1 FROM JobChan finalValue WHERE finalValue.LinkJobHdr=j.ID
                AND finalValue.IsAddedToHundred=1 AND finalValue.Conc IS NOT NULL)
            ORDER BY g.CreationDate DESC,g.ID DESC,j.ID DESC;
            """;

        await using var connection = new SqlConnection(
            BuildConnectionString(server, user, password, "UniQuant"));
        await connection.OpenAsync(cancellationToken);
        var analyses = new List<UqAnalysis>();
        await using (var command = new SqlCommand(jobsSql, connection) { CommandTimeout = 15 })
        {
            command.Parameters.AddWithValue("@since", since);
            command.Parameters.AddWithValue("@afterId", afterGeneralId);
            command.Parameters.AddWithValue("@limit", Math.Clamp(limit, 1, 250));
            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            while (await reader.ReadAsync(cancellationToken))
            {
                analyses.Add(new UqAnalysis
                {
                    Options = new UqOptions
                    {
                        Id = Int(reader, 0)!.Value, SampleId = Text(reader, 1),
                        CreationDate = reader.GetDateTime(2), Remark = Text(reader, 3),
                        Chemistry = Int(reader, 4), LinkShapeHdr = Int(reader, 5), CaseNb = Int(reader, 6),
                        LinkKappasHdr = Int(reader, 7), Method = Text(reader, 8), Atmosphere = Int(reader, 9),
                        LinkFilmHdr = Int(reader, 10), ReportLevel = Number(reader, 11), Sector = Number(reader, 12),
                        Area = Number(reader, 13), Diameter = Number(reader, 14), GrossDiameter = Number(reader, 15),
                        Mass = Number(reader, 16), GrossMass = Number(reader, 17), Rho = Number(reader, 18),
                        Height = Number(reader, 19), ShadowLoss = Number(reader, 20), KnownConc = Number(reader, 21),
                        LinkKnownMaterial = Int(reader, 22), Rest = Number(reader, 23), LinkRestMaterial = Int(reader, 24),
                        DoS = Number(reader, 25), LinkDoSMaterial = Int(reader, 26), Shape = Text(reader, 27),
                        Kappas = Text(reader, 28), Film = Text(reader, 29),
                    },
                    Job = new UqJob
                    {
                        Id = Int(reader, 30)!.Value, Name = Text(reader, 31),
                        LinkGeneralData = Int(reader, 32)!.Value, IsTemplate = Flag(reader, 33),
                         Result = Text(reader, 34), PartRho = Number(reader, 35),
                        CO2Conc = Number(reader, 36), StrippedOxygen = Number(reader, 37),
                    },
                });
            }
        }

        if (analyses.Count == 0) return analyses;
        var parameterNames = analyses.Select((_, index) => $"@job{index}").ToArray();
        var resultsSql = $"""
            SELECT jc.LinkJobHdr,a.Name,a.OxideName,jc.Conc
            FROM JobChan jc
            JOIN [Line] line ON line.ID=jc.LinkLine
            JOIN Atom a ON a.ID=line.LinkAtom
            WHERE jc.LinkJobHdr IN ({string.Join(",", parameterNames)})
              AND jc.IsAddedToHundred=1 AND jc.Conc IS NOT NULL
            ORDER BY jc.LinkJobHdr,jc.Conc DESC,jc.ID;
            """;
        var byJob = analyses.ToDictionary(analysis => analysis.JobId);
        await using (var command = new SqlCommand(resultsSql, connection) { CommandTimeout = 15 })
        {
            for (var index = 0; index < analyses.Count; index++)
                command.Parameters.AddWithValue(parameterNames[index], analyses[index].JobId);
            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            while (await reader.ReadAsync(cancellationToken))
            {
                var jobId = Int(reader, 0)!.Value;
                if (!byJob.TryGetValue(jobId, out var analysis)) continue;
                var elementName = Text(reader, 1);
                var oxideName = Text(reader, 2);
                var name = analysis.Options.Chemistry == 1 && oxideName.Length > 0
                    ? oxideName : elementName;
                var value = Number(reader, 3);
                if (name.Length > 0 && value is not null)
                    analysis.Results.Add(new OxsasResult { Name = name, Value = value.Value });
            }
        }
        return analyses
            .OrderByDescending(analysis => analysis.AnalyzedAt)
            .ThenByDescending(analysis => analysis.GeneralDataId)
            .Take(limit)
            .ToList();
    }

    private static string Text(SqlDataReader reader, int ordinal) =>
        reader.IsDBNull(ordinal) ? "" : Convert.ToString(reader.GetValue(ordinal))?.Trim() ?? "";
    private static int? Int(SqlDataReader reader, int ordinal) =>
        reader.IsDBNull(ordinal) ? null : Convert.ToInt32(reader.GetValue(ordinal));
    private static double? Number(SqlDataReader reader, int ordinal) =>
        reader.IsDBNull(ordinal) ? null : Convert.ToDouble(reader.GetValue(ordinal));
    private static bool? Flag(SqlDataReader reader, int ordinal) =>
        reader.IsDBNull(ordinal) ? null : Convert.ToBoolean(reader.GetValue(ordinal));

    public async Task<OxsasRuntimeStatus?> ReadRuntimeStatusAsync(
        string server, string user, string password,
        CancellationToken cancellationToken = default)
    {
        const string sql = """
            ;WITH PendingCollections AS (
                SELECT b.ID AS BatchID,b.Name AS BatchName,c.ID AS CollectionID,c.Name AS CollectionName,
                    c.XXXLastModif,
                    ROW_NUMBER() OVER (ORDER BY c.XXXLastModif DESC,c.ID DESC) AS rn
                FROM Batch_Batches b
                JOIN Batch_BatchColls bc ON bc.LinkBatch=b.ID
                JOIN Batch_Collections c ON c.ID=bc.LinkColl_Batch_Collections
                WHERE c.Type=0 AND EXISTS(
                    SELECT 1 FROM Batch_CollSamples pending
                    WHERE pending.LinkCollection=c.ID AND pending.Status=0)
            ), InstrumentState AS (
                SELECT
                    MAX(CASE WHEN Name='X-ray voltage' THEN TRY_CONVERT(float,Value) END) AS XRayKv,
                    MAX(CASE WHEN Name='X-ray current' THEN TRY_CONVERT(float,Value) END) AS XRayMa,
                    MAX(CASE WHEN Name='enter kV' THEN TRY_CONVERT(float,Value) END) AS StandbyKv,
                    MAX(CASE WHEN Name='enter mA' THEN TRY_CONVERT(float,Value) END) AS StandbyMa
                FROM Gen_InstrState
            )
            SELECT TOP (1) GETDATE() AS ServerTime,pc.XXXLastModif,pc.BatchID,pc.BatchName,
                pc.CollectionID,pc.CollectionName,s.ID AS RowID,s.Sequence,s.Cassette,p.Name AS MethodName,
                CASE WHEN CHARINDEX('<v>',CONVERT(nvarchar(max),s.SerialSid))>0
                           AND CHARINDEX('</v>',CONVERT(nvarchar(max),s.SerialSid))>0
                    THEN SUBSTRING(CONVERT(nvarchar(max),s.SerialSid),
                        CHARINDEX('<v>',CONVERT(nvarchar(max),s.SerialSid))+3,
                        CHARINDEX('</v>',CONVERT(nvarchar(max),s.SerialSid))-
                        CHARINDEX('<v>',CONVERT(nvarchar(max),s.SerialSid))-3)
                    ELSE '' END AS SampleName,
                COALESCE(i.XRayKv,0),COALESCE(i.XRayMa,0),
                COALESCE(i.StandbyKv,0),COALESCE(i.StandbyMa,0)
            FROM PendingCollections pc
            JOIN Batch_CollSamples s ON s.LinkCollection=pc.CollectionID AND s.Status=0
            LEFT JOIN Prog_Hdr p ON p.ID=s.LinkProg_Prog_Hdr
            CROSS JOIN InstrumentState i
            WHERE pc.rn=1
            ORDER BY s.Sequence,s.ID;
            """;

        await using var connection = new SqlConnection(
            BuildConnectionString(server, user, password, "oxsas_db"));
        await connection.OpenAsync(cancellationToken);
        await using var command = new SqlCommand(sql, connection) { CommandTimeout = 10 };
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        if (!await reader.ReadAsync(cancellationToken)) return null;
        return new OxsasRuntimeStatus
        {
            ServerTime = reader.GetDateTime(0),
            ActivityAt = reader.GetDateTime(1),
            BatchId = reader.GetInt32(2),
            Batch = reader.IsDBNull(3) ? "" : reader.GetString(3).Trim(),
            CollectionId = reader.GetInt32(4),
            Collection = reader.IsDBNull(5) ? "" : reader.GetString(5).Trim(),
            RowId = reader.GetInt32(6),
            Sequence = reader.GetInt32(7),
            Cassette = reader.IsDBNull(8) ? "" : reader.GetString(8).Trim(),
            Method = reader.IsDBNull(9) ? "" : reader.GetString(9).Trim(),
            SampleName = reader.IsDBNull(10) ? "" : reader.GetString(10).Trim(),
            XRayKv = reader.GetDouble(11),
            XRayMa = reader.GetDouble(12),
            StandbyKv = reader.GetDouble(13),
            StandbyMa = reader.GetDouble(14),
        };
    }
}
