using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace ToyLims.XrfClient;

public sealed class LimsApiClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly JsonSerializerOptions _json = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public LimsApiClient(string baseUrl, string token)
    {
        _http = new HttpClient
        {
            BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(8),
        };
        if (!string.IsNullOrWhiteSpace(token))
            _http.DefaultRequestHeaders.Add("X-Instrument-Token", token.Trim());
    }

    public async Task<XrfTasksResponse> GetTasksAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _http.GetAsync("api/instrument/xrf/tasks", cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync<XrfTasksResponse>(_json, cancellationToken)
            ?? new XrfTasksResponse { Error = "服务端返回空响应" };
        if (!response.IsSuccessStatusCode || !payload.Ok)
            throw new InvalidOperationException(payload.Error.Length > 0
                ? payload.Error : $"LIMS 请求失败：{(int)response.StatusCode}");
        return payload;
    }

    public async Task<ImportResponse> ImportAsync(
        OxsasAnalysis analysis, CancellationToken cancellationToken = default)
    {
        var request = new
        {
            analysis_id = analysis.AnalysisId,
            oxsas_sample_name = analysis.SampleName,
            method = analysis.Method,
            batch = analysis.Batch,
            analyzed_at = analysis.AnalyzedAt.ToString("O"),
            results = analysis.Results.Select(result => new { result.Name, result.Value }).ToArray(),
        };
        using var response = await _http.PostAsJsonAsync(
            "api/instrument/xrf/import", request, _json, cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync<ImportResponse>(_json, cancellationToken)
            ?? new ImportResponse { Error = "服务端返回空响应" };
        if (!response.IsSuccessStatusCode || !payload.Ok)
            throw new InvalidOperationException(payload.Error.Length > 0
                ? payload.Error : $"上传失败：{(int)response.StatusCode}");
        return payload;
    }

    public async Task<XrfSyncStateResponse> GetSyncStateAsync(
        CancellationToken cancellationToken = default)
    {
        using var response = await _http.GetAsync("api/instrument/xrf/sync-state", cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync<XrfSyncStateResponse>(_json, cancellationToken)
            ?? new XrfSyncStateResponse { Error = "服务端返回空响应" };
        if (!response.IsSuccessStatusCode || !payload.Ok)
            throw new InvalidOperationException(payload.Error.Length > 0
                ? payload.Error : $"同步状态读取失败：{(int)response.StatusCode}");
        return payload;
    }

    public async Task<BatchImportResponse> ImportBatchAsync(
        IReadOnlyCollection<OxsasAnalysis> analyses, CancellationToken cancellationToken = default)
    {
        var request = new
        {
            analyses = analyses.Select(analysis => new
            {
                analysis_id = analysis.AnalysisId,
                oxsas_sample_name = analysis.SampleName,
                method = analysis.Method,
                batch = analysis.Batch,
                analyzed_at = analysis.AnalyzedAt.ToString("O"),
                results = analysis.Results.Select(result => new { result.Name, result.Value }).ToArray(),
            }).ToArray(),
        };
        return await PostBatchAsync("api/instrument/xrf/import/batch", request, cancellationToken);
    }

    public async Task<UqImportResponse> ImportUqAsync(
        UqAnalysis analysis, CancellationToken cancellationToken = default)
    {
        var request = new
        {
            general_id = analysis.GeneralDataId,
            job_id = analysis.JobId,
            sample_name = analysis.Options.SampleId,
            analyzed_at = analysis.AnalyzedAt.ToString("O"),
            method = analysis.Options.Method,
            processed = analysis.Processed,
            options = analysis.Options,
            job = analysis.Job,
            results = analysis.Results.Select(result => new
            {
                result.Name, result.Value,
                result.ElementName, result.OxideName,
            }).ToArray(),
        };
        using var response = await _http.PostAsJsonAsync(
            "api/instrument/xrf/uq/import", request, _json, cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync<UqImportResponse>(_json, cancellationToken)
            ?? new UqImportResponse { Error = "服务端返回空响应" };
        if (!response.IsSuccessStatusCode || !payload.Ok)
            throw new InvalidOperationException(payload.Error.Length > 0
                ? payload.Error : $"UQ 同步失败：{(int)response.StatusCode}");
        return payload;
    }

    public async Task<BatchImportResponse> ImportUqBatchAsync(
        IReadOnlyCollection<UqAnalysis> analyses, CancellationToken cancellationToken = default)
    {
        var request = new
        {
            analyses = analyses.Select(analysis => new
            {
                general_id = analysis.GeneralDataId,
                job_id = analysis.JobId,
                sample_name = analysis.Options.SampleId,
                analyzed_at = analysis.AnalyzedAt.ToString("O"),
                method = analysis.Options.Method,
                processed = analysis.Processed,
                options = analysis.Options,
                job = analysis.Job,
                results = analysis.Results.Select(result => new
                {
                    result.Name, result.Value,
                    result.ElementName, result.OxideName,
                }).ToArray(),
            }).ToArray(),
        };
        return await PostBatchAsync("api/instrument/xrf/uq/import/batch", request, cancellationToken);
    }

    private async Task<BatchImportResponse> PostBatchAsync(
        string path, object request, CancellationToken cancellationToken)
    {
        using var response = await _http.PostAsJsonAsync(path, request, _json, cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync<BatchImportResponse>(_json, cancellationToken)
            ?? new BatchImportResponse { Error = "服务端返回空响应" };
        if (!response.IsSuccessStatusCode || !payload.Ok)
            throw new InvalidOperationException(payload.Error.Length > 0
                ? payload.Error : $"批量同步失败：{(int)response.StatusCode}");
        return payload;
    }

    /// <summary>上报终端状态心跳；失败时静默忽略，避免影响测量流程。</summary>
    public async Task PostStatusAsync(
        string state, string currentSample = "", string currentMethod = "",
        string currentBatch = "", string currentRunId = "", string currentPosition = "",
        string currentStartedAt = "", string message = "", string version = "",
        CancellationToken cancellationToken = default)
    {
        var request = new
        {
            machine_name = Environment.MachineName,
            version,
            state,
            current = new
            {
                sample = currentSample,
                method = currentMethod,
                batch = currentBatch,
                run_id = currentRunId,
                position = currentPosition,
                started_at = currentStartedAt,
            },
            message,
        };
        try
        {
            using var response = await _http.PostAsJsonAsync(
                "api/instrument/xrf/status", request, _json, cancellationToken);
        }
        catch (HttpRequestException) { /* 心跳失败不影响主流程 */ }
        catch (TaskCanceledException) { /* 超时同上 */ }
    }

    public void Dispose() => _http.Dispose();
}
