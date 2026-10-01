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

    private void RunOnStartupToggle_Toggled(object sender, RoutedEventArgs e)
    {
        if (_loading)
        {
            return;
        }
        AutoStart.SetEnabled(RunOnStartupToggle.IsOn);
    }
}
