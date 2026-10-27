using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

/// <summary>Home page: the service plus one card per enrolled network (a device can
/// be in several, each on its own server). A card opens that network's
/// <see cref="StatusPage"/>.</summary>
public sealed partial class NetworksPage : Page
{
    private readonly DispatcherTimer _timer;
    private bool _refreshing;
    private string? _fingerprint;

    public NetworksPage()
    {
        InitializeComponent();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
        _timer.Tick += async (_, _) => await RefreshAsync();
        Loaded += async (_, _) =>
        {
            await RefreshAsync();
            _timer.Start();
        };
        Unloaded += (_, _) => _timer.Stop();
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e)
    {
        _fingerprint = null;
        await RefreshAsync();
    }

    private void AddNetworkButton_Click(object sender, RoutedEventArgs e) =>
        App.MainWindowInstance?.NavigateToTag("enrollment");

    private async Task RefreshAsync()
    {
        if (_refreshing)
        {
            return;
        }
        _refreshing = true;
        try
        {
            var state = ServiceControl.GetState();
            UpdateServiceCard(state);
            var networks = state == NebulaServiceState.Running ? await ServiceApi.ListNetworksAsync() : null;
            RenderNetworks(networks, state);
        }
        finally
        {
            _refreshing = false;
        }
    }

    private void RenderNetworks(List<NetworkInfo>? networks, NebulaServiceState state)
    {
        var fingerprint = networks is null
            ? $"none:{state}"
            : string.Join("|", networks.Select(n =>
                $"{n.Id};{n.DisplayName};{n.Server};{n.OverlayIp};{n.TunDev};{n.Status.State};{n.Status.Message};{n.ExitNode}"));
        if (fingerprint == _fingerprint)
        {
            return;
        }
        _fingerprint = fingerprint;
        NetworksPanel.Children.Clear();
        NoNetworksBar.IsOpen = networks is { Count: 0 };
        CloudPromo.Visibility = networks is { Count: 0 } ? Visibility.Visible : Visibility.Collapsed;
        if (networks is null)
        {
            NetworksPanel.Children.Add(new TextBlock
            {
                Text = state == NebulaServiceState.Running
                    ? "The service isn't answering yet."
                    : "Start the service to see this device's networks.",
                Opacity = 0.7,
            });
            return;
        }
        foreach (var n in networks)
        {
            NetworksPanel.Children.Add(BuildCard(n));
        }
    }

    private Button BuildCard(NetworkInfo n)
    {
        var (color, stateText) = n.Status.State switch
        {
            "connected" => (Colors.SeaGreen, "Connected"),
            "error" => (Colors.Firebrick, "Error"),
            "idle" => (Colors.SteelBlue, "Idle"),
            "starting" => (Colors.Goldenrod, "Starting"),
            _ => (Colors.Gray, "Unknown"),
        };
        var details = new List<string>();
        if (!string.IsNullOrWhiteSpace(n.OverlayIp)) details.Add(n.OverlayIp);
        if (!string.IsNullOrWhiteSpace(n.TunDev)) details.Add(n.TunDev);
        if (!string.IsNullOrWhiteSpace(n.Server)) details.Add(n.Server);

        var header = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        header.Children.Add(new Ellipse { Width = 10, Height = 10, Fill = new SolidColorBrush(color), VerticalAlignment = VerticalAlignment.Center });
        header.Children.Add(new TextBlock { Text = n.DisplayName, Style = (Style)Application.Current.Resources["BodyStrongTextBlockStyle"] });
        header.Children.Add(new TextBlock { Text = stateText, Opacity = 0.7 });

        var body = new StackPanel { Spacing = 4 };
        body.Children.Add(header);
        body.Children.Add(new TextBlock { Text = string.Join("  ·  ", details), Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        if (n.Status.State == "error" && !string.IsNullOrWhiteSpace(n.Status.Message))
        {
            body.Children.Add(new TextBlock { Text = n.Status.Message, TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Colors.Firebrick) });
        }
        if (!string.IsNullOrWhiteSpace(n.ExitNode))
        {
            body.Children.Add(new TextBlock { Text = $"All traffic goes through the exit node via {n.ExitNode}", Opacity = 0.7 });
        }

        var card = new Button
        {
            Content = body,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Left,
            Padding = new Thickness(16),
            Tag = n,
        };
        AutomationPropertiesHelper.SetName(card, $"{n.DisplayName}, {stateText}");
        card.Click += (_, _) => Frame.Navigate(typeof(StatusPage), n);
        return card;
    }

    private void UpdateServiceCard(NebulaServiceState state)
    {
        var (color, text) = state switch
        {
            NebulaServiceState.Running => (Colors.SeaGreen, "Running"),
            NebulaServiceState.Stopped => (Colors.Firebrick, "Stopped"),
            NebulaServiceState.Transitioning => (Colors.Goldenrod, "Starting/stopping..."),
            _ => (Colors.Gray, "Not installed"),
        };
        ServiceDot.Fill = new SolidColorBrush(color);
        ServiceStateText.Text = text;
        ServiceStartButton.IsEnabled = state == NebulaServiceState.Stopped;
        ServiceStopButton.IsEnabled = state == NebulaServiceState.Running;
        ServiceRestartButton.IsEnabled = state == NebulaServiceState.Running;
    }

    private async void ServiceStartButton_Click(object sender, RoutedEventArgs e) =>
        await RunServiceActionAsync(() => ServiceControl.Start(), "started");

    private async void ServiceStopButton_Click(object sender, RoutedEventArgs e) =>
        await RunServiceActionAsync(() => ServiceControl.Stop(), "stopped");

    private async void ServiceRestartButton_Click(object sender, RoutedEventArgs e) =>
        await RunServiceActionAsync(() => ServiceControl.Restart(), "restarted");

    private async Task RunServiceActionAsync(Action action, string verb)
    {
        ServiceStartButton.IsEnabled = false;
        ServiceStopButton.IsEnabled = false;
        ServiceRestartButton.IsEnabled = false;
        ServiceProgress.IsActive = true;
        ServiceActionResult.Text = "";
        try
        {
            // Start/Stop/Restart block on WaitForStatus (up to 15s) - off the UI thread.
            await Task.Run(action);
            ServiceActionResult.Text = $"Service {verb}.";
        }
        catch (Exception ex)
        {
            if (!Elevation.IsElevated)
            {
                App.MainWindowInstance?.ShowAdminRequired();
                ServiceActionResult.Text = "Failed: administrator required.";
            }
            else
            {
                ServiceActionResult.Text = $"Failed: {ex.Message}";
            }
        }
        finally
        {
            ServiceProgress.IsActive = false;
            _fingerprint = null;
            await RefreshAsync();
        }
    }
}

/// <summary>Small wrapper so the card's accessible name reads as "name, state" rather
/// than the concatenation of every TextBlock inside it.</summary>
internal static class AutomationPropertiesHelper
{
    public static void SetName(DependencyObject element, string name) =>
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(element, name);
}
