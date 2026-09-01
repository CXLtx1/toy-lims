using System.IO;
using System.Text.Json;

namespace ToyLims.StandardClient;

public sealed class ClientSettings
{
    public string ServerUrl { get; set; } = "http://127.0.0.1:5000";
    public string Token { get; set; } = "";
    public int? InstrumentId { get; set; }
}

public static class ClientSettingsStore
{
    public static readonly string FilePath = Path.Combine(AppContext.BaseDirectory, "standard-client.json");
    private static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true };

    public static ClientSettings Load()
    {
        try
        {
            return File.Exists(FilePath)
                ? JsonSerializer.Deserialize<ClientSettings>(File.ReadAllText(FilePath), Json) ?? new ClientSettings()
                : new ClientSettings();
        }
        catch { return new ClientSettings(); }
    }

}
