/** Defined.net-style inbound rule: who can send traffic to this group. */
export interface InboundFirewallRule {
  allowed_group: string;
  protocol: "any" | "tcp" | "udp" | "icmp";
  port_range: string;
  description?: string;
}

export interface Network {
  id: number;
  name: string;
  subnet_cidr: string;
  ca_cert_path: string | null;
  created_at: string;
  role?: string;
  can_manage_nodes?: boolean;
  can_invite_users?: boolean;
  can_manage_firewall?: boolean;
}

export interface NetworkCreate {
  name: string;
  subnet_cidr: string;
}

export interface NetworkUpdateData {
  // No network-level firewall; use Groups page for per-group inbound rules.
}

export interface GroupFirewallConfig {
  group_name: string;
  inbound_rules: InboundFirewallRule[];
}
