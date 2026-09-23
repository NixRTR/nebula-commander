# Subnet routers and exit nodes

Nebula Commander can turn a node into a **subnet router** (it advertises a LAN behind it
to the rest of the mesh, the way `tailscale up --advertise-routes` does) or an **exit
node** (it advertises `0.0.0.0/0`/`::/0` and routes all of another node's traffic, the
way `tailscale up --advertise-exit-node` does). Both build on Nebula's own
[`unsafe_routes`](https://nebula.defined.net/docs/config/tun/#tununsafe_routes) feature.

This doc covers how it's configured from both sides — the gateway that advertises a
route, and the other nodes that actually use it — what happens automatically for
nodes running `ncclient` on Linux, and — the part that's easy to miss — what you
have to do yourself for everything else (Windows, macOS, Docker-deployed `ncclient`,
or bare `nebula`).

## Two sides of the same setting

Every route has a **gateway** (the node advertising it) and one or more
**consumers** (the nodes that actually route through it). Nebula Commander exposes
both sides in a node's details panel:

- On the **gateway** node, under **Advanced → Subnet Router & Exit Node Config**
  (and **Advanced → Exit Node**), you choose what this node advertises and, per
  route, a **"Used by"** checklist of which other nodes are allowed to consume it.
- On a **consumer** node, the visible (non-Advanced) **Use Subnet Router** and
  **Use Exit Node** dropdowns let you pick a gateway directly, without opening the
  gateway's own settings.

Both mechanisms write to the same data: picking a gateway from a consumer's
dropdown adds that consumer to the gateway's "Used by" list for every matching
route, and clears it from any other gateway's routes of the same kind (a node uses
at most one subnet router and one exit node at a time). **Either way, a route
reaches nobody until an admin explicitly says who it's for** — advertising a route
is never enough on its own.

## Setting up a route (gateway side)

In a node's details panel (**Nodes → *hostname* → Edit**), expand **Advanced**:

- **Exit Node** — a single checkbox, **Exit node (route all traffic)**. Checking it
  advertises both `0.0.0.0/0` and `::/0` from this node.
- **Subnet Router & Exit Node Config → Advertised subnets** — a checklist of local
  interfaces `ncclient` discovered on this node (ethernet, Wi-Fi, Tailscale, or
  another Nebula interface on the same host; Docker interfaces are never offered).
  Only populated for nodes actively running `ncclient` on Linux.
- **Subnet Router & Exit Node Config → Other** — type any CIDR by hand. Use this for
  a subnet reachable through the node by some other means `ncclient` can't detect on
  its own, or on a node not running `ncclient` at all.

Under each route is a **"Used by"** disclosure — expand it and check off which other
nodes on the network should actually receive a route to it.

## Picking a route (consumer side)

On any other node's details panel — visible without opening Advanced:

- **Use Subnet Router** — a dropdown listing every other node on the network that
  advertises at least one subnet. Choosing one routes this node's traffic for all of
  that gateway's advertised subnets through it; **None** stops using one.
- **Use Exit Node** — the same idea for full-tunnel routing: a dropdown of every
  other node advertising an exit route.

This works for every platform, not just desktop/`ncclient` nodes - a mobile node can
pick a subnet router or exit node too, since consuming a route needs no host
automation, just the generated Nebula config.

## Accepting a route locally (desktop `ncclient` nodes)

The picker above is server-side authorization - it controls what a node is *allowed*
to consume, the same way DNS being enabled for a network doesn't by itself mean a
device applies it (`accept_dns`/`--accept-dns` is the separate, local opt-in for
that). Subnet routers and exit nodes work the same way on desktop `ncclient` nodes
(Linux and Windows): being picked as a consumer makes the route *available*, not
automatically *active*. `ncclient` writes everything it's authorized to consume to
`available-routes.json` in its output directory, but only writes the locally
*accepted* subset into `config.yaml` for Nebula to actually use.

- **CLI** (`ncclient` on Linux, `ncclient.exe` on Windows - same commands either
  way): `ncclient routes list` shows what's available and what's currently
  accepted; `ncclient routes accept <CIDR>` / `routes reject <CIDR>` manage subnet
  routes, `routes accept-exit-node --via <IP>` / `routes reject-exit-node` manage
  the exit node. Multiple subnet routes can be accepted at once as long as their
  CIDRs don't overlap - `accept` rejects an overlapping one with an explanation of
  which already-accepted route it conflicts with. At most one exit node is ever
  accepted at a time.
- **The Windows app** (`client/windows-app/`): the Status page's "Exit Node /
  Subnet Router" card lists the same available/accepted state interactively -
  checkboxes for subnet routes (disabled with a reason if accepting one would
  overlap an already-accepted route) and a single-select list for the exit node.

A locally accepted/rejected change is picked up within one poll cycle without
needing to re-enroll or restart anything by hand (or immediately, if something
nudges the service to poll now - the Windows app already does this after a
Settings change). This is entirely client-side: the "Used by" list above already
determines *authorization*; this is a separate device-level *consent* step on top
of it, and doesn't exist for mobile (Mobile Nebula) nodes, which have no local
ncclient process to gate anything through - a mobile node's only control is the
server-side picker.

## What happens automatically (Linux nodes running `ncclient`)

For a gateway node whose `ncclient` has confirmed it's Linux (shown by the absence
of the amber warning under Advanced → Subnet Router & Exit Node Config):

1. Nebula Commander generates the correct `tun.unsafe_routes` entry (with the
   required `via`) in every *consumer* node's config, and signs the gateway's own
   certificate with the `-subnets` claim Nebula requires before it will let that node
   route the CIDR at all.
2. `ncclient` on the gateway polls `GET /api/device/advertised-routes` and, when its
   own advertised routes change, enables IP forwarding
   (`net.ipv4.ip_forward`, and `net.ipv6.conf.all.forwarding` if any route is IPv6)
   and installs a dedicated `inet ncclient_routing` nftables table: forwarding
   accept rules scoped to each advertised subnet, and a masquerade rule for the
   exit-node case.

None of this needs the admin to touch the host directly. `nft` (nftables) must be
installed on the gateway for step 2 to work - `ncclient` logs a warning and skips it
if `nft` isn't found, leaving the route inert.

## What you have to do yourself (hosts not running `ncclient` on Linux)

This includes Windows nodes, macOS, a Docker-deployed `ncclient` (it runs in its own
network namespace, so it can't reach the host's routing table at all), or any host
running the bare `nebula` binary directly. Nebula Commander still generates the
correct config for these nodes - `ncclient`'s automation is the only piece that's
Linux-only. On such a gateway node you need to:

1. **Get the config onto the host.** Either let a non-Linux/bare `ncclient` write it
   normally, or download it yourself from the node's **Config** button (admin UI) or
   `GET /api/device/config` (device token) and place it where `nebula -config
   <path>` expects it.
2. **Enable IP forwarding.**
   - Linux (no `ncclient`): `sysctl -w net.ipv4.ip_forward=1` (and
     `net.ipv6.conf.all.forwarding=1` for IPv6 routes/exit-node), persisted via a file
     under `/etc/sysctl.d/`.
   - Windows: enable IP forwarding on the network adapter bound to the Nebula tun
     device, and configure routing/NAT (e.g. via `netsh interface ipv4 set interface
     "<adapter>" forwarding=enabled`, plus RRAS if you need NAT for an exit node) -
     consult Microsoft's routing documentation for your Windows version.
   - macOS: `sysctl -w net.inet.ip.forwarding=1`, plus `pfctl` for NAT.
3. **Allow forwarding and (for an exit node) NAT between the Nebula tun interface and
   your physical interface.** On Linux with nftables, this is exactly what
   [`client/linux_routing.py`](../client/linux_routing.py) does for `ncclient` - use
   it as a reference. For a subnet route to `192.168.1.0/24` via tun device `nebula1`:

   ```
   table inet ncclient_routing {
       chain forward {
           type filter hook forward priority filter; policy accept;
           iifname "nebula1" ip daddr 192.168.1.0/24 accept
           ip saddr 192.168.1.0/24 oifname "nebula1" accept
       }
   }
   ```

   For an exit node, add a NAT table masquerading traffic from the tun device out
   your uplink interface (`eth0` below):

   ```
   table inet ncclient_routing {
       chain postrouting {
           type nat hook postrouting priority srcnat; policy accept;
           iifname "nebula1" oifname "eth0" masquerade
       }
   }
   ```

   `iptables`-only systems need the equivalent `iptables -A FORWARD ...` /
   `iptables -t nat -A POSTROUTING ... -j MASQUERADE` rules.

## Troubleshooting

**`nebula` fails to start with `Could not parse tun.unsafe_routes: entry N.via ... is
not present`** - you're running a config from before Nebula Commander added the
`via`/`-subnets` fix, or a hand-edited config that omits `via`. Re-download the
config; every generated `tun.unsafe_routes` entry always includes `via` now. If this
is your own config (not Nebula Commander's), every entry needs a `via` pointing at
the gateway node's Nebula IP.

**A consumer node has the route in its config, but traffic to the subnet doesn't
arrive** - most likely the gateway's own firewall. Since Nebula 1.10, a firewall rule
only matches traffic to the node's *own* Nebula IP unless it also sets `local_cidr` -
Nebula Commander generates a `local_cidr`-scoped accept rule for each advertised
subnet, one per node in that route's "Used by" list, matched by that consumer's own
certificate-verified Nebula IP (`cidr: <ip>/32`). If the consumer isn't actually
selected in "Used by" - even if it somehow has the route in its own config, e.g. a
hand-edited config or a non-`ncclient` host - the gateway has no matching rule and
will drop the forwarded traffic; check the "Used by" list first. A manually-written
config for a non-`ncclient` gateway needs the equivalent `cidr`/`local_cidr` rules
added by hand. See [Nebula's firewall docs](https://nebula.defined.net/docs/config/firewall/)
for the exact rule shape.

**The route works for one node but not another** - check that node's selection:
either its own **Use Subnet Router**/**Use Exit Node** dropdown, or the "Used by"
list on the gateway it should be using. A route only reaches nodes explicitly
selected on one side or the other, and - since the gateway's firewall now enforces
this per node, not just config distribution - an unselected node can't use the
route even if it has (or is given) a matching `tun.unsafe_routes` entry by some
other means.
