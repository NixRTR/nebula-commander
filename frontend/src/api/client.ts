const API_BASE = "/api";
const TOKEN_KEY = "nebula_commander_token";

function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

/** Try to obtain a dev token when backend is in debug mode (development). */
async function tryDevToken(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/auth/dev-token`);
    if (!res.ok) return false;
    const data = (await res.json()) as { token: string };
    if (data.token) {
      localStorage.setItem(TOKEN_KEY, data.token);
      return true;
    }
  } catch {
    // ignore
  }
  return false;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  let res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...getAuthHeaders(), ...options.headers },
  });
  if (res.status === 401 && !localStorage.getItem(TOKEN_KEY)) {
    const got = await tryDevToken();
    if (got) {
      res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: { ...getAuthHeaders(), ...options.headers },
      });
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function listNetworks() {
  return apiFetch<import("../types/networks").Network[]>("/networks");
}

export async function createNetwork(body: import("../types/networks").NetworkCreate) {
  return apiFetch<import("../types/networks").Network>("/networks", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getNetwork(id: number) {
  return apiFetch<import("../types/networks").Network>(`/networks/${id}`);
}

export async function updateNetwork(
  id: number,
  data: import("../types/networks").NetworkUpdateData
) {
  return apiFetch<import("../types/networks").Network>(`/networks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function listGroupFirewall(networkId: number) {
  return apiFetch<import("../types/networks").GroupFirewallConfig[]>(
    `/networks/${networkId}/group-firewall`
  );
}

export async function updateGroupFirewall(
  networkId: number,
  groupName: string,
  data: { inbound_rules: import("../types/networks").InboundFirewallRule[] }
) {
  const encoded = encodeURIComponent(groupName);
  return apiFetch<import("../types/networks").GroupFirewallConfig>(
    `/networks/${networkId}/group-firewall/${encoded}`,
    { method: "PUT", body: JSON.stringify(data) }
  );
}

export async function deleteGroupFirewall(networkId: number, groupName: string): Promise<void> {
  const encoded = encodeURIComponent(groupName);
  const res = await fetch(`${API_BASE}/networks/${networkId}/group-firewall/${encoded}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (res.status === 401 && !localStorage.getItem(TOKEN_KEY)) {
    const got = await tryDevToken();
    if (got) {
      const retry = await fetch(`${API_BASE}/networks/${networkId}/group-firewall/${encoded}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (!retry.ok) {
        const err = await retry.json().catch(() => ({ detail: retry.statusText }));
        throw new Error((err as { detail?: string }).detail || retry.statusText);
      }
      return;
    }
  }
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
}

export interface CheckIpAvailableResponse {
  available: boolean;
}

export async function checkIpAvailable(
  networkId: number,
  ip: string
): Promise<CheckIpAvailableResponse> {
  const encoded = encodeURIComponent(ip);
  return apiFetch<CheckIpAvailableResponse>(
    `/networks/${networkId}/check-ip?ip=${encoded}`
  );
}

export async function listNodes(networkId?: number) {
  const q = networkId != null ? `?network_id=${networkId}` : "";
  return apiFetch<import("../types/nodes").Node[]>(`/nodes${q}`);
}

export async function getNode(id: number) {
  return apiFetch<import("../types/nodes").Node>(`/nodes/${id}`);
}

export type NodeUpdateData = {
  group?: string | null;
  is_lighthouse?: boolean;
  is_relay?: boolean;
  public_endpoint?: string | null;
  lighthouse_options?: import("../types/nodes").LighthouseOptions | null;
  logging_options?: import("../types/nodes").LoggingOptions | null;
  punchy_options?: import("../types/nodes").PunchyOptions | null;
};

export async function updateNode(id: number, data: NodeUpdateData) {
  return apiFetch<{ ok: boolean }>(`/nodes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteNode(nodeId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/nodes/${nodeId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (res.status === 401 && !localStorage.getItem(TOKEN_KEY)) {
    const got = await tryDevToken();
    if (got) {
      const retry = await fetch(`${API_BASE}/nodes/${nodeId}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (!retry.ok) {
        const err = await retry.json().catch(() => ({ detail: retry.statusText }));
        throw new Error((err as { detail?: string }).detail || retry.statusText);
      }
      return;
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
}

export async function revokeNodeCertificate(nodeId: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/nodes/${nodeId}/revoke-certificate`, {
    method: "POST",
  });
}

export async function reenrollNode(nodeId: number): Promise<{ ok: boolean; node_id: number }> {
  return apiFetch<{ ok: boolean; node_id: number }>(`/nodes/${nodeId}/re-enroll`, {
    method: "POST",
  });
}

/** Fetch a binary endpoint with auth; returns blob. Throws on error. */
async function apiFetchBlob(path: string): Promise<Blob> {
  let res = await fetch(`${API_BASE}${path}`, {
    headers: getAuthHeaders(),
  });
  if (res.status === 401 && !localStorage.getItem(TOKEN_KEY)) {
    const got = await tryDevToken();
    if (got) {
      res = await fetch(`${API_BASE}${path}`, { headers: getAuthHeaders() });
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.blob();
}

export async function getNodeConfigBlob(nodeId: number): Promise<Blob> {
  return apiFetchBlob(`/nodes/${nodeId}/config`);
}

export async function getNodeCertsBlob(nodeId: number): Promise<Blob> {
  return apiFetchBlob(`/nodes/${nodeId}/certs`);
}

export interface CreateEnrollmentCodeResponse {
  code: string;
  expires_at: string;
  node_id: number;
  hostname: string;
}

export async function createEnrollmentCode(
  nodeId: number,
  expiresInHours: number = 24
): Promise<CreateEnrollmentCodeResponse> {
  return apiFetch<CreateEnrollmentCodeResponse>("/device/enrollment-codes", {
    method: "POST",
    body: JSON.stringify({ node_id: nodeId, expires_in_hours: expiresInHours }),
  });
}

export interface SignCertificateRequest {
  network_id: number;
  name: string;
  public_key: string;
  group?: string | null;
  suggested_ip?: string;
  duration_days?: number;
}

export interface SignCertificateResponse {
  ip_address: string;
  certificate: string;
  ca_certificate?: string;
}

export async function signCertificate(body: SignCertificateRequest) {
  return apiFetch<SignCertificateResponse>("/certificates/sign", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface CreateCertificateRequest {
  network_id: number;
  name: string;
  group?: string | null;
  suggested_ip?: string;
  duration_days?: number;
  is_lighthouse?: boolean;
  is_relay?: boolean;
  public_endpoint?: string;
  lighthouse_options?: {
    serve_dns?: boolean;
    dns_host?: string;
    dns_port?: number;
    interval_seconds?: number;
  };
  punchy_options?: import("../types/nodes").PunchyOptions;
}

export interface CreateCertificateResponse {
  node_id: number;
  hostname: string;
  ip_address: string;
  certificate: string;
  private_key: string;
  ca_certificate?: string;
}

export async function createCertificate(body: CreateCertificateRequest) {
  return apiFetch<CreateCertificateResponse>("/certificates/create", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface CertificateListItem {
  id: number;
  node_id: number;
  node_name: string;
  network_id: number;
  network_name: string;
  ip_address: string | null;
  issued_at: string;
  expires_at: string;
  revoked_at: string | null;
}

export async function listCertificates(networkId?: number) {
  const q = networkId != null ? `?network_id=${networkId}` : "";
  return apiFetch<CertificateListItem[]>(`/certificates${q}`);
}
