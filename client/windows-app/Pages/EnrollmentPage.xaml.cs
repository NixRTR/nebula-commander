using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

public sealed partial class EnrollmentPage : Page
{
    public EnrollmentPage()
    {
        InitializeComponent();
        Loaded += (_, _) => LoadExisting();
    }

    private void LoadExisting()
    {
        var settings = SettingsStore.Load();
        if (!string.IsNullOrWhiteSpace(settings.Server))
        {
            ServerBox.Text = settings.Server;
        }
        AlreadyEnrolledBar.IsOpen = TokenStore.GetToken() is not null;
        ResultBar.IsOpen = false;
    }

    private async void EnrollButton_Click(object sender, RoutedEventArgs e)
    {
        var server = ServerBox.Text.Trim();
        var code = CodeBox.Text.Trim();

        if (string.IsNullOrWhiteSpace(server))
        {
            ShowResult(InfoBarSeverity.Error, "Server URL is required.");
            return;
        }
        if (string.IsNullOrWhiteSpace(code))
        {
            ShowResult(InfoBarSeverity.Error, "Enrollment code is required.");
            return;
        }

        EnrollButton.IsEnabled = false;
        EnrollProgress.IsActive = true;
        ShowResult(InfoBarSeverity.Informational, "Enrolling...");
        try
        {
            var result = await BackendClient.EnrollAsync(server, code);

            TokenStore.SetToken(result.DeviceToken);

            var settings = SettingsStore.Load();
            settings.Server = BackendClient.NormalizeServerUrl(server);
            settings.NodeId = result.NodeId;
            SettingsStore.Save(settings);

            // Best-effort: ask the service to poll immediately instead of waiting
            // for its next interval tick. A failure here isn't fatal - the
            // service will pick up the new token/server on its own regardless.
            await PipeClient.SendCommandAsync(PipeClient.CmdPollNow);

            ShowResult(InfoBarSeverity.Success, "Enrolled. Loading status...");
            App.MainWindowInstance?.NavigateToTag("status");
        }
        catch (BackendClient.EnrollException ex)
        {
            ShowResult(InfoBarSeverity.Error, ex.Message);
        }
        catch (Exception ex)
        {
            ShowResult(InfoBarSeverity.Error, $"Enroll failed: {ex.Message}");
        }
        finally
        {
            EnrollButton.IsEnabled = true;
            EnrollProgress.IsActive = false;
        }
    }

    private void ShowResult(InfoBarSeverity severity, string message)
    {
        ResultBar.Severity = severity;
        ResultBar.Title = severity switch
        {
            InfoBarSeverity.Error => "Enroll failed",
            InfoBarSeverity.Success => "Success",
            _ => "",
        };
        ResultBar.Message = message;
        ResultBar.IsOpen = true;
    }
}
