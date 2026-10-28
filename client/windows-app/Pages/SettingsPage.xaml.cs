using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

public sealed partial class SettingsPage : Page
{
    private bool _loading;
    private string? _latestNebulaTag;
    // Install progress: polled while an install runs (started here, or by the service
    // in the update window). _installTarget is set once "Install now" was clicked here.
    private readonly DispatcherTimer _installTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private string? _installTarget;
    private bool _pollingInstall;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await LoadSettingsAsync();
        _installTimer.Tick += async (_, _) => await PollInstallAsync();
        UpdateState.InstalledChanged += OnUpdateInstalled;
        Unloaded += (_, _) =>
        {
            _installTimer.Stop();
            UpdateState.InstalledChanged -= OnUpdateInstalled;
        };
    }

    private void OnUpdateInstalled() => DispatcherQueue.TryEnqueue(() => RenderInstall(null));

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
                    "Start the Nebula Commander service (Networks page) to view or change settings.");
                SaveButton.IsEnabled = false;
            }
            else
            {
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
            var interval = Math.Clamp((int)(double.IsNaN(IntervalBox.Value) ? 60 : IntervalBox.Value), 10, 3600);
            // The service saves and restarts its poll loop with the new settings.
            var result = await ServiceApi.SetSettingsAsync(interval, AcceptDnsToggle.IsOn);
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
        UpdateState.Observe(st);
        if (st is null && (_installTarget is not null || UpdateState.Installed))
        {
            // The installer stops the service while it upgrades: keep showing progress.
            RenderInstall(null);
            return null;
        }
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
        RenderInstall(st);
        return st;
    }

    private static string Megabytes(long bytes) => $"{bytes / 1048576.0:0.0} MB";

    /// <summary>Install now / progress bar / "Restart App", from the latest status
    /// (null: the service is restarting mid-install, or unreachable).</summary>
    private void RenderInstall(UpdateStatus? st)
    {
        var target = st?.InstallTarget ?? _installTarget ?? st?.AvailableVersion;
        var phase = st?.InstallPhase;
        if (UpdateState.Installed)
        {
            StopInstallPolling();
            InstallNowButton.Visibility = Visibility.Collapsed;
            InstallProgressPanel.Visibility = Visibility.Collapsed;
            RestartPanel.Visibility = Visibility.Visible;
            App.MainWindowInstance?.HideUpdatedBar();
            return;
        }
        RestartPanel.Visibility = Visibility.Collapsed;

        if (phase is not null || (st is null && _installTarget is not null))
        {
            InstallNowButton.Visibility = Visibility.Collapsed;
            InstallProgressPanel.Visibility = Visibility.Visible;
            if (phase == "downloading")
            {
                var known = st!.DownloadTotal > 0;
                InstallProgressBar.IsIndeterminate = !known;
                InstallProgressBar.Value = known ? 100.0 * st.DownloadDone / st.DownloadTotal : 0;
                InstallProgressText.Text = known
                    ? $"Downloading v{target}: {Megabytes(st.DownloadDone)} of {Megabytes(st.DownloadTotal)}"
                    : $"Downloading v{target}...";
            }
            else
            {
                InstallProgressBar.IsIndeterminate = true;
                InstallProgressText.Text = st is null
                    ? $"Installing v{target}. The service restarts while it upgrades..."
                    : $"Installing v{target}...";
            }
            StartInstallPolling();
            return;
        }

        InstallProgressPanel.Visibility = Visibility.Collapsed;
        if (_installTarget is not null && st?.LastInstallResult == "error")
        {
            _installTarget = null;
            StopInstallPolling();
            ShowUpdatesResult(InfoBarSeverity.Error, "Update failed", st.LastInstallError ?? "The install failed.");
        }
        InstallNowButton.Visibility =
            st is { LastResult: "update_available", DevBuild: false, Mode: "install" } && _installTarget is null
                ? Visibility.Visible
                : Visibility.Collapsed;
        if (_installTarget is null)
        {
            StopInstallPolling();
        }
    }

    private void StartInstallPolling()
    {
        if (!_pollingInstall)
        {
            _pollingInstall = true;
            _installTimer.Start();
        }
    }

    private void StopInstallPolling()
    {
        _pollingInstall = false;
        _installTimer.Stop();
    }

    private async Task PollInstallAsync()
    {
        _installTimer.Stop();
        try
        {
            await RefreshUpdateStatusAsync(loadSettings: false);
        }
        finally
        {
            if (_pollingInstall)
            {
                _installTimer.Start();
            }
        }
    }

    private async void InstallNowButton_Click(object sender, RoutedEventArgs e)
    {
        InstallNowButton.IsEnabled = false;
        UpdatesResultBar.IsOpen = false;
        try
        {
            var before = await ServiceApi.GetUpdateStatusAsync();
            var result = await ServiceApi.UpdateInstallNowAsync();
            if (!result.Ok)
            {
                if (result.AdministratorRequired)
                {
                    App.MainWindowInstance?.ShowAdminRequired();
                }
                ShowUpdatesResult(InfoBarSeverity.Error, "Not installed", ServiceApi.Describe(result));
                return;
            }
            _installTarget = before?.AvailableVersion ?? "";
            RenderInstall(before is null ? null : new UpdateStatus
            {
                InstalledVersion = before.InstalledVersion,
                InstallPhase = "downloading",
                InstallTarget = before.AvailableVersion,
            });
        }
        finally
        {
            InstallNowButton.IsEnabled = true;
        }
    }

    private void RestartAppButton_Click(object sender, RoutedEventArgs e) =>
        App.MainWindowInstance?.RestartApp();

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
                    if (st.LastResult == "update_available" && st.Mode == "install" && !st.DevBuild)
                    {
                        ShowUpdatesResult(InfoBarSeverity.Informational, $"v{st.AvailableVersion} is available",
                            st.Enabled
                                ? $"Click Install now, or it installs automatically between {st.WindowStart} and {st.WindowEnd}."
                                : "Click Install now to install it.");
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
