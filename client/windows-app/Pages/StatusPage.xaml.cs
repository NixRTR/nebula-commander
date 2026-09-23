using System.Diagnostics;
using System.Text;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

public sealed partial class StatusPage : Page
{
    // Cheap local-only refresh (files + service query, no network) on a short
    // timer so the page feels live; routing info hits the backend so it's only
    // refetched on page load / the Refresh button, not on every tick.
    private readonly DispatcherTimer _timer;

    public StatusPage()
    {
        InitializeComponent();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        _timer.Tick += (_, _) => RefreshLocal();
        Loaded += StatusPage_Loaded;
        Unloaded += (_, _) => _timer.Stop();
    }

    private async void StatusPage_Loaded(object sender, RoutedEventArgs e)
    {
        await RefreshFullAsync();
        _timer.Start();
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshFullAsync();

    private async Task RefreshFullAsync()
    {
        RefreshButton.IsEnabled = false;
        RefreshProgress.IsActive = true;
        try
        {
            RefreshLocal();
            await RefreshRoutingAsync();
        }
        finally
        {
            RefreshButton.IsEnabled = true;
            RefreshProgress.IsActive = false;
        }
    }

    private void RefreshLocal()
    {
        var settings = SettingsStore.Load();
        var status = StatusStore.Load();
        var serviceState = ServiceControl.GetState();
        var tun = ConfigYaml.ReadTunConfig(SharedPaths.ConfigPath);

        var server = string.IsNullOrWhiteSpace(settings.Server) ? "(not set)" : settings.Server;
        ServerLink.Content = server;
        ServerLink.IsEnabled = !string.IsNullOrWhiteSpace(settings.Server);

        UpdateServiceCard(serviceState);
        UpdateNebulaCard(status, tun);
        UpdateDnsCard(settings);
        // Deliberately NOT refreshed by the 2s timer (unlike the cards above): this
        // panel holds interactive checkboxes/radios, and rebuilding it periodically
        // could disrupt a mid-click user. It's refreshed on load, the Refresh
        // button, and immediately after the user's own accept/reject action below.
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

    private void UpdateNebulaCard(NebulaStatus status, TunConfig? tun)
    {
        var processRunning = Process.GetProcessesByName("nebula").Length > 0;
        var (color, text) = status.State switch
        {
            "connected" => (Colors.SeaGreen, "Connected"),
            "idle" => (Colors.SteelBlue, "Idle"),
            "error" => (Colors.Firebrick, "Error"),
            "starting" => (Colors.Goldenrod, "Starting"),
            "stopped" => (Colors.Gray, "Stopped"),
            _ => (Colors.Gray, "Unknown"),
        };
        NebulaDot.Fill = new SolidColorBrush(color);
        NebulaStateText.Text = text;

        var sb = new StringBuilder();
        sb.Append(status.Message);
        if (tun?.Dev is { Length: > 0 } dev)
        {
            sb.Append(" · Interface: ").Append(dev);
        }
        sb.Append(processRunning ? " · Nebula process running" : " · Nebula process not running");
        if (status.UpdatedAt is { Length: > 0 } updated)
        {
            sb.Append(" · Updated ").Append(updated);
        }
        NebulaDetailText.Text = sb.ToString();
    }

    private void UpdateDnsCard(NebulaSettings settings)
    {
        var dnsConfigured = File.Exists(SharedPaths.DnsClientConfigPath);
        if (!dnsConfigured)
        {
            DnsDot.Fill = new SolidColorBrush(Colors.Gray);
            DnsStateText.Text = "Not configured for this network";
        }
        else if (settings.AcceptDns)
        {
            DnsDot.Fill = new SolidColorBrush(Colors.SeaGreen);
            DnsStateText.Text = "Active";
        }
        else
        {
            DnsDot.Fill = new SolidColorBrush(Colors.Goldenrod);
            DnsStateText.Text = "Available, not enabled (see Settings)";
        }
    }

    private async Task RefreshRoutingAsync()
    {
        var settings = SettingsStore.Load();
        var token = TokenStore.GetToken();

        var advertised = !string.IsNullOrWhiteSpace(settings.Server) && token is not null
            ? await BackendClient.GetAdvertisedRoutesAsync(settings.Server, token)
            : new List<string>();
        AdvertisingText.Text = advertised.Count > 0
            ? string.Join(", ", advertised)
            : "Nothing (not acting as a gateway)";

        RefreshRoutesPicker(settings);
    }

    /// <summary>Rebuilds the subnet-route checkboxes and exit-node radio buttons
    /// from available-routes.json (everything the server authorizes this node to
    /// consume) against settings.json (what's been locally accepted) - the
    /// client-side consent gate described in docs/unsafe-routes.md. Local-only,
    /// no network call.</summary>
    private void RefreshRoutesPicker(NebulaSettings settings)
    {
        var available = RoutesStore.Load();
        var acceptedSubnetRoutes = settings.AcceptedSubnetRoutes ?? new List<SubnetRouteRef>();
        var acceptedExitVia = settings.AcceptedExitNode?.Via;

        SubnetRoutesPanel.Children.Clear();
        var subnetRoutes = available.Where(r => !r.IsExit).ToList();
        NoSubnetRoutesText.Visibility = subnetRoutes.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        foreach (var route in subnetRoutes)
        {
            var isAccepted = acceptedSubnetRoutes.Any(a => a.Route == route.Route && a.Via == route.Via);
            var checkbox = new CheckBox
            {
                Content = $"{route.Route} via {route.Via}",
                IsChecked = isAccepted,
                Tag = route,
            };
            if (!isAccepted)
            {
                var conflict = CidrUtil.ValidateNewSubnetRoute(route.Route, acceptedSubnetRoutes);
                if (conflict is not null)
                {
                    checkbox.IsEnabled = false;
                    ToolTipService.SetToolTip(checkbox, conflict);
                }
            }
            checkbox.Checked += SubnetRouteCheckbox_Toggled;
            checkbox.Unchecked += SubnetRouteCheckbox_Toggled;
            SubnetRoutesPanel.Children.Add(checkbox);
        }

        ExitNodePanel.Children.Clear();
        // Exit routes always come in a 0.0.0.0/0 + ::/0 pair from the same gateway
        // (same via) - group them into one radio option per gateway.
        var exitGateways = available.Where(r => r.IsExit).Select(r => r.Via).Distinct().ToList();
        NoExitNodesText.Visibility = exitGateways.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        if (exitGateways.Count > 0)
        {
            var noneRadio = new RadioButton { Content = "None", GroupName = "ExitNode", IsChecked = acceptedExitVia is null };
            noneRadio.Checked += ExitNodeRadio_Checked;
            ExitNodePanel.Children.Add(noneRadio);
            foreach (var via in exitGateways)
            {
                var radio = new RadioButton
                {
                    Content = $"Exit node via {via}",
                    GroupName = "ExitNode",
                    IsChecked = via == acceptedExitVia,
                    Tag = via,
                };
                radio.Checked += ExitNodeRadio_Checked;
                ExitNodePanel.Children.Add(radio);
            }
        }
    }

    private void SubnetRouteCheckbox_Toggled(object sender, RoutedEventArgs e)
    {
        if (sender is not CheckBox { Tag: AvailableRoute route } checkbox)
        {
            return;
        }
        var settings = SettingsStore.Load();
        var accepted = settings.AcceptedSubnetRoutes ?? new List<SubnetRouteRef>();
        var wantAccepted = checkbox.IsChecked == true;
        var isCurrentlyAccepted = accepted.Any(a => a.Route == route.Route && a.Via == route.Via);
        if (wantAccepted == isCurrentlyAccepted)
        {
            return;
        }

        if (wantAccepted)
        {
            var conflict = CidrUtil.ValidateNewSubnetRoute(route.Route, accepted);
            if (conflict is not null)
            {
                // Shouldn't normally happen (conflicting boxes are disabled), but a
                // stale rebuild race is possible - revert and explain rather than
                // silently accepting a conflicting route.
                checkbox.IsChecked = false;
                ShowRoutesResult(InfoBarSeverity.Error, conflict);
                return;
            }
            accepted = accepted.Where(a => a.Route != route.Route).ToList();
            accepted.Add(new SubnetRouteRef { Route = route.Route, Via = route.Via });
            ShowRoutesResult(InfoBarSeverity.Success, $"Accepted {route.Route} via {route.Via}.");
        }
        else
        {
            accepted = accepted.Where(a => a.Route != route.Route).ToList();
            ShowRoutesResult(InfoBarSeverity.Success, $"Rejected {route.Route}.");
        }

        settings.AcceptedSubnetRoutes = accepted;
        SettingsStore.Save(settings);
        _ = PipeClient.SendCommandAsync(PipeClient.CmdPollNow);
        RefreshRoutesPicker(settings); // re-evaluate conflict-disabled state for the other checkboxes
    }

    private void ExitNodeRadio_Checked(object sender, RoutedEventArgs e)
    {
        if (sender is not RadioButton radio)
        {
            return;
        }
        var via = radio.Tag as string; // null for the "None" option
        var settings = SettingsStore.Load();
        if (settings.AcceptedExitNode?.Via == via)
        {
            return;
        }
        settings.AcceptedExitNode = via is not null ? new ExitNodeRef { Via = via } : null;
        SettingsStore.Save(settings);
        _ = PipeClient.SendCommandAsync(PipeClient.CmdPollNow);
        ShowRoutesResult(
            InfoBarSeverity.Success,
            via is not null ? $"Accepted exit node via {via}." : "Rejected the exit node.");
    }

    private void ShowRoutesResult(InfoBarSeverity severity, string message)
    {
        RoutesResultBar.Severity = severity;
        RoutesResultBar.Title = severity == InfoBarSeverity.Error ? "Routes" : "";
        RoutesResultBar.Message = message;
        RoutesResultBar.IsOpen = true;
    }

    private void ServerLink_Click(object sender, RoutedEventArgs e)
    {
        var server = SettingsStore.Load().Server;
        if (string.IsNullOrWhiteSpace(server))
        {
            return;
        }
        Process.Start(new ProcessStartInfo { FileName = server, UseShellExecute = true });
    }

    private async void TestConnectionButton_Click(object sender, RoutedEventArgs e)
    {
        var server = SettingsStore.Load().Server;
        if (string.IsNullOrWhiteSpace(server))
        {
            TestConnectionResult.Text = "No server configured.";
            return;
        }
        TestConnectionButton.IsEnabled = false;
        TestConnectionResult.Text = "Testing...";
        try
        {
            var (_, message) = await BackendClient.TestConnectionAsync(server);
            TestConnectionResult.Text = message;
        }
        finally
        {
            TestConnectionButton.IsEnabled = true;
        }
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
            // ServiceControl's Start/Stop/Restart block on WaitForStatus (up to
            // 15s) - keep that off the UI thread so the page stays responsive.
            await Task.Run(action);
            ServiceActionResult.Text = $"Service {verb}.";
        }
        catch (Exception ex)
        {
            ServiceActionResult.Text = $"Failed: {ex.Message}";
        }
        finally
        {
            ServiceProgress.IsActive = false;
            RefreshLocal();
        }
    }

    private async void ViewConfigButton_Click(object sender, RoutedEventArgs e)
    {
        string content;
        try
        {
            content = File.Exists(SharedPaths.ConfigPath)
                ? File.ReadAllText(SharedPaths.ConfigPath)
                : "config.yaml not found yet - not enrolled, or the service hasn't polled successfully.";
        }
        catch (Exception ex)
        {
            content = $"Failed to read config.yaml: {ex.Message}";
        }

        var textBlock = new TextBlock
        {
            Text = content,
            TextWrapping = TextWrapping.NoWrap,
            FontFamily = new FontFamily("Cascadia Mono, Consolas"),
        };
        var scrollViewer = new ScrollViewer
        {
            Content = textBlock,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            MaxHeight = 500,
            MaxWidth = 700,
        };

        var dialog = new ContentDialog
        {
            Title = "config.yaml",
            Content = scrollViewer,
            CloseButtonText = "Close",
            XamlRoot = XamlRoot,
        };
        await dialog.ShowAsync();
    }

    private void OpenFolderButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"\"{SharedPaths.Root}\"",
                UseShellExecute = true,
            });
        }
        catch
        {
            // Best-effort convenience action; nothing meaningful to surface if it fails.
        }
    }
}
