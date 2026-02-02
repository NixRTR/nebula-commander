import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Button,
  TextInput,
  Label,
  Textarea,
  Select,
  Table,
  Alert,
} from "flowbite-react";
import { HiShieldCheck, HiClipboard, HiDownload, HiKey } from "react-icons/hi";
import type { Network } from "../types/networks";
import {
  listNetworks,
  createCertificate,
  signCertificate,
  listCertificates,
} from "../api/client";
import type {
  CreateCertificateResponse,
  SignCertificateResponse,
  CertificateListItem,
} from "../api/client";

function downloadFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function Certificates() {
  const [networks, setNetworks] = useState<Network[]>([]);
  const [certList, setCertList] = useState<CertificateListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [listLoading, setListLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [createForm, setCreateForm] = useState({
    network_id: 0,
    name: "",
    groups: "",
    suggested_ip: "",
    duration_days: "365",
  });
  const [signForm, setSignForm] = useState({
    network_id: 0,
    name: "",
    public_key: "",
    groups: "",
    suggested_ip: "",
    duration_days: "365",
  });
  const [createResult, setCreateResult] = useState<CreateCertificateResponse | null>(null);
  const [signResult, setSignResult] = useState<SignCertificateResponse | null>(null);
  const [filterNetworkId, setFilterNetworkId] = useState<number | "">("");

  const loadNetworks = () => {
    setLoading(true);
    listNetworks()
      .then(setNetworks)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  const loadCerts = useCallback(() => {
    setListLoading(true);
    const nid = filterNetworkId === "" ? undefined : filterNetworkId;
    listCertificates(nid)
      .then(setCertList)
      .catch(() => setCertList([]))
      .finally(() => setListLoading(false));
  }, [filterNetworkId]);

  useEffect(() => {
    const id = setTimeout(loadNetworks, 0);
    return () => clearTimeout(id);
  }, []);

  useEffect(() => {
    const id = setTimeout(loadCerts, 0);
    return () => clearTimeout(id);
  }, [loadCerts]);

  useEffect(() => {
    const id = setTimeout(() => {
      if (networks.length > 0) {
        setCreateForm((f) => (f.network_id === 0 ? { ...f, network_id: networks[0].id } : f));
        setSignForm((f) => (f.network_id === 0 ? { ...f, network_id: networks[0].id } : f));
      }
    }, 0);
    return () => clearTimeout(id);
  }, [networks]);

  const onCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setCreateResult(null);
    setSignResult(null);
    setSubmitting(true);
    const body = {
      network_id: createForm.network_id,
      name: createForm.name.trim(),
      groups: createForm.groups.trim()
        ? createForm.groups.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined,
      suggested_ip: createForm.suggested_ip.trim() || undefined,
      duration_days: createForm.duration_days ? parseInt(createForm.duration_days, 10) : undefined,
    };
    createCertificate(body)
      .then((res) => {
        setCreateResult(res);
        setCreateForm((f) => ({ ...f, name: "" }));
        loadCerts();
      })
      .catch((e) => setError(e.message))
      .finally(() => setSubmitting(false));
  };

  const onSignSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setCreateResult(null);
    setSignResult(null);
    setSubmitting(true);
    const body = {
      network_id: signForm.network_id,
      name: signForm.name.trim(),
      public_key: signForm.public_key.trim(),
      groups: signForm.groups.trim()
        ? signForm.groups.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined,
      suggested_ip: signForm.suggested_ip.trim() || undefined,
      duration_days: signForm.duration_days ? parseInt(signForm.duration_days, 10) : undefined,
    };
    signCertificate(body)
      .then((res) => {
        setSignResult(res);
        setSignForm((f) => ({ ...f, name: "", public_key: "" }));
        loadCerts();
      })
      .catch((e) => setError(e.message))
      .finally(() => setSubmitting(false));
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const formatDate = (s: string) => new Date(s).toLocaleString();

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Certificates</h1>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Issued certificates list */}
      <Card className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <HiShieldCheck className="w-6 h-6" />
            Issued certificates
          </h2>
          <div className="flex items-center gap-2">
            <Label htmlFor="filter_network" value="Network" className="sr-only" />
            <Select
              id="filter_network"
              value={filterNetworkId === "" ? "" : String(filterNetworkId)}
              onChange={(e) =>
                setFilterNetworkId(e.target.value === "" ? "" : parseInt(e.target.value, 10))
              }
            >
              <option value="">All networks</option>
              {networks.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </Select>
            <Button color="gray" size="sm" onClick={loadCerts}>
              Refresh
            </Button>
          </div>
        </div>
        {listLoading ? (
          <p className="text-gray-600 dark:text-gray-400">Loading...</p>
        ) : certList.length === 0 ? (
          <p className="text-gray-600 dark:text-gray-400">No certificates issued yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <Table.Head>
                <Table.HeadCell>Node</Table.HeadCell>
                <Table.HeadCell>Network</Table.HeadCell>
                <Table.HeadCell>IP</Table.HeadCell>
                <Table.HeadCell>Issued</Table.HeadCell>
                <Table.HeadCell>Expires</Table.HeadCell>
              </Table.Head>
              <Table.Body>
                {certList.map((c) => (
                  <Table.Row key={c.id}>
                    <Table.Cell className="font-medium">{c.node_name}</Table.Cell>
                    <Table.Cell>{c.network_name}</Table.Cell>
                    <Table.Cell>{c.ip_address ?? "—"}</Table.Cell>
                    <Table.Cell>{formatDate(c.issued_at)}</Table.Cell>
                    <Table.Cell>{formatDate(c.expires_at)}</Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
      </Card>

      {/* Create certificate (no CLI) - primary flow */}
      <Card className="mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2 mb-2">
          <HiKey className="w-6 h-6" />
          Create certificate
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Create a new certificate from the Web UI. The server will generate the keypair, sign it,
          and give you the private key, certificate, and CA. Copy or download these to your node
          (e.g. <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">host.key</code>,{" "}
          <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">host.crt</code>,{" "}
          <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ca.crt</code>). No command
          line required.
        </p>

        {loading ? (
          <p className="text-gray-600 dark:text-gray-400">Loading networks...</p>
        ) : networks.length === 0 ? (
          <p className="text-gray-600 dark:text-gray-400">Create a network first on the Networks page.</p>
        ) : (
          <form onSubmit={onCreateSubmit} className="space-y-4">
            <div>
              <Label htmlFor="create_network_id" value="Network" />
              <Select
                id="create_network_id"
                value={String(createForm.network_id)}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, network_id: parseInt(e.target.value, 10) }))
                }
                required
              >
                <option value="0">Select a network</option>
                {networks.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name} ({n.subnet_cidr})
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="create_name" value="Node name (hostname)" />
              <TextInput
                id="create_name"
                type="text"
                value={createForm.name}
                onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="my-laptop"
                required
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="create_groups" value="Groups (comma-separated, optional)" />
                <TextInput
                  id="create_groups"
                  type="text"
                  value={createForm.groups}
                  onChange={(e) => setCreateForm((f) => ({ ...f, groups: e.target.value }))}
                  placeholder="laptops, admin"
                />
              </div>
              <div>
                <Label htmlFor="create_suggested_ip" value="Suggested IP (optional)" />
                <TextInput
                  id="create_suggested_ip"
                  type="text"
                  value={createForm.suggested_ip}
                  onChange={(e) => setCreateForm((f) => ({ ...f, suggested_ip: e.target.value }))}
                  placeholder="10.100.0.10"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="create_duration_days" value="Certificate validity (days)" />
              <TextInput
                id="create_duration_days"
                type="number"
                value={createForm.duration_days}
                onChange={(e) => setCreateForm((f) => ({ ...f, duration_days: e.target.value }))}
                min={1}
                max={3650}
              />
            </div>
            <Button type="submit" color="blue" isProcessing={submitting} disabled={submitting}>
              Create certificate
            </Button>
          </form>
        )}
      </Card>

      {/* Result: Create (private key + cert + CA) */}
      {createResult && (
        <Card className="mb-6 border-2 border-green-200 dark:border-green-800">
          <h2 className="text-xl font-semibold mb-2 text-green-800 dark:text-green-200">
            Certificate created
          </h2>
          <Alert color="success" className="mb-4">
            The private key is stored on the server and is included in the node&apos;s cert bundle when you download it from the Nodes page. You can still copy or download the key below to place on your node manually (e.g. <code>host.key</code>, <code>host.crt</code>, <code>ca.crt</code>).
          </Alert>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            Assigned IP: <strong>{createResult.ip_address}</strong>
          </p>
          <div className="space-y-4">
            <div>
              <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                <Label value="Private key (host.key)" />
                <div className="flex gap-2">
                  <Button size="xs" color="gray" onClick={() => copyToClipboard(createResult.private_key)}>
                    <HiClipboard className="w-4 h-4 mr-1" /> Copy
                  </Button>
                  <Button
                    size="xs"
                    color="gray"
                    onClick={() =>
                      downloadFile("host.key", createResult.private_key)
                    }
                  >
                    <HiDownload className="w-4 h-4 mr-1" /> Download
                  </Button>
                </div>
              </div>
              <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                {createResult.private_key}
              </pre>
            </div>
            <div>
              <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                <Label value="Signed certificate (host.crt)" />
                <div className="flex gap-2">
                  <Button size="xs" color="gray" onClick={() => copyToClipboard(createResult.certificate)}>
                    <HiClipboard className="w-4 h-4 mr-1" /> Copy
                  </Button>
                  <Button size="xs" color="gray" onClick={() => downloadFile("host.crt", createResult.certificate)}>
                    <HiDownload className="w-4 h-4 mr-1" /> Download
                  </Button>
                </div>
              </div>
              <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                {createResult.certificate}
              </pre>
            </div>
            {createResult.ca_certificate && (
              <div>
                <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                  <Label value="CA certificate (ca.crt)" />
                  <div className="flex gap-2">
                    <Button
                      size="xs"
                      color="gray"
                      onClick={() => copyToClipboard(createResult.ca_certificate!)}
                    >
                      <HiClipboard className="w-4 h-4 mr-1" /> Copy
                    </Button>
                    <Button
                      size="xs"
                      color="gray"
                      onClick={() => downloadFile("ca.crt", createResult.ca_certificate!)}
                    >
                      <HiDownload className="w-4 h-4 mr-1" /> Download
                    </Button>
                  </div>
                </div>
                <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                  {createResult.ca_certificate}
                </pre>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Sign existing public key (advanced) */}
      <Card>
        <h2 className="text-xl font-semibold flex items-center gap-2 mb-2">
          <HiShieldCheck className="w-6 h-6" />
          Sign existing public key (advanced)
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          If you already generated a keypair on your node with{" "}
          <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">
            nebula-cert keygen -out-pub key.pub -out-key key.key
          </code>
          , paste the public key below to get a signed certificate.
        </p>

        {loading ? (
          <p className="text-gray-600 dark:text-gray-400">Loading networks...</p>
        ) : networks.length === 0 ? (
          <p className="text-gray-600 dark:text-gray-400">Create a network first.</p>
        ) : (
          <form onSubmit={onSignSubmit} className="space-y-4">
            <div>
              <Label htmlFor="sign_network_id" value="Network" />
              <Select
                id="sign_network_id"
                value={String(signForm.network_id)}
                onChange={(e) =>
                  setSignForm((f) => ({ ...f, network_id: parseInt(e.target.value, 10) }))
                }
                required
              >
                <option value="0">Select a network</option>
                {networks.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name} ({n.subnet_cidr})
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="sign_name" value="Node name (hostname)" />
              <TextInput
                id="sign_name"
                type="text"
                value={signForm.name}
                onChange={(e) => setSignForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="my-laptop"
                required
              />
            </div>
            <div>
              <Label htmlFor="sign_public_key" value="Public key (PEM from key.pub)" />
              <Textarea
                id="sign_public_key"
                value={signForm.public_key}
                onChange={(e) => setSignForm((f) => ({ ...f, public_key: e.target.value }))}
                placeholder={
                  "-----BEGIN NEBULA ED25519 PUBLIC KEY-----\n...\n-----END NEBULA ED25519 PUBLIC KEY-----"
                }
                rows={6}
                required
                className="font-mono text-sm"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="sign_groups" value="Groups (comma-separated, optional)" />
                <TextInput
                  id="sign_groups"
                  type="text"
                  value={signForm.groups}
                  onChange={(e) => setSignForm((f) => ({ ...f, groups: e.target.value }))}
                  placeholder="laptops, admin"
                />
              </div>
              <div>
                <Label htmlFor="sign_suggested_ip" value="Suggested IP (optional)" />
                <TextInput
                  id="sign_suggested_ip"
                  type="text"
                  value={signForm.suggested_ip}
                  onChange={(e) => setSignForm((f) => ({ ...f, suggested_ip: e.target.value }))}
                  placeholder="10.100.0.10"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="sign_duration_days" value="Certificate validity (days)" />
              <TextInput
                id="sign_duration_days"
                type="number"
                value={signForm.duration_days}
                onChange={(e) => setSignForm((f) => ({ ...f, duration_days: e.target.value }))}
                min={1}
                max={3650}
              />
            </div>
            <Button type="submit" color="gray" isProcessing={submitting} disabled={submitting}>
              Sign certificate
            </Button>
          </form>
        )}

        {signResult && (
          <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold mb-2">Certificate signed</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              Assigned IP: <strong>{signResult.ip_address}</strong>. Save the certificate and CA on
              your node.
            </p>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between items-center mb-1">
                  <Label value="Signed certificate (host.crt)" />
                  <Button size="xs" color="gray" onClick={() => copyToClipboard(signResult.certificate)}>
                    <HiClipboard className="w-4 h-4 mr-1" /> Copy
                  </Button>
                </div>
                <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                  {signResult.certificate}
                </pre>
              </div>
              {signResult.ca_certificate && (
                <div>
                  <div className="flex justify-between items-center mb-1">
                    <Label value="CA certificate (ca.crt)" />
                    <Button
                      size="xs"
                      color="gray"
                      onClick={() => copyToClipboard(signResult.ca_certificate!)}
                    >
                      <HiClipboard className="w-4 h-4 mr-1" /> Copy
                    </Button>
                  </div>
                  <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                    {signResult.ca_certificate}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
