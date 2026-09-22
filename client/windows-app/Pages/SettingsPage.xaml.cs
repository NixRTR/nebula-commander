using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Services;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace NebulaCommanderApp.Pages;

public sealed partial class SettingsPage : Page
{
    private bool _loading;
    private string? _latestNebulaTag;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += (_, _) => LoadSettings();
    }

    private void LoadSettings()
    {
        _loading = true;
        try
        {
            var settings = SettingsStore.Load();
            ServerBox.Text = settings.Server;
            IntervalBox.Value = settings.Interval;
            NebulaPathBox.Text = settings.NebulaPath;
            AcceptDnsToggle.IsOn = settings.AcceptDns;
            RunOnStartupToggle.IsOn = AutoStart.IsEnabled();
        }
        finally
        {
            _loading = false;
        }

        SaveResultBar.IsOpen = false;
        RefreshNebulaVersionText();
    }

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        SaveButton.IsEnabled = false;
        SaveProgress.IsActive = true;
        try
        {
            var settings = SettingsStore.Load();
            settings.Server = BackendClient.NormalizeServerUrl(ServerBox.Text.Trim());
            settings.Interval = Math.Clamp((int)(double.IsNaN(IntervalBox.Value) ? 60 : IntervalBox.Value), 10, 3600);
            settings.NebulaPath = NebulaPathBox.Text.Trim();
            settings.AcceptDns = AcceptDnsToggle.IsOn;
            SettingsStore.Save(settings);

            var result = await PipeClient.SendCommandAsync(PipeClient.CmdReloadSettings);

            SaveResultBar.Severity = InfoBarSeverity.Success;
            SaveResultBar.Title = "Saved";
            SaveResultBar.Message = result.Ok
                ? "Settings saved. The service is reloading them now."
                : $"Settings saved. The service will pick them up on its next poll ({result.Error}).";
            SaveResultBar.IsOpen = true;
        }
        finally
        {
            SaveButton.IsEnabled = true;
            SaveProgress.IsActive = false;
        }
    }

    private async void BrowseButton_Click(object sender, RoutedEventArgs e)
    {
        if (App.MainWindowInstance is null)
        {
            return;
        }

        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.ComputerFolder,
        };
        picker.FileTypeFilter.Add(".exe");

        // Unpackaged WinUI3 apps have no implicit window association - a picker
        // needs an explicit owner HWND or PickSingleFileAsync throws.
        var hwnd = WindowNative.GetWindowHandle(App.MainWindowInstance);
        InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        if (file is not null)
        {
            NebulaPathBox.Text = file.Path;
            RefreshNebulaVersionText();
        }
    }

    private string EffectiveNebulaPath()
    {
        var configured = NebulaPathBox.Text.Trim();
        if (!string.IsNullOrEmpty(configured))
        {
            return configured;
        }
        return File.Exists(SharedPaths.NebulaExePath) ? SharedPaths.NebulaExePath : "nebula";
    }

    private void RefreshNebulaVersionText()
    {
        var path = EffectiveNebulaPath();
        var version = NebulaDownload.GetInstalledVersion(path);
        NebulaVersionText.Text = version is not null
            ? $"Installed: v{version} ({path})"
            : $"Not found or not runnable at \"{path}\".";
    }

    private async void CheckUpdateButton_Click(object sender, RoutedEventArgs e)
    {
        CheckUpdateButton.IsEnabled = false;
        NebulaProgress.IsActive = true;
        NebulaResultBar.IsOpen = false;
        try
        {
            _latestNebulaTag = await NebulaDownload.FetchLatestTagAsync();
            if (_latestNebulaTag is null)
            {
                NebulaResultBar.Severity = InfoBarSeverity.Error;
                NebulaResultBar.Title = "Check failed";
                NebulaResultBar.Message = $"Could not reach GitHub releases ({NebulaDownload.ReleasesUrl}).";
                NebulaResultBar.IsOpen = true;
                DownloadButton.IsEnabled = false;
                return;
            }

            var installed = NebulaDownload.GetInstalledVersion(EffectiveNebulaPath());
            var newer = NebulaDownload.IsNewerVersion(installed, _latestNebulaTag);

            NebulaResultBar.Severity = InfoBarSeverity.Informational;
            NebulaResultBar.Title = "Latest release";
            NebulaResultBar.Message = newer
                ? $"{_latestNebulaTag} is available (installed: {(installed is null ? "none" : "v" + installed)})."
                : $"Already up to date ({_latestNebulaTag}).";
            NebulaResultBar.IsOpen = true;
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
        var tag = _latestNebulaTag;
        if (tag is null)
        {
            return;
        }

        DownloadButton.IsEnabled = false;
        NebulaProgress.IsActive = true;
        try
        {
            var (ok, exePath, error) = await NebulaDownload.DownloadToDirAsync(tag, SharedPaths.NebulaDir);
            if (!ok || exePath is null)
            {
                NebulaResultBar.Severity = InfoBarSeverity.Error;
                NebulaResultBar.Title = "Download failed";
                NebulaResultBar.Message = error;
                NebulaResultBar.IsOpen = true;
                return;
            }

            NebulaPathBox.Text = exePath;
            var settings = SettingsStore.Load();
            settings.NebulaPath = exePath;
            SettingsStore.Save(settings);
            await PipeClient.SendCommandAsync(PipeClient.CmdReloadSettings);

            NebulaResultBar.Severity = InfoBarSeverity.Success;
            NebulaResultBar.Title = "Downloaded";
            NebulaResultBar.Message = $"Installed {tag} to {exePath} and notified the service.";
            NebulaResultBar.IsOpen = true;
            RefreshNebulaVersionText();
        }
        finally
        {
            DownloadButton.IsEnabled = true;
            NebulaProgress.IsActive = false;
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
