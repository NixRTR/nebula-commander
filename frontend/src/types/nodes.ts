export interface LighthouseOptions {
  serve_dns?: boolean;
  dns_host?: string;
  dns_port?: number;
  interval_seconds?: number;
}

export interface Node {
  id: number;
  network_id: number;
  hostname: string;
  ip_address: string | null;
  cert_fingerprint: string | null;
  groups: string[];
  is_lighthouse: boolean;
  public_endpoint: string | null;
  lighthouse_options: LighthouseOptions | null;
  status: string;
  last_seen: string | null;
  created_at: string;
}
