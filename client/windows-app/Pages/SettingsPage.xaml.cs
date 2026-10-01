using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

public sealed partial class SettingsPage : Page
{
    private bool _loading;
    private string? _latestNebulaTag;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await LoadSettingsAsync();
    }

    private async Task LoadSettingsAsync()
    {
        _loading = true;
        try
        {
            RunOnStartupToggle.IsOn = AutoStart.IsEnabled();
            var settings = await ServiceApi.GetSettingsAsync();
            if (settings is null)
            {
                ShowSaveResult(InfoBarSeverity.Warning, "Service not running",
                    "Start the Nebula Commander service (Status page) to view or change settings.");
                SaveButton.IsEnabled = false;
            }
            else
            {
                ServerBox.Text = settings.Server ?? "";
                IntervalBox.Value = settings.Interval ?? 60;
                AcceptDnsToggle.IsOn = settings.AcceptDns ?? false;
                SaveButton.IsEnabled = true;
                SaveResultBar.IsOpen = false;
            }
        }
        finally
        {
            _loading = false;
        }

        await RefreshUpdateStatusAsync(loadSettings: true);

        // Nothing installed yet (e.g. the first-run install failed offline):
        // allow installing latest without a separate "check" first.
        if (await RefreshNebulaVersionTextAsync() is null)
        {
            DownloadButton.IsEnabled = true;
        }
    }

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        SaveButton.IsEnabled = false;
        SaveProgress.IsActive = true;
        try
        {
            var server = string.IsNullOrWhiteSpace(ServerBox.Text) ? "" : BackendClient.NormalizeServerUrl(ServerBox.Text.Trim());
            var interval = Math.Clamp((int)(double.IsNaN(IntervalBox.Value) ? 60 : IntervalBox.Value), 10, 3600);
            // The service saves and restarts its poll loop with the new settings.
            var result = await ServiceApi.SetSettingsAsync(server, interval, AcceptDnsToggle.IsOn);
            if (result.Ok)
            {
                ShowSaveResult(InfoBarSeverity.Success, "Saved", "Settings saved. The service is using them now.");
            }
            else
            {
                if (result.AdministratorRequired)
                {
                    App.MainWindowInstance?.ShowAdminRequired();
                }
                ShowSaveResult(InfoBarSeverity.Error, "Not saved", ServiceApi.Describe(result));
            }
        }
        finally
        {
            SaveButton.IsEnabled = true;
            SaveProgress.IsActive = false;
        }
    }

    private void ShowSaveResult(InfoBarSeverity severity, string title, string message)
    {
        SaveResultBar.Severity = severity;
        SaveResultBar.Title = title;
        SaveResultBar.Message = message;
        SaveResultBar.IsOpen = true;
    }

    private async Task<string?> RefreshNebulaVersionTextAsync()
    {
        var version = await ServiceApi.GetNebulaVersionAsync();
        NebulaVersionText.Text = version is not null
            ? $"Installed: v{version}"
            : "Not installed (or the service isn't running).";
        return version;
    }

    private async void CheckUpdateButton_Click(object sender, RoutedEventArgs e)
    {
        CheckUpdateButton.IsEnabled = false;
        NebulaProgress.IsActive = true;
        NebulaResultBar.IsOpen = false;
        try
        {
            var latest = await ServiceApi.GetLatestNebulaTagAsync();
            _latestNebulaTag = latest.Ok && latest.Result.ValueKind == System.Text.Json.JsonValueKind.String
                ? latest.Result.GetString()
                : null;
            if (_latestNebulaTag is null)
            {
                ShowNebulaResult(InfoBarSeverity.Error, "Check failed", ServiceApi.Describe(latest));
                DownloadButton.IsEnabled = false;
                return;
            }

            var installed = await RefreshNebulaVersionTextAsync();
            var newer = ServiceApi.IsNewerVersion(installed, _latestNebulaTag);
            ShowNebulaResult(
                InfoBarSeverity.Informational,
                "Latest release",
                newer
                    ? $"{_latestNebulaTag} is available (installed: {(installed is null ? "none" : "v" + installed)})."
                    : $"Already up to date ({_latestNebulaTag}).");
            DownloadButton.IsEnabled = true;
        }
        finally
        {
            CheckUpdateButton.IsEnabled = true;
            NebulaProgress.IsActive = false;
        }
    }

    private async void DownloadButton_Click(object sender, RoutedEventArgs e)
    {
        DownloadButton.IsEnabled = false;
        CheckUpdateButton.IsEnabled = false;
        NebulaProgress.IsActive = true;
        ShowNebulaResult(InfoBarSeverity.Informational, "Installing",
            "The service is downloading and verifying Nebula - the tunnel restarts briefly when it switches over.");
        try
        {
            var result = await ServiceApi.UpdateNebulaAsync(_latestNebulaTag);
            if (!result.Ok)
            {
                if (result.AdministratorRequired)
                {
                    App.MainWindowInstance?.ShowAdminRequired();
                }
                ShowNebulaResult(InfoBarSeverity.Error, "Install failed", ServiceApi.Describe(result));
                return;
            }
            var tag = result.Result.TryGetProperty("tag", out var t) ? t.GetString() : _latestNebulaTag;
            ShowNebulaResult(InfoBarSeverity.Success, "Installed", $"Nebula {tag} installed and running.");
            await RefreshNebulaVersionTextAsync();
        }
        finally
        {
            DownloadButton.IsEnabled = true;
            CheckUpdateButton.IsEnabled = true;
            NebulaProgress.IsActive = false;
        }
    }

    private void ShowNebulaResult(InfoBarSeverity severity, string title, string message)
    {
        NebulaResultBar.Severity = severity;
        NebulaResultBar.Title = title;
        NebulaResultBar.Message = message;
        NebulaResultBar.IsOpen = true;
    }

    // --- Nebula Commander updates ---

    private static TimeSpan ParseHhMm(string value, TimeSpan fallback) =>
        TimeSpan.TryParseExact(value, @"hh\:mm", null, out var t) ? t : fallback;

    private static string FormatHhMm(TimeSpan t) => $"{t.Hours:00}:{t.Minutes:00}";

    private static string LocalTime(string? iso) =>
        DateTimeOffset.TryParse(iso, out var t) ? t.LocalDateTime.ToString("g") : iso ?? "";

    /// <summary>Returns the status (null if the service is unreachable or too old).
    /// loadSettings: also reset the toggle/window to what the service has.</summary>
    private async Task<UpdateStatus?> RefreshUpdateStatusAsync(bool loadSettings)
    {
        var st = await ServiceApi.GetUpdateStatusAsync();
        if (st is null || !st.Supported)
        {
            UpdatesSection.Visibility = Visibility.Collapsed;
            return st;
        }
        UpdatesSection.Visibility = Visibility.Visible;
        ClientVersionText.Text = st.DevBuild
            ? "Installed: development build (never updated automatically)"
            : $"Installed: v{st.InstalledVersion}";
        if (loadSettings)
        {
            AutoUpdateToggle.IsOn = st.Enabled;
            WindowStartPicker.Time = ParseHhMm(st.WindowStart, new TimeSpan(2, 0, 0));
            WindowEndPicker.Time = ParseHhMm(st.WindowEnd, new TimeSpan(5, 0, 0));
        }

        var lines = new List<string>();
        if (st.LastCheck is not null)
        {
            lines.Add(st.LastResult switch
            {
                "update_available" => $"Last checked {LocalTime(st.LastCheck)}: v{st.AvailableVersion} is available.",
                "error" => $"Last checked {LocalTime(st.LastCheck)}: {st.LastError}",
                _ => $"Last checked {LocalTime(st.LastCheck)}: up to date.",
            });
        }
        if (st.LastInstallAttempt is not null)
        {
            lines.Add(st.LastInstallResult switch
            {
                "installing" => $"Installing since {LocalTime(st.LastInstallAttempt)}...",
                "error" => $"Last install ({LocalTime(st.LastInstallAttempt)}) failed: {st.LastInstallError}",
                _ => $"Last updated {LocalTime(st.LastInstallAttempt)}.",
            });
        }
        UpdateStatusText.Text = string.Join(Environment.NewLine, lines);
        UpdateStatusText.Visibility = lines.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        return st;
    }

    private void ShowUpdatesResult(InfoBarSeverity severity, string title, string message)
    {
        UpdatesResultBar.Severity = severity;
        UpdatesResultBar.Title = title;
        UpdatesResultBar.Message = message;
        UpdatesResultBar.IsOpen = true;
    }

    private async void SaveUpdatesButton_Click(object sender, RoutedEventArgs e)
    {
        SaveUpdatesButton.IsEnabled = false;
        UpdatesProgress.IsActive = true;
        try
        {
            var result = await ServiceApi.SetAutoUpdateAsync(
                AutoUpdateToggle.IsOn, FormatHhMm(WindowStartPicker.Time), FormatHhMm(WindowEndPicker.Time));
            if (result.Ok)
            {
                ShowUpdatesResult(InfoBarSeverity.Success, "Saved", AutoUpdateToggle.IsOn
                    ? $"Updates install automatically between {FormatHhMm(WindowStartPicker.Time)} and {FormatHhMm(WindowEndPicker.Time)}."
                    : "Automatic updates are off.");
            }
            else
            {
                if (result.AdministratorRequired)
                {
                    App.MainWindowInstance?.ShowAdminRequired();
                }
                ShowUpdatesResult(InfoBarSeverity.Error, "Not saved", ServiceApi.Describe(result));
            }
            await RefreshUpdateStatusAsync(loadSettings: true);
        }
        finally
        {
            SaveUpdatesButton.IsEnabled = true;
            UpdatesProgress.IsActive = false;
        }
    }

    private async void CheckNowButton_Click(object sender, RoutedEventArgs e)
    {
        CheckNowButton.IsEnabled = false;
        UpdatesProgress.IsActive = true;
        UpdatesResultBar.IsOpen = false;
        try
        {
            var before = (await ServiceApi.GetUpdateStatusAsync())?.LastCheck;
            var result = await ServiceApi.UpdateCheckNowAsync();
            if (!result.Ok)
            {
                if (result.AdministratorRequired)
                {
                    App.MainWindowInstance?.ShowAdminRequired();
                }
                ShowUpdatesResult(InfoBarSeverity.Error, "Check failed", ServiceApi.Describe(result));
                return;
            }
            // The service checks on its own thread; wait for the result to land.
            for (var i = 0; i < 60; i++)
            {
                await Task.Delay(1000);
                var st = await RefreshUpdateStatusAsync(loadSettings: false);
                if (st?.LastCheck is not null && st.LastCheck != before)
                {
                    if (st.LastResult == "update_available" && st.Enabled && !st.DevBuild)
                    {
                        ShowUpdatesResult(InfoBarSeverity.Informational, "Installing",
                            $"Installing v{st.AvailableVersion}. This app closes and reopens while it upgrades.");
                    }
                    return;
                }
            }
            ShowUpdatesResult(InfoBarSeverity.Warning, "Still checking", "No result yet - check back in a minute.");
        }
        finally
        {
            CheckNowButton.IsEnabled = true;
            UpdatesProgress.IsActive = false;
        }
    }

    private void RunOnStartupToggle_Toggled(object sender, RoutedEventArgs e)
    {
        if (_loading)
        {
            return;
        }
        AutoStart.SetEnabled(RunOnStartupToggle.IsOn);
    }
}
