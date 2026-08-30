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
  created_at: string;
}
