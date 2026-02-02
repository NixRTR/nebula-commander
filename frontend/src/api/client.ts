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

export async function listNodes(networkId?: number) {
  const q = networkId != null ? `?network_id=${networkId}` : "";
  return apiFetch<import("../types/nodes").Node[]>(`/nodes${q}`);
}

export async function getNode(id: number) {
  return apiFetch<import("../types/nodes").Node>(`/nodes/${id}`);
}

export type NodeUpdateData = {
  groups?: string[];
  is_lighthouse?: boolean;
  public_endpoint?: string | null;
  lighthouse_options?: import("../types/nodes").LighthouseOptions | null;
};

export async function updateNode(id: number, data: NodeUpdateData) {
  return apiFetch<{ ok: boolean }>(`/nodes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
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
  groups?: string[];
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
  groups?: string[];
  suggested_ip?: string;
  duration_days?: number;
}

export interface CreateCertificateResponse {
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
