import { apiFetch } from "./client";

export interface DNSConfig {
  domain: string;
  enabled: boolean;
  upstream_servers: string[];
}

export interface DNSAlias {
  id: number;
  alias: string;
  node_id: number;
  node_hostname: string;
}

export async function getDNSConfig(networkId: number): Promise<DNSConfig> {
  return apiFetch<DNSConfig>(`/networks/${networkId}/dns`);
}

export async function upsertDNSConfig(
  networkId: number,
  body: { domain: string; enabled: boolean; upstream_servers?: string[] }
): Promise<DNSConfig> {
  return apiFetch<DNSConfig>(`/networks/${networkId}/dns`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function listDNSAliases(networkId: number): Promise<DNSAlias[]> {
  return apiFetch<DNSAlias[]>(`/networks/${networkId}/dns/aliases`);
}

export async function createDNSAlias(
  networkId: number,
  body: { alias: string; node_id: number }
): Promise<DNSAlias> {
  return apiFetch<DNSAlias>(`/networks/${networkId}/dns/aliases`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteDNSAlias(
  networkId: number,
  aliasId: number
): Promise<void> {
  await apiFetch<void>(`/networks/${networkId}/dns/aliases/${aliasId}`, {
    method: "DELETE",
  });
}

export async function listNodesForNetwork(networkId: number) {
  return apiFetch<import("../types/nodes").Node[]>(`/nodes?network_id=${networkId}`);
}

