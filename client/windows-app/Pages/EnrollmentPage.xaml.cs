using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

public sealed partial class EnrollmentPage : Page
{
    public EnrollmentPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await LoadExistingAsync();
    }

    private async Task LoadExistingAsync()
    {
        ResultBar.IsOpen = false;
        var enrollment = await ServiceApi.GetEnrollmentAsync();
        if (enrollment is null)
        {
            ShowResult(InfoBarSeverity.Warning, "The Nebula Commander service isn't running - start it from the Status page.");
            return;
        }
        if (!string.IsNullOrWhiteSpace(enrollment.Server))
        {
            ServerBox.Text = enrollment.Server;
        }
        AlreadyEnrolledBar.IsOpen = enrollment.Enrolled;
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
            // The service makes the enroll HTTP call and stores the token itself
            // (SYSTEM-only), then re-polls immediately.
            var result = await ServiceApi.EnrollAsync(BackendClient.NormalizeServerUrl(server), code);
            if (result.AdministratorRequired)
            {
                App.MainWindowInstance?.ShowAdminRequired();
                ShowResult(InfoBarSeverity.Error, ServiceApi.Describe(result));
                return;
            }
            if (!result.Ok)
            {
                ShowResult(InfoBarSeverity.Error, ServiceApi.Describe(result));
                return;
            }

            CodeBox.Text = "";
            ShowResult(InfoBarSeverity.Success, "Enrolled. Loading status...");
            App.MainWindowInstance?.NavigateToTag("status");
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
