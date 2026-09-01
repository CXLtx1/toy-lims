using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace ToyLims.StandardClient;

public sealed class LimsApiClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly JsonSerializerOptions _json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    public LimsApiClient(string baseUrl, string token)
    {
        var normalized = baseUrl.Trim().TrimEnd('/') + "/";
        _http = new HttpClient { BaseAddress = new Uri(normalized), Timeout = TimeSpan.FromSeconds(12) };
        if (!string.IsNullOrWhiteSpace(token)) _http.DefaultRequestHeaders.Add("X-Instrument-Token", token.Trim());
    }

    public Task<InstrumentListResponse> GetInstrumentsAsync(CancellationToken cancellationToken = default) =>
        GetAsync<InstrumentListResponse>("api/instrument/standard/instruments", cancellationToken);

    public Task<TaskListResponse> GetTasksAsync(int instrumentId, CancellationToken cancellationToken = default) =>
        GetAsync<TaskListResponse>($"api/instrument/standard/tasks?instrument_id={instrumentId}", cancellationToken);

    public async Task ReportStatusAsync(int instrumentId, CancellationToken cancellationToken = default)
    {
        var payload = new
        {
            client_id = Environment.MachineName,
            machine_name = Environment.MachineName,
            version = typeof(LimsApiClient).Assembly.GetName().Version?.ToString(3) ?? "",
            instrument_id = instrumentId,
        };
        using var response = await _http.PostAsJsonAsync("api/instrument/standard/status",
            payload, _json, cancellationToken);
        await ReadResponseAsync<BasicResponse>(response, cancellationToken);
    }

    public void SetUserAuthorization(string? token)
    {
        _http.DefaultRequestHeaders.Remove("X-User-Authorization");
        if (!string.IsNullOrWhiteSpace(token))
            _http.DefaultRequestHeaders.Add("X-User-Authorization", token);
    }

    public async Task<AuthorizationResponse> AuthorizeAsync(string password,
        CancellationToken cancellationToken = default)
    {
        using var response = await _http.PostAsJsonAsync("api/instrument/standard/authorize",
            new { password, client_id = Environment.MachineName }, _json, cancellationToken);
        return await ReadResponseAsync<AuthorizationResponse>(response, cancellationToken);
    }

    public async Task TouchAuthorizationAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _http.PostAsJsonAsync("api/instrument/standard/session/touch",
            new { }, _json, cancellationToken);
        await ReadResponseAsync<BasicResponse>(response, cancellationToken);
    }

    public async Task LogoutAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _http.PostAsJsonAsync("api/instrument/standard/logout",
            new { }, _json, cancellationToken);
        await ReadResponseAsync<BasicResponse>(response, cancellationToken);
    }

    public async Task StartMeasurementAsync(int sampleId, int instrumentId,
        CancellationToken cancellationToken = default)
    {
        using var response = await _http.PostAsJsonAsync($"api/instrument/standard/samples/{sampleId}/start",
            new { instrument_id = instrumentId }, _json, cancellationToken);
        await ReadResponseAsync<BasicResponse>(response, cancellationToken);
    }

    public async Task<SubmitResponse> SubmitAsync(int instrumentId, IReadOnlyCollection<ReadingSubmission> readings,
        string submissionId, CancellationToken cancellationToken = default)
    {
        var payload = new
        {
            client_id = Environment.MachineName,
            submission_id = submissionId,
            instrument_id = instrumentId,
            readings,
        };
        using var response = await _http.PostAsJsonAsync("api/instrument/standard/submit", payload, _json, cancellationToken);
        return await ReadResponseAsync<SubmitResponse>(response, cancellationToken);
    }

    private async Task<T> GetAsync<T>(string url, CancellationToken cancellationToken)
    {
        using var response = await _http.GetAsync(url, cancellationToken);
        return await ReadResponseAsync<T>(response, cancellationToken);
    }

    private async Task<T> ReadResponseAsync<T>(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var text = await response.Content.ReadAsStringAsync(cancellationToken);
        T? data;
        try { data = JsonSerializer.Deserialize<T>(text, _json); }
        catch (JsonException ex)
        {
            throw new InvalidOperationException($"LIMS 响应格式无法识别：{ex.Path ?? "未知字段"}", ex);
        }
        if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized)
        {
            string? unauthorizedError = null;
            try { unauthorizedError = JsonDocument.Parse(text).RootElement.GetProperty("error").GetString(); }
            catch { }
            throw new UnauthorizedAccessException(unauthorizedError ?? "用户登录已过期");
        }
        if (!response.IsSuccessStatusCode || data is null)
        {
            string? error = null;
            try { error = JsonDocument.Parse(text).RootElement.GetProperty("error").GetString(); }
            catch { }
            throw new InvalidOperationException(error ?? $"LIMS 返回错误 {(int)response.StatusCode}");
        }
        return data;
    }

    public void Dispose() => _http.Dispose();
}
