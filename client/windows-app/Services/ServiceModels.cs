using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

// DTOs for the service's pipe API (see ServiceApi.cs). Field names match
// client/config.py / client/service_api.py exactly.

/// <summary>A locally-accepted subnet route: (route, via) - identifies which offered
/// entry in available-routes.json this corresponds to. Matches client/ncclient.py's
/// accepted_subnet_routes shape exactly.</summary>
public sealed class SubnetRouteRef
{
    [JsonPropertyName("route")]
    public string Route { get; set; } = "";

    [JsonPropertyName("via")]
    public string? Via { get; set; }
}

/// <summary>The locally-accepted exit node, identified by its gateway's Nebula IP -
/// at most one at a time. Matches client/ncclient.py's accepted_exit_node shape.</summary>
public sealed class ExitNodeRef
{
    [JsonPropertyName("via")]
    public string? Via { get; set; }
}

/// <summary>settings.json as returned by the service's get_settings (read-only here -
/// changes go through set_settings / accept_* / reject_*).</summary>
public sealed class NebulaSettings
{
    [JsonPropertyName("server")]
    public string? Server { get; set; }

    [JsonPropertyName("interval")]
    public int? Interval { get; set; }

    [JsonPropertyName("accept_dns")]
    public bool? AcceptDns { get; set; }

    [JsonPropertyName("node_id")]
    public int? NodeId { get; set; }

    [JsonPropertyName("accepted_subnet_routes")]
    public List<SubnetRouteRef>? AcceptedSubnetRoutes { get; set; }

    [JsonPropertyName("accepted_exit_node")]
    public ExitNodeRef? AcceptedExitNode { get; set; }
}

/// <summary>One entry from available-routes.json - everything this node is
/// currently authorized to consume (server-side "Used by" list), independent
/// of what's been locally accepted. Written by client/ncclient.py's
/// extract_available_routes/_write_available_routes.</summary>
public sealed class AvailableRoute
{
    [JsonPropertyName("route")]
    public string Route { get; set; } = "";

    [JsonPropertyName("via")]
    public string? Via { get; set; }

    /// <summary>"subnet" or "exit" - 0.0.0.0/0 and ::/0 are always "exit".</summary>
    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "subnet";

    public bool IsExit => Kind == "exit";
}

/// <summary>status.json - the service's self-reported state (see
/// client/windows/shared_paths.py::save_status).</summary>
public sealed class NebulaStatus
{
    [JsonPropertyName("state")]
    public string State { get; set; } = "unknown";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "Service not reachable";

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }
}

/// <summary>Automatic updates - client/service_api.py's get_update_status
/// (settings.json's auto_update merged with update-status.json).</summary>
public sealed class UpdateStatus
{
    [JsonPropertyName("installed_version")]
    public string? InstalledVersion { get; set; }

    [JsonPropertyName("dev_build")]
    public bool DevBuild { get; set; }

    [JsonPropertyName("supported")]
    public bool Supported { get; set; }

    /// <summary>off / install / notify.</summary>
    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "off";

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("window_start")]
    public string WindowStart { get; set; } = "02:00";

    [JsonPropertyName("window_end")]
    public string WindowEnd { get; set; } = "05:00";

    [JsonPropertyName("last_check")]
    public string? LastCheck { get; set; }

    /// <summary>up_to_date / update_available / error.</summary>
    [JsonPropertyName("last_result")]
    public string? LastResult { get; set; }

    [JsonPropertyName("last_error")]
    public string? LastError { get; set; }

    [JsonPropertyName("available_version")]
    public string? AvailableVersion { get; set; }

    [JsonPropertyName("last_install_attempt")]
    public string? LastInstallAttempt { get; set; }

    /// <summary>installing / updated / up_to_date / error.</summary>
    [JsonPropertyName("last_install_result")]
    public string? LastInstallResult { get; set; }

    [JsonPropertyName("last_install_error")]
    public string? LastInstallError { get; set; }
}

public sealed class EnrollmentState
{
    [JsonPropertyName("enrolled")]
    public bool Enrolled { get; set; }

    [JsonPropertyName("server")]
    public string? Server { get; set; }
}
