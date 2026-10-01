# Public endpoint and additional reachable addresses

A node has two optional settings that tell the rest of the mesh where to find it
on the underlay network. They reach peers by different paths, so they are
separate fields.

| | Public endpoint | Additional reachable addresses |
|---|---|---|
| Where to set it | Node details panel | Node details → **Advanced** |
| Values | One `host:port` (hostname, IPv4, or `[IPv6]`) | Up to 8 `IP:port`, added one at a time |
| Nebula setting | Every peer's `static_host_map` | This node's own `lighthouse.advertise_addrs` |
| How peers learn it | Written into their config | Reported to the lighthouses, which pass it on |
| Lighthouses and relays | Required | Not shown for lighthouses (Nebula ignores it there) |

## When to use additional reachable addresses

Use them for addresses Nebula can't discover on its own:

- A port forward on the router in front of the node, especially when the
  external port is not 4242.
- A second uplink or a LAN address that peers on the same site should try.

Nebula already reports the node's local interface addresses and the address a
lighthouse sees it connect from. This list should have what that doesn't cover.

## Rules

- Add addresses one at a time: type an `IP:port` and click **Add**, and use the
  trash button next to an address to remove it. Through the API,
  `advertise_addrs` is a list with one address per item.
- IP addresses only. Nebula resolves a hostname here once at startup and does
  not start if the lookup fails.
- Port `0` means the node's own listen port (4242).
- Addresses inside the Nebula network, loopback, link-local, multicast,
  reserved (`240.0.0.0/4`, including the broadcast address `255.255.255.255`),
  IPv4-mapped IPv6 (use the plain IPv4 address instead), and `0.0.0.0` / `::`
  are rejected.
- IPv4 addresses ending in `.0` or `.255` are accepted, with a warning next to
  them: on a `/24` LAN they're the network/broadcast address and won't work, but
  on a larger LAN they can be ordinary hosts.
- Changing the list restarts Nebula on that node only. It does not re-sign the
  certificate.
