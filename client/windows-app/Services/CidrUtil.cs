using System.Net;

namespace NebulaCommanderApp.Services;

/// <summary>
/// CIDR overlap checking for the subnet-route accept picker - mirrors
/// client/ncclient.py's validate_new_subnet_route
/// (ipaddress.ip_network(...).overlaps(...)) so the Windows app rejects the
/// same conflicting selections the CLI would, without needing to shell out
/// to Python for it.
/// </summary>
public static class CidrUtil
{
    /// <summary>True if two CIDR strings' address ranges intersect at all.
    /// Different address families never overlap. Invalid input is treated as
    /// non-overlapping (the caller is expected to validate parseability
    /// separately, e.g. via ValidateNewSubnetRoute).</summary>
    public static bool Overlaps(string cidrA, string cidrB)
    {
        if (!IPNetwork.TryParse(cidrA, out var a) || !IPNetwork.TryParse(cidrB, out var b))
        {
            return false;
        }
        if (a.BaseAddress.AddressFamily != b.BaseAddress.AddressFamily)
        {
            return false;
        }
        var minPrefix = Math.Min(a.PrefixLength, b.PrefixLength);
        return Truncate(a.BaseAddress, minPrefix).Equals(Truncate(b.BaseAddress, minPrefix));
    }

    /// <summary>Masks an address down to its network portion at the given
    /// prefix length, so two networks can be compared for containment at
    /// whichever is the shorter (less specific) of the two prefixes.</summary>
    private static IPAddress Truncate(IPAddress address, int prefixLength)
    {
        var bytes = address.GetAddressBytes();
        var result = new byte[bytes.Length];
        var fullBytes = prefixLength / 8;
        var remainingBits = prefixLength % 8;
        Array.Copy(bytes, result, Math.Min(fullBytes, bytes.Length));
        if (remainingBits > 0 && fullBytes < bytes.Length)
        {
            var mask = (byte)(0xFF << (8 - remainingBits));
            result[fullBytes] = (byte)(bytes[fullBytes] & mask);
        }
        return new IPAddress(result);
    }

    /// <summary>Error message if accepting newCidr would overlap any already-
    /// accepted subnet route, or if newCidr itself doesn't parse; null if
    /// it's safe to accept.</summary>
    public static string? ValidateNewSubnetRoute(string newCidr, IEnumerable<SubnetRouteRef> currentlyAccepted)
    {
        if (!IPNetwork.TryParse(newCidr, out _))
        {
            return $"Invalid CIDR: {newCidr}";
        }
        foreach (var existing in currentlyAccepted)
        {
            if (!string.IsNullOrEmpty(existing.Route) && Overlaps(newCidr, existing.Route))
            {
                return $"{newCidr} overlaps already-accepted {existing.Route} (via {existing.Via})";
            }
        }
        return null;
    }
}
