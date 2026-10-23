# Public endpoint, additional endpoints, listen port and reachable addresses

A node has three optional settings that tell the rest of the mesh where to find
it on the underlay network. They reach peers by different paths, so they are
separate fields. A fourth setting, the listen port, is the UDP port the node
itself binds.

| | Public endpoint | Additional endpoints | Additional reachable addresses |
|---|---|---|---|
| Where to set it | Node details panel | Node details panel, once a public endpoint is set | Node details → **Advanced** |
| Values | One `host:port` (hostname, IPv4, or `[IPv6]`) | Up to 8 `host:port`, added one at a time | Up to 8 `IP:port`, added one at a time |
| Nebula setting | Every peer's `static_host_map` | Every peer's `static_host_map`, after the public endpoint | This node's own `lighthouse.advertise_addrs` |
| How peers learn it | Written into their config | Written into their config | Reported to the lighthouses, which pass it on |
| Lighthouses and relays | Required | Allowed | Not shown for lighthouses (Nebula ignores it there) |

## Additional endpoints

Every peer gets the public endpoint **and** the additional endpoints in its
`static_host_map`, and Nebula tries each of them. Use them for addresses only
some nodes can reach. Nodes that can't reach an address simply skip it.

The typical case is a lighthouse or relay inside an office:

1. Forward UDP 4242 on the office router to the machine, and give it a DHCP
   reservation.
2. Set its **public endpoint** to the office's public address, e.g.
   `64.4.231.35:4242`. Nodes outside the office use this one.
3. Add its **LAN address** as an additional endpoint, e.g.
   `192.168.1.50:4242`. Machines in the office reach it directly, without
   the router having to loop traffic back to its own public address (NAT
   loopback, which many routers don't do for UDP).

Rules:

- Only alongside a public endpoint. Clearing the public endpoint means
  removing the additional endpoints in the same save.
- Same format as the public endpoint: hostname, IPv4 or `[IPv6]`, plus a
  port. Private addresses are fine; loopback, `0.0.0.0`, multicast, reserved
  addresses and addresses inside the Nebula network are rejected.
- An entry repeating the public endpoint or another entry is dropped.
- Changing the list updates every peer's config, so Nebula restarts on every
  node in the network once. It does not re-sign any certificate.

Use **additional reachable addresses** instead when the node isn't a
lighthouse and you only want the lighthouses to hand the address out. Peers
then learn it when they look the node up, and nothing changes in every
other node's config.

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
- Port `0` means the node's own listen port (4242 unless changed).
- Addresses inside the Nebula network, loopback, link-local, multicast,
  reserved (`240.0.0.0/4`, including the broadcast address `255.255.255.255`),
  IPv4-mapped IPv6 (use the plain IPv4 address instead), and `0.0.0.0` / `::`
  are rejected.
- IPv4 addresses ending in `.0` or `.255` are accepted, with a warning next to
  them: on a `/24` LAN they're the network/broadcast address and won't work, but
  on a larger LAN they can be ordinary hosts.
- Changing the list restarts Nebula on that node only. It does not re-sign the
  certificate.

## Listen port

Every node listens on UDP 4242 unless you change it under Node details →
**Listen port**. The value becomes the node's `listen.port`. Give nodes
different ports when:

- Several nodes sit behind one NAT. With the same source port, the NAT can
  keep the port for only one of them and remaps the others unpredictably. With
  distinct ports, each node gets its own predictable mapping and its own port
  forward.
- One host joins more than one network. Each network runs its own nebula on
  that host, and two nebulas can't bind the same port.

Rules:

- `0` lets the operating system pick a free port at each start. Peers learn the
  port through the lighthouses. Lighthouses and relays can't use `0`: peers
  reach them at their public endpoint, which needs a fixed port.
- Changing the port doesn't update the public endpoint. For a lighthouse or
  relay, the public endpoint must point at the new port, or at a port forward
  to it.
- Changing the port restarts Nebula on that node only. It does not re-sign the
  certificate.
- The field is shown for desktop nodes only, like additional reachable
  addresses.
