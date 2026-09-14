export interface LighthouseOptions {
  interval_seconds?: number;
}

/** Nebula logging config: level, format, disable_timestamp, timestamp_format (Go time format). */
export interface LoggingOptions {
  level?: "panic" | "fatal" | "error" | "warning" | "info" | "debug";
  format?: "json" | "text";
  disable_timestamp?: boolean;
  timestamp_format?: string;
}

export interface PunchyOptions {
  respond?: boolean;
  delay?: string;
  respond_delay?: string;
}

export type NodePlatform = "desktop" | "ios" | "android";

/** A local interface ncclient (Linux only) found and reported as advertisable. */
export type SubnetKind = "ethernet" | "wifi" | "tailscale" | "nebula";

export interface AvailableSubnet {
  interface: string;
  cidr: string;
  kind: SubnetKind;
}

/**
 * Where a node's unsafe_routes entry came from - drives which toggle/checkbox the
 * Routing UI re-hydrates as checked. Only `route` is ever sent to Nebula; source/interface
 * are nebula-commander bookkeeping.
 */
export type RouteSource = "exit_v4" | "exit_v6" | "interface" | "manual";

export interface UnsafeRoute {
  route: string;
  source: RouteSource;
  interface?: string | null;
  /** Node IDs (on this node's network) allowed to actually route to this CIDR via this
   * node. Opt-in: empty by default, so advertising a route doesn't reach anyone until
   * explicitly selected. The exit-node pair (exit_v4 + exit_v6) share one selection. */
  consumers: number[];
}

export interface Node {
  id: number;
  network_id: number;
  hostname: string;
  ip_address: string | null;
  groups: string[];
  is_lighthouse: boolean;
  is_relay: boolean;
  public_endpoint: string | null;
  lighthouse_options: LighthouseOptions | null;
  logging_options: LoggingOptions | null;
  punchy_options: PunchyOptions | null;
  status: string;
  platform: NodePlatform;
  last_seen: string | null;
  first_polled_at: string | null;
  checkin_interval_seconds: number | null;
  lighthouse_reachable: boolean | null;
  lighthouse_checked_at: string | null;
  unsafe_routes: UnsafeRoute[];
  available_subnets: AvailableSubnet[];
  os_platform: string | null;
  created_at: string;
}
