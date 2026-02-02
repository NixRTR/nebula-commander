import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Table,
  Badge,
  Button,
  Modal,
  Label,
  TextInput,
  Checkbox,
  Select,
  Alert,
} from "flowbite-react";
import { HiCheckCircle, HiXCircle, HiClock, HiDownload, HiPencil, HiPlus, HiTrash, HiClipboard } from "react-icons/hi";
import type { Node, LighthouseOptions } from "../types/nodes";
import type { Network } from "../types/networks";
import {
  listNodes,
  listNetworks,
  updateNode,
  getNodeConfigBlob,
  getNodeCertsBlob,
  createEnrollmentCode,
  createCertificate,
  checkIpAvailable,
  deleteNode,
} from "../api/client";
import type { CreateEnrollmentCodeResponse, CreateCertificateResponse } from "../api/client";

function downloadFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function Nodes() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [filterNetworkId, setFilterNetworkId] = useState<number | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingNode, setEditingNode] = useState<Node | null>(null);
  const [editForm, setEditForm] = useState<{
    is_lighthouse: boolean;
    public_endpoint: string;
    groups: string;
    serve_dns: boolean;
    dns_host: string;
    dns_port: string;
    interval_seconds: string;
  }>({
    is_lighthouse: false,
    public_endpoint: "",
    groups: "",
    serve_dns: false,
    dns_host: "0.0.0.0",
    dns_port: "53",
    interval_seconds: "60",
  });
  const [saving, setSaving] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [enrollmentCodeModal, setEnrollmentCodeModal] = useState<{
    open: boolean;
    data: CreateEnrollmentCodeResponse | null;
    loading: boolean;
  }>({ open: false, data: null, loading: false });

  const [showCreateNodeForm, setShowCreateNodeForm] = useState(false);
  const [createNodeForm, setCreateNodeForm] = useState({
    network_id: 0,
    name: "",
    groups: "",
    suggested_ip: "",
    duration_days: "365",
    is_lighthouse: false,
    public_endpoint: "",
    serve_dns: false,
    dns_host: "0.0.0.0",
    dns_port: "53",
    interval_seconds: "60",
  });
  const [nodeNameError, setNodeNameError] = useState<string | null>(null);
  const [suggestedIpError, setSuggestedIpError] = useState<string | null>(null);
  const [createNodeResult, setCreateNodeResult] = useState<CreateCertificateResponse | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);

  const [deleteModal, setDeleteModal] = useState<{
    open: boolean;
    node: Node | null;
    step: 1 | 2;
    typedHostname: string;
  }>({ open: false, node: null, step: 1, typedHostname: "" });
  const [deleting, setDeleting] = useState(false);

  const loadNetworks = useCallback(() => {
    listNetworks()
      .then((data) => {
        setNetworks(data);
        setCreateNodeForm((f) =>
          f.network_id === 0 && data.length > 0 ? { ...f, network_id: data[0].id } : f
        );
      })
      .catch(() => setNetworks([]));
  }, []);

  const loadNodes = useCallback(() => {
    setLoading(true);
    const nid = filterNetworkId === "" ? undefined : filterNetworkId;
    listNodes(nid)
      .then(setNodes)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filterNetworkId]);

  useEffect(() => {
    loadNetworks();
  }, [loadNetworks]);

  useEffect(() => {
    const id = setTimeout(loadNodes, 0);
    return () => clearTimeout(id);
  }, [loadNodes]);

  const handleCreateNodeNameBlur = useCallback(() => {
    const name = createNodeForm.name.trim();
    const nid = createNodeForm.network_id;
    if (!nid || !name) {
      setNodeNameError(null);
      return;
    }
    listNodes(nid)
      .then((list) => {
        const exists = list.some((n) => n.hostname === name);
        setNodeNameError(exists ? "A node with this name already exists in this network." : null);
      })
      .catch(() => setNodeNameError(null));
  }, [createNodeForm.name, createNodeForm.network_id]);

  const handleSuggestedIpBlur = useCallback(() => {
    const ip = createNodeForm.suggested_ip.trim();
    const nid = createNodeForm.network_id;
    if (!nid || !ip) {
      setSuggestedIpError(null);
      return;
    }
    checkIpAvailable(nid, ip)
      .then((res) => setSuggestedIpError(res.available ? null : "This IP is already reserved in this network."))
      .catch(() => setSuggestedIpError(null));
  }, [createNodeForm.suggested_ip, createNodeForm.network_id]);

  const handleCreateNodeSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setCreateNodeResult(null);
    if (nodeNameError || suggestedIpError) return;
    setCreateSubmitting(true);
    const body = {
      network_id: createNodeForm.network_id,
      name: createNodeForm.name.trim(),
      groups: createNodeForm.groups.trim()
        ? createNodeForm.groups.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined,
      suggested_ip: createNodeForm.suggested_ip.trim() || undefined,
      duration_days: createNodeForm.duration_days ? parseInt(createNodeForm.duration_days, 10) : undefined,
      is_lighthouse: createNodeForm.is_lighthouse,
      public_endpoint: createNodeForm.public_endpoint.trim() || undefined,
      lighthouse_options: createNodeForm.is_lighthouse
        ? {
            serve_dns: createNodeForm.serve_dns,
            dns_host: createNodeForm.dns_host || "0.0.0.0",
            dns_port: parseInt(createNodeForm.dns_port, 10) || 53,
            interval_seconds: parseInt(createNodeForm.interval_seconds, 10) || 60,
          }
        : undefined,
    };
    createCertificate(body)
      .then((res) => {
        setCreateNodeResult(res);
        setCreateNodeForm((f) => ({ ...f, name: "", groups: "", suggested_ip: "" }));
        setNodeNameError(null);
        setSuggestedIpError(null);
        loadNodes();
      })
      .catch((e) => setError(e.message))
      .finally(() => setCreateSubmitting(false));
  };

  const openDeleteModal = (node: Node) => {
    setDeleteModal({ open: true, node, step: 1, typedHostname: "" });
  };

  const closeDeleteModal = () => {
    setDeleteModal({ open: false, node: null, step: 1, typedHostname: "" });
  };

  const handleDeleteConfirm = () => {
    const node = deleteModal.node;
    if (!node) return;
    setDeleting(true);
    deleteNode(node.id)
      .then(() => {
        closeDeleteModal();
        loadNodes();
      })
      .catch((e) => setError(e.message))
      .finally(() => setDeleting(false));
  };

  const openEditModal = (node: Node) => {
    setEditingNode(node);
    const opts = node.lighthouse_options;
    setEditForm({
      is_lighthouse: node.is_lighthouse,
      public_endpoint: node.public_endpoint ?? "",
      groups: (node.groups ?? []).join(", "),
      serve_dns: opts?.serve_dns ?? false,
      dns_host: opts?.dns_host ?? "0.0.0.0",
      dns_port: String(opts?.dns_port ?? 53),
      interval_seconds: String(opts?.interval_seconds ?? 60),
    });
    setEditModalOpen(true);
    setDownloadError(null);
  };

  const closeEditModal = () => {
    setEditModalOpen(false);
    setEditingNode(null);
  };

  const handleSaveEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingNode) return;
    setSaving(true);
    const groups = editForm.groups
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const lighthouse_options: LighthouseOptions = {
      serve_dns: editForm.serve_dns,
      dns_host: editForm.dns_host || "0.0.0.0",
      dns_port: parseInt(editForm.dns_port, 10) || 53,
      interval_seconds: parseInt(editForm.interval_seconds, 10) || 60,
    };
    updateNode(editingNode.id, {
      is_lighthouse: editForm.is_lighthouse,
      public_endpoint: editForm.public_endpoint.trim() || null,
      groups,
      lighthouse_options,
    })
      .then(() => {
        closeEditModal();
        loadNodes();
      })
      .catch((e) => setError(e.message))
      .finally(() => setSaving(false));
  };

  const handleDownloadConfig = async (node: Node) => {
    setDownloadError(null);
    try {
      const blob = await getNodeConfigBlob(node.id);
      downloadBlob(blob, `${node.hostname}.yaml`);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "Download failed");
    }
  };

  const handleDownloadCerts = async (node: Node) => {
    setDownloadError(null);
    try {
      const blob = await getNodeCertsBlob(node.id);
      downloadBlob(blob, `node-${node.hostname}-certs.zip`);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "Download failed");
    }
  };

  const openEnrollmentCodeModal = (node: Node) => {
    setEnrollmentCodeModal({ open: true, data: null, loading: true });
    createEnrollmentCode(node.id, 24)
      .then((data) => setEnrollmentCodeModal((s) => ({ ...s, data, loading: false })))
      .catch((e) => {
        setError(e.message);
        setEnrollmentCodeModal((s) => ({ ...s, loading: false }));
      });
  };

  const closeEnrollmentCodeModal = () => {
    setEnrollmentCodeModal({ open: false, data: null, loading: false });
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return (
          <Badge color="success" icon={HiCheckCircle}>
            Active
          </Badge>
        );
      case "offline":
        return (
          <Badge color="failure" icon={HiXCircle}>
            Offline
          </Badge>
        );
      case "pending":
        return (
          <Badge color="warning" icon={HiClock}>
            Pending
          </Badge>
        );
      default:
        return <Badge color="gray">{status}</Badge>;
    }
  };

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Nodes</h1>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      {downloadError && (
        <Alert color="failure" className="mb-4" onDismiss={() => setDownloadError(null)}>
          {downloadError}
        </Alert>
      )}

      {loading ? (
        <Card>
          <p className="text-gray-600 dark:text-gray-400">Loading nodes...</p>
        </Card>
      ) : (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
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
                {networks.map((net) => (
                  <option key={net.id} value={net.id}>
                    {net.name}
                  </option>
                ))}
              </Select>
              <Button
                color={showCreateNodeForm ? "gray" : "blue"}
                onClick={() => {
                  setShowCreateNodeForm((v) => !v);
                  setCreateNodeResult(null);
                  setNodeNameError(null);
                  setSuggestedIpError(null);
                }}
              >
                <HiPlus className="mr-2 h-5 w-5" />
                {showCreateNodeForm ? "Cancel" : "Create Node"}
              </Button>
            </div>
          </div>

          {showCreateNodeForm && (
            <div className="mb-6 p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
              <h2 className="text-xl font-semibold mb-4">Create Node</h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                This will generate the config and certificate for the node.
              </p>
              {networks.length === 0 ? (
                <p className="text-gray-600 dark:text-gray-400">Create a network first on the Networks page.</p>
              ) : (
                <form onSubmit={handleCreateNodeSubmit} className="space-y-4">
                  <div>
                    <Label htmlFor="create_node_network" value="Network" />
                    <Select
                      id="create_node_network"
                      value={String(createNodeForm.network_id)}
                      onChange={(e) => {
                        const v = parseInt(e.target.value, 10);
                        setCreateNodeForm((f) => ({ ...f, network_id: v }));
                        setNodeNameError(null);
                        setSuggestedIpError(null);
                      }}
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
                    <Label htmlFor="create_node_name" value="Node name (hostname)" />
                    <TextInput
                      id="create_node_name"
                      type="text"
                      value={createNodeForm.name}
                      onChange={(e) => {
                        setCreateNodeForm((f) => ({ ...f, name: e.target.value }));
                        setNodeNameError(null);
                      }}
                      onBlur={handleCreateNodeNameBlur}
                      placeholder="my-laptop"
                      required
                      color={nodeNameError ? "failure" : undefined}
                      helperText={nodeNameError}
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="create_node_groups" value="Groups (comma-separated, optional)" />
                      <TextInput
                        id="create_node_groups"
                        type="text"
                        value={createNodeForm.groups}
                        onChange={(e) => setCreateNodeForm((f) => ({ ...f, groups: e.target.value }))}
                        placeholder="laptops, admin"
                      />
                    </div>
                    <div>
                      <Label htmlFor="create_node_suggested_ip" value="Suggested IP (optional)" />
                      <TextInput
                        id="create_node_suggested_ip"
                        type="text"
                        value={createNodeForm.suggested_ip}
                        onChange={(e) => {
                          setCreateNodeForm((f) => ({ ...f, suggested_ip: e.target.value }));
                          setSuggestedIpError(null);
                        }}
                        onBlur={handleSuggestedIpBlur}
                        placeholder="10.100.0.10"
                        color={suggestedIpError ? "failure" : undefined}
                        helperText={suggestedIpError}
                      />
                    </div>
                  </div>
                  <div>
                    <Label htmlFor="create_node_duration" value="Certificate validity (days)" />
                    <TextInput
                      id="create_node_duration"
                      type="number"
                      value={createNodeForm.duration_days}
                      onChange={(e) => setCreateNodeForm((f) => ({ ...f, duration_days: e.target.value }))}
                      min={1}
                      max={3650}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="create_node_lighthouse"
                      checked={createNodeForm.is_lighthouse}
                      onChange={(e) =>
                        setCreateNodeForm((f) => ({ ...f, is_lighthouse: e.target.checked }))
                      }
                    />
                    <Label htmlFor="create_node_lighthouse">Lighthouse</Label>
                  </div>
                  {createNodeForm.is_lighthouse && (
                    <>
                      <div>
                        <Label htmlFor="create_node_public_endpoint" value="Public endpoint (hostname or IP:port)" />
                        <TextInput
                          id="create_node_public_endpoint"
                          value={createNodeForm.public_endpoint}
                          onChange={(e) =>
                            setCreateNodeForm((f) => ({ ...f, public_endpoint: e.target.value }))
                          }
                          placeholder="lighthouse.example.com:4242"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="create_node_serve_dns"
                          checked={createNodeForm.serve_dns}
                          onChange={(e) =>
                            setCreateNodeForm((f) => ({ ...f, serve_dns: e.target.checked }))
                          }
                        />
                        <Label htmlFor="create_node_serve_dns">Serve DNS</Label>
                      </div>
                      {createNodeForm.serve_dns && (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                          <div>
                            <Label htmlFor="create_node_dns_host" value="DNS host" />
                            <TextInput
                              id="create_node_dns_host"
                              value={createNodeForm.dns_host}
                              onChange={(e) =>
                                setCreateNodeForm((f) => ({ ...f, dns_host: e.target.value }))
                              }
                            />
                          </div>
                          <div>
                            <Label htmlFor="create_node_dns_port" value="DNS port" />
                            <TextInput
                              id="create_node_dns_port"
                              type="number"
                              value={createNodeForm.dns_port}
                              onChange={(e) =>
                                setCreateNodeForm((f) => ({ ...f, dns_port: e.target.value }))
                              }
                            />
                          </div>
                          <div>
                            <Label htmlFor="create_node_interval" value="Report interval (seconds)" />
                            <TextInput
                              id="create_node_interval"
                              type="number"
                              value={createNodeForm.interval_seconds}
                              onChange={(e) =>
                                setCreateNodeForm((f) => ({ ...f, interval_seconds: e.target.value }))
                              }
                            />
                          </div>
                        </div>
                      )}
                    </>
                  )}
                  <Button
                    type="submit"
                    color="blue"
                    isProcessing={createSubmitting}
                    disabled={createSubmitting || !!nodeNameError || !!suggestedIpError}
                  >
                    Create Node
                  </Button>
                </form>
              )}
            </div>
          )}

          {createNodeResult && (
            <div className="mb-6 p-4 border-2 border-green-200 dark:border-green-800 rounded-lg bg-green-50/50 dark:bg-gray-800/50">
              <h2 className="text-xl font-semibold mb-2 text-green-800 dark:text-green-200">Node created</h2>
              <Alert color="success" className="mb-4">
                The private key is stored on the server and is included when you download certs from the node. Copy or download below to place on your node (host.key, host.crt, ca.crt).
              </Alert>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Assigned IP: <strong>{createNodeResult.ip_address}</strong>
              </p>
              <div className="space-y-4">
                <div>
                  <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                    <Label value="Private key (host.key)" />
                    <div className="flex gap-2">
                      <Button size="xs" color="gray" onClick={() => navigator.clipboard.writeText(createNodeResult.private_key)}>
                        <HiClipboard className="w-4 h-4 mr-1" /> Copy
                      </Button>
                      <Button size="xs" color="gray" onClick={() => downloadFile("host.key", createNodeResult.private_key)}>
                        <HiClipboard className="w-4 h-4 mr-1" /> Download
                      </Button>
                    </div>
                  </div>
                  <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                    {createNodeResult.private_key}
                  </pre>
                </div>
                <div>
                  <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                    <Label value="Certificate (host.crt)" />
                    <div className="flex gap-2">
                      <Button size="xs" color="gray" onClick={() => navigator.clipboard.writeText(createNodeResult.certificate)}>
                        <HiClipboard className="w-4 h-4 mr-1" /> Copy
                      </Button>
                      <Button size="xs" color="gray" onClick={() => downloadFile("host.crt", createNodeResult.certificate)}>
                        Download
                      </Button>
                    </div>
                  </div>
                  <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                    {createNodeResult.certificate}
                  </pre>
                </div>
                {createNodeResult.ca_certificate && (
                  <div>
                    <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                      <Label value="CA certificate (ca.crt)" />
                      <div className="flex gap-2">
                        <Button size="xs" color="gray" onClick={() => navigator.clipboard.writeText(createNodeResult.ca_certificate!)}>
                          <HiClipboard className="w-4 h-4 mr-1" /> Copy
                        </Button>
                        <Button size="xs" color="gray" onClick={() => downloadFile("ca.crt", createNodeResult.ca_certificate!)}>
                          Download
                        </Button>
                      </div>
                    </div>
                    <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre-wrap break-all">
                      {createNodeResult.ca_certificate}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}
          <div className="overflow-x-auto">
            <Table>
              <Table.Head>
                <Table.HeadCell>ID</Table.HeadCell>
                <Table.HeadCell>Hostname</Table.HeadCell>
                <Table.HeadCell>Network ID</Table.HeadCell>
                <Table.HeadCell>IP Address</Table.HeadCell>
                <Table.HeadCell>Groups</Table.HeadCell>
                <Table.HeadCell>Lighthouse</Table.HeadCell>
                <Table.HeadCell>Status</Table.HeadCell>
                <Table.HeadCell>Last Seen</Table.HeadCell>
                <Table.HeadCell>Actions</Table.HeadCell>
              </Table.Head>
              <Table.Body className="divide-y">
                {nodes.map((n) => (
                  <Table.Row key={n.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                      {n.id}
                    </Table.Cell>
                    <Table.Cell>{n.hostname}</Table.Cell>
                    <Table.Cell>{n.network_id}</Table.Cell>
                    <Table.Cell>{n.ip_address || "—"}</Table.Cell>
                    <Table.Cell>
                      {n.groups && n.groups.length > 0 ? (
                        <div className="flex gap-1 flex-wrap">
                          {n.groups.map((g, i) => (
                            <Badge key={i} color="info" size="sm">
                              {g}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        "—"
                      )}
                    </Table.Cell>
                    <Table.Cell>
                      {n.is_lighthouse ? (
                        <Badge color="purple" size="sm">
                          Yes
                        </Badge>
                      ) : (
                        <span className="text-gray-500 dark:text-gray-400">No</span>
                      )}
                    </Table.Cell>
                    <Table.Cell>{getStatusBadge(n.status)}</Table.Cell>
                    <Table.Cell>
                      {n.last_seen ? new Date(n.last_seen).toLocaleString() : "—"}
                    </Table.Cell>
                    <Table.Cell>
                      <div className="flex flex-wrap gap-2 items-center">
                        <Button size="xs" color="gray" onClick={() => openEditModal(n)}>
                          <HiPencil className="w-4 h-4 mr-1" />
                          Edit
                        </Button>
                        <Button size="xs" color="gray" onClick={() => handleDownloadConfig(n)}>
                          <HiDownload className="w-4 h-4 mr-1" />
                          Config
                        </Button>
                        {n.ip_address ? (
                          <Button size="xs" color="gray" onClick={() => handleDownloadCerts(n)}>
                            <HiDownload className="w-4 h-4 mr-1" />
                            Certs
                          </Button>
                        ) : (
                          <span className="text-gray-400 text-xs">No cert</span>
                        )}
                        {n.ip_address && (
                          <Button size="xs" color="purple" onClick={() => openEnrollmentCodeModal(n)}>
                            Enroll
                          </Button>
                        )}
                        <Button size="xs" color="failure" onClick={() => openDeleteModal(n)}>
                          <HiTrash className="w-4 h-4 mr-1" />
                          Delete
                        </Button>
                      </div>
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
            {nodes.length === 0 && (
              <div className="p-4 text-center text-gray-500 dark:text-gray-400">
                No nodes yet. Create certificates to add nodes.
              </div>
            )}
          </div>
        </Card>
      )}

      <Modal show={editModalOpen} onClose={closeEditModal} size="md">
        <Modal.Header>Edit node {editingNode?.hostname}</Modal.Header>
        <form onSubmit={handleSaveEdit}>
          <Modal.Body className="space-y-4">
            <div className="flex items-center gap-2">
              <Checkbox
                id="edit_is_lighthouse"
                checked={editForm.is_lighthouse}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, is_lighthouse: e.target.checked }))
                }
              />
              <Label htmlFor="edit_is_lighthouse">This node is a lighthouse</Label>
            </div>
            {editForm.is_lighthouse && (
              <>
                <div>
                  <Label htmlFor="edit_public_endpoint" value="Public endpoint (hostname or IP:port)" />
                  <TextInput
                    id="edit_public_endpoint"
                    value={editForm.public_endpoint}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, public_endpoint: e.target.value }))
                    }
                    placeholder="lighthouse.example.com:4242"
                  />
                </div>
                <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Lighthouse options
                  </p>
                  <div className="flex items-center gap-2 mb-2">
                    <Checkbox
                      id="edit_serve_dns"
                      checked={editForm.serve_dns}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, serve_dns: e.target.checked }))
                      }
                    />
                    <Label htmlFor="edit_serve_dns">Serve DNS</Label>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <Label htmlFor="edit_dns_host" value="DNS host" />
                      <TextInput
                        id="edit_dns_host"
                        value={editForm.dns_host}
                        onChange={(e) =>
                          setEditForm((f) => ({ ...f, dns_host: e.target.value }))
                        }
                      />
                    </div>
                    <div>
                      <Label htmlFor="edit_dns_port" value="DNS port" />
                      <TextInput
                        id="edit_dns_port"
                        type="number"
                        value={editForm.dns_port}
                        onChange={(e) =>
                          setEditForm((f) => ({ ...f, dns_port: e.target.value }))
                        }
                      />
                    </div>
                  </div>
                  <div>
                    <Label htmlFor="edit_interval" value="Report interval (seconds)" />
                    <TextInput
                      id="edit_interval"
                      type="number"
                      value={editForm.interval_seconds}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, interval_seconds: e.target.value }))
                      }
                    />
                  </div>
                </div>
              </>
            )}
            <div>
              <Label htmlFor="edit_groups" value="Groups (comma-separated)" />
              <TextInput
                id="edit_groups"
                value={editForm.groups}
                onChange={(e) => setEditForm((f) => ({ ...f, groups: e.target.value }))}
                placeholder="laptops, admin"
              />
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button type="submit" color="blue" isProcessing={saving} disabled={saving}>
              Save
            </Button>
            <Button color="gray" onClick={closeEditModal}>
              Cancel
            </Button>
          </Modal.Footer>
        </form>
      </Modal>

      <Modal show={deleteModal.open} onClose={closeDeleteModal} size="md">
        <Modal.Header>Delete node</Modal.Header>
        <Modal.Body>
          {deleteModal.step === 1 && deleteModal.node && (
            <div className="space-y-4">
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete the node <strong>{deleteModal.node.hostname}</strong>? This will remove the node, its certificate, enrollment codes, and release its IP. This cannot be undone.
              </p>
            </div>
          )}
          {deleteModal.step === 2 && deleteModal.node && (
            <div className="space-y-4">
              <p className="text-gray-700 dark:text-gray-300">
                To confirm, type the node hostname: <strong>{deleteModal.node.hostname}</strong>
              </p>
              <TextInput
                type="text"
                value={deleteModal.typedHostname}
                onChange={(e) =>
                  setDeleteModal((s) => ({ ...s, typedHostname: e.target.value }))
                }
                placeholder={deleteModal.node.hostname}
              />
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          {deleteModal.step === 1 ? (
            <>
              <Button color="gray" onClick={closeDeleteModal}>
                Cancel
              </Button>
              <Button
                color="failure"
                onClick={() => setDeleteModal((s) => ({ ...s, step: 2 }))}
              >
                Continue
              </Button>
            </>
          ) : (
            <>
              <Button
                color="gray"
                onClick={() => setDeleteModal((s) => ({ ...s, step: 1, typedHostname: "" }))}
              >
                Back
              </Button>
              <Button
                color="failure"
                onClick={handleDeleteConfirm}
                disabled={
                  deleteModal.node?.hostname.trim() !== deleteModal.typedHostname.trim() || deleting
                }
                isProcessing={deleting}
              >
                Delete
              </Button>
            </>
          )}
        </Modal.Footer>
      </Modal>

      <Modal show={enrollmentCodeModal.open} onClose={closeEnrollmentCodeModal} size="md">
        <Modal.Header>Enrollment code (dnclient-style)</Modal.Header>
        <Modal.Body>
          {enrollmentCodeModal.loading && (
            <p className="text-gray-600 dark:text-gray-400">Generating code...</p>
          )}
          {enrollmentCodeModal.data && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Use this code once on the device to enroll. Expires:{" "}
                {new Date(enrollmentCodeModal.data.expires_at).toLocaleString()}.
              </p>
              <div>
                <Label value="Code" />
                <p className="mt-1 p-3 bg-gray-100 dark:bg-gray-800 rounded font-mono text-lg">
                  {enrollmentCodeModal.data.code}
                </p>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                On the device, run (replace SERVER with your Nebula Commander URL):
              </p>
              <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto">
                {"ncclient enroll --server https://YOUR_SERVER --code "}
                {enrollmentCodeModal.data.code}
              </pre>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Then run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient run --server https://YOUR_SERVER</code> to poll for config and certs every minute.
              </p>
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button color="gray" onClick={closeEnrollmentCodeModal}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
