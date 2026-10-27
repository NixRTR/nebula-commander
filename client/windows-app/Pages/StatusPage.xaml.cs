using System.Diagnostics;
using System.Text;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Pages;

/// <summary>One network's status, routes, exit node and config. Opened from
/// <see cref="NetworksPage"/> with the <see cref="NetworkInfo"/> as the navigation
/// parameter; without one (service from before 0.8.0) it shows the service's only
/// network.</summary>
public sealed partial class StatusPage : Page
{
    private NetworkInfo? _network;
    private string? NetworkId => _network?.Id;

    // Cheap local refresh (pipe reads + service query, no network) on a short
    // timer so the page feels live; routing info hits the backend so it's only
    // refetched on page load / the Refresh button, not on every tick.
    private readonly DispatcherTimer _timer;
    private bool _refreshingLocal;
    // Set while RefreshRoutesPicker rebuilds the controls, so the Checked/
    // Unchecked events it triggers aren't mistaken for user actions.
    private bool _rebuildingRoutes;
    private TunConfig? _tun;
    // Fallback for this node's IP: Windows services up to 0.8.1 can leave list_networks'
    // overlay_ip empty (recorded only at the moment of connecting), so ask once per full
    // refresh instead - get_connectivity pings the lighthouses, too slow for the timer.
    private string? _connectivityIp;

    public StatusPage()
    {
        InitializeComponent();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        _timer.Tick += async (_, _) => await RefreshLocalAsync();
        Loaded += StatusPage_Loaded;
        Unloaded += (_, _) => _timer.Stop();
        OpenFolderButton.IsEnabled = Elevation.IsElevated;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _network = e.Parameter as NetworkInfo;
        TitleText.Text = _network?.DisplayName ?? "Status";
        LeaveButton.Visibility = _network is null ? Visibility.Collapsed : Visibility.Visible;
    }

    private async void LeaveButton_Click(object sender, RoutedEventArgs e)
    {
        if (_network is null)
        {
            return;
        }
        var dialog = new ContentDialog
        {
            Title = $"Leave {_network.DisplayName}?",
            Content = "Nebula stops for this network and the device forgets its token. Joining again needs a new enrollment code.",
            PrimaryButtonText = "Leave network",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }
        var result = await ServiceApi.RemoveNetworkAsync(_network.Id);
        if (!result.Ok)
        {
            if (result.AdministratorRequired)
            {
                App.MainWindowInstance?.ShowAdminRequired();
            }
            LeaveResultBar.Severity = InfoBarSeverity.Error;
            LeaveResultBar.Title = "Leave network";
            LeaveResultBar.Message = ServiceApi.Describe(result);
            LeaveResultBar.IsOpen = true;
            return;
        }
        if (Frame.CanGoBack)
        {
            Frame.GoBack();
        }
        else
        {
            App.MainWindowInstance?.NavigateToTag("networks");
        }
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
            var config = await ServiceApi.GetConfigYamlAsync(NetworkId);
            _tun = config.Ok && config.Result.ValueKind == System.Text.Json.JsonValueKind.String
                ? ConfigYaml.ParseTunConfig(config.Result.GetString())
                : null;
            await RefreshLocalAsync();
            await RefreshRoutingAsync();
            _connectivityIp = (await ServiceApi.GetConnectivityAsync(NetworkId))?.OverlayIp;
            await RefreshLocalAsync();
        }
        finally
        {
            RefreshButton.IsEnabled = true;
            RefreshProgress.IsActive = false;
        }
    }

    private async Task RefreshLocalAsync()
    {
        if (_refreshingLocal)
        {
            return;
        }
        _refreshingLocal = true;
        try
        {
            var settings = await ServiceApi.GetSettingsAsync(NetworkId) ?? new NebulaSettings();
            var status = await ServiceApi.GetStatusAsync(NetworkId);
            var dnsConfigured = await ServiceApi.GetDnsConfiguredAsync(NetworkId);
            var networks = await ServiceApi.ListNetworksAsync();
            var overlayIp = networks?.FirstOrDefault(n => n.Id == NetworkId)?.OverlayIp
                ?? (NetworkId is null ? networks?.FirstOrDefault()?.OverlayIp : null);
            if (string.IsNullOrWhiteSpace(overlayIp))
            {
                overlayIp = _connectivityIp;
            }
            OverlayIpText.Text = string.IsNullOrWhiteSpace(overlayIp) ? "—" : overlayIp;
            CopyIpButton.IsEnabled = !string.IsNullOrWhiteSpace(overlayIp);

            var server = string.IsNullOrWhiteSpace(settings.Server) ? "(not set)" : settings.Server;
            ServerLink.Content = server;
            ServerLink.IsEnabled = !string.IsNullOrWhiteSpace(settings.Server);

            UpdateNebulaCard(status, _tun);
            UpdateDnsCard(settings, dnsConfigured);
        }
        finally
        {
            _refreshingLocal = false;
        }
        // Deliberately NOT refreshed by the 2s timer (unlike the cards above): this
        // panel holds interactive checkboxes/radios, and rebuilding it periodically
        // could disrupt a mid-click user. It's refreshed on load, the Refresh
        // button, and immediately after the user's own accept/reject action below.
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
            "updating" => (Colors.Goldenrod, "Updating Nebula"),
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

    private void UpdateDnsCard(NebulaSettings settings, bool dnsConfigured)
    {
        if (!dnsConfigured)
        {
            DnsDot.Fill = new SolidColorBrush(Colors.Gray);
            DnsStateText.Text = "Not configured for this network";
        }
        else if (settings.AcceptDns == true)
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
        // Fetched by the service with the device token - the app never sees it.
        var advertised = await ServiceApi.GetAdvertisedRoutesAsync(NetworkId);
        AdvertisingText.Text = advertised.Count > 0
            ? string.Join(", ", advertised)
            : "Nothing (not acting as a gateway)";

        await RebuildRoutesPickerAsync();
    }

    private async Task RebuildRoutesPickerAsync()
    {
        var settings = await ServiceApi.GetSettingsAsync(NetworkId) ?? new NebulaSettings();
        var available = await ServiceApi.GetAvailableRoutesAsync(NetworkId);
        RefreshRoutesPicker(settings, available);
    }

    /// <summary>Rebuilds the subnet-route checkboxes and exit-node radio buttons
    /// from available-routes.json (everything the server authorizes this node to
    /// consume) against settings.json (what's been locally accepted) - the
    /// client-side consent gate described in docs/unsafe-routes.md. Both read
    /// from the service; no network call.</summary>
    private void RefreshRoutesPicker(NebulaSettings settings, List<AvailableRoute> available)
    {
        _rebuildingRoutes = true;
        try
        {
            BuildRoutesPicker(settings, available);
        }
        finally
        {
            _rebuildingRoutes = false;
        }
    }

    private void BuildRoutesPicker(NebulaSettings settings, List<AvailableRoute> available)
    {
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
        ExitAllowLanCheckBox.Visibility = exitGateways.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        ExitReplaceNote.Visibility = exitGateways.Count > 0 && settings.HostExitActive == true && acceptedExitVia is null
            ? Visibility.Visible
            : Visibility.Collapsed;
        ExitAllowLanCheckBox.IsChecked = settings.ExitAllowLan != false;
    }

    private async void ExitAllowLanCheckBox_Toggled(object sender, RoutedEventArgs e)
    {
        if (_rebuildingRoutes)
        {
            return;
        }
        var allowLan = ExitAllowLanCheckBox.IsChecked == true;
        var result = await ServiceApi.SetExitAllowLanAsync(allowLan);
        HandleRouteResult(result, allowLan
            ? "Local-network traffic stays direct while using an exit node."
            : "Local-network traffic now goes through the exit node too.");
        await RebuildRoutesPickerAsync();
    }

    private async void SubnetRouteCheckbox_Toggled(object sender, RoutedEventArgs e)
    {
        if (_rebuildingRoutes || sender is not CheckBox { Tag: AvailableRoute route } checkbox)
        {
            return;
        }
        var wantAccepted = checkbox.IsChecked == true;
        // The service validates (offered? overlapping?) and restarts its poll
        // loop; on any failure the picker is rebuilt from the service's state,
        // which reverts this checkbox.
        var result = wantAccepted
            ? await ServiceApi.AcceptRouteAsync(route.Route, route.Via, NetworkId)
            : await ServiceApi.RejectRouteAsync(route.Route, NetworkId);
        HandleRouteResult(result, wantAccepted
            ? $"Accepted {route.Route} via {route.Via}."
            : $"Rejected {route.Route}.");
        await RebuildRoutesPickerAsync(); // re-evaluate conflict-disabled state for the other checkboxes
    }

    private async void ExitNodeRadio_Checked(object sender, RoutedEventArgs e)
    {
        if (_rebuildingRoutes || sender is not RadioButton radio)
        {
            return;
        }
        var via = radio.Tag as string; // null for the "None" option
        var result = via is not null
            ? await ServiceApi.AcceptExitNodeAsync(via, NetworkId)
            : await ServiceApi.RejectExitNodeAsync(NetworkId);
        HandleRouteResult(result, via is not null ? $"Accepted exit node via {via}." : "Rejected the exit node.");
        await RebuildRoutesPickerAsync();
    }

    private void HandleRouteResult(PipeClient.PipeResponse result, string successMessage)
    {
        if (result.Ok)
        {
            ShowRoutesResult(InfoBarSeverity.Success, successMessage);
            return;
        }
        if (result.AdministratorRequired)
        {
            App.MainWindowInstance?.ShowAdminRequired();
        }
        ShowRoutesResult(InfoBarSeverity.Error, ServiceApi.Describe(result));
    }

    private void ShowRoutesResult(InfoBarSeverity severity, string message)
    {
        RoutesResultBar.Severity = severity;
        RoutesResultBar.Title = severity == InfoBarSeverity.Error ? "Routes" : "";
        RoutesResultBar.Message = message;
        RoutesResultBar.IsOpen = true;
    }

    private void CopyIpButton_Click(object sender, RoutedEventArgs e)
    {
        var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
        package.SetText(OverlayIpText.Text);
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
    }

    private async void ServerLink_Click(object sender, RoutedEventArgs e)
    {
        var server = (await ServiceApi.GetSettingsAsync(NetworkId))?.Server;
        if (string.IsNullOrWhiteSpace(server))
        {
            return;
        }
        Process.Start(new ProcessStartInfo { FileName = server, UseShellExecute = true });
    }

    private async void TestConnectionButton_Click(object sender, RoutedEventArgs e)
    {
        var server = (await ServiceApi.GetSettingsAsync(NetworkId))?.Server;
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

    private async void ViewConfigButton_Click(object sender, RoutedEventArgs e)
    {
        // Served by the service with pki.key redacted - the node's private key
        // is never shown or readable outside the SYSTEM-only state folder.
        var result = await ServiceApi.GetConfigYamlAsync(NetworkId);
        var content = result.Ok && result.Result.ValueKind == System.Text.Json.JsonValueKind.String
            ? result.Result.GetString() ?? ""
            : result.Unreachable
                ? $"Service not reachable: {result.Error}"
                : "config.yaml not found yet - not enrolled, or the service hasn't polled successfully.";

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
                Arguments = $"\"{(NetworkId is null ? SharedPaths.Root : System.IO.Path.Combine(SharedPaths.Root, "networks", NetworkId))}\"",
                UseShellExecute = true,
            });
        }
        catch
        {
            // Best-effort convenience action; nothing meaningful to surface if it fails.
        }
    }
}
