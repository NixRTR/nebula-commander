export interface LighthouseOptions {
  serve_dns?: boolean;
  dns_host?: string;
  dns_port?: number;
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

export interface Node {
  id: number;
  network_id: number;
  hostname: string;
  ip_address: string | null;
  cert_fingerprint: string | null;
  groups: string[];
  is_lighthouse: boolean;
  is_relay: boolean;
  public_endpoint: string | null;
  lighthouse_options: LighthouseOptions | null;
  logging_options: LoggingOptions | null;
  punchy_options: PunchyOptions | null;
  status: string;
  last_seen: string | null;
  first_polled_at: string | null;
  created_at: string;
}
