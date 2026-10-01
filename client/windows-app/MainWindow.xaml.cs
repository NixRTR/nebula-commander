using System.Linq;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Pages;
using NebulaCommanderApp.Services;
using NebulaCommanderApp.Tray;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace NebulaCommanderApp;

public sealed partial class MainWindow : Window
{
    private readonly TrayIcon _trayIcon;

    // Set only by ExitFromTray(); AppWindow_Closing checks it to tell "user
    // clicked X" (hide to tray) apart from "user picked Exit in the tray menu"
    // (let the close actually happen) - both raise the same Closing event.
    private bool _isExiting;

    public MainWindow()
    {
        InitializeComponent();

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        AppWindow.SetIcon("Assets/AppIcon.ico");

        AppWindow.Closing += AppWindow_Closing;
        _trayIcon = new TrayIcon(onOpen: ShowAndActivate, onExit: ExitFromTray);
        AdminBar.IsOpen = !Elevation.IsElevated;
    }

    /// <summary>Called by pages when the service answered administrator_required
    /// (or a service start/stop was denied): re-show the bar, highlighted.</summary>
    public void ShowAdminRequired()
    {
        AdminBar.Severity = InfoBarSeverity.Warning;
        AdminBar.Title = "Administrator required";
        AdminBar.IsOpen = true;
    }

    private void RelaunchElevated_Click(object sender, RoutedEventArgs e)
    {
        if (Elevation.TryRelaunchElevated())
        {
            ExitFromTray();
        }
    }

    private void AppWindow_Closing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_isExiting)
        {
            return;
        }
        // Closing the window (X button, Alt+F4) minimizes to tray instead of
        // exiting - the service keeps running regardless either way, but the UI
        // should stay reachable from the tray rather than requiring a relaunch.
        args.Cancel = true;
        AppWindow.Hide();
    }

    public void ShowAndActivate()
    {
        AppWindow.Show();
        Activate();
    }

    private void ExitFromTray()
    {
        _isExiting = true;
        _trayIcon.Dispose();
        Application.Current.Exit();
    }

    /// <summary>Selects the given MenuItem tag ("status"/"enrollment"), which
    /// fires NavView_SelectionChanged and navigates the frame to match.</summary>
    public void NavigateToTag(string tag)
    {
        var item = NavView.MenuItems
            .OfType<NavigationViewItem>()
            .FirstOrDefault(i => (string?)i.Tag == tag);
        if (item is not null)
        {
            NavView.SelectedItem = item;
        }
    }

    /// <summary>Enrolled -> Status, not enrolled -> Enrollment. Called once at
    /// launch (see App.xaml.cs::OnLaunched). Asks the service (is_enrolled) -
    /// the token itself is never readable by this app. Service unreachable ->
    /// Status, which explains that.</summary>
    public async void NavigateInitial()
    {
        var enrollment = await ServiceApi.GetEnrollmentAsync();
        NavigateToTag(enrollment is { Enrolled: false } ? "enrollment" : "status");
    }

    private void TitleBar_PaneToggleRequested(TitleBar sender, object args)
    {
        NavView.IsPaneOpen = !NavView.IsPaneOpen;
    }

    private void TitleBar_BackRequested(TitleBar sender, object args)
    {
        NavFrame.GoBack();
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            NavFrame.Navigate(typeof(SettingsPage));
        }
        else if (args.SelectedItem is NavigationViewItem item)
        {
            switch (item.Tag)
            {
                case "status":
                    NavFrame.Navigate(typeof(StatusPage));
                    break;
                case "enrollment":
                    NavFrame.Navigate(typeof(EnrollmentPage));
                    break;
                default:
                    throw new InvalidOperationException($"Unknown navigation item tag: {item.Tag}");
            }
        }
    }
}
