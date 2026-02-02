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
import { HiCheckCircle, HiXCircle, HiClock, HiDownload, HiPencil } from "react-icons/hi";
import type { Node, LighthouseOptions } from "../types/nodes";
import type { Network } from "../types/networks";
import {
  listNodes,
  listNetworks,
  updateNode,
  getNodeConfigBlob,
  getNodeCertsBlob,
  createEnrollmentCode,
} from "../api/client";
import type { CreateEnrollmentCodeResponse } from "../api/client";

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

  const loadNetworks = useCallback(() => {
    listNetworks()
      .then(setNetworks)
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
            </div>
          </div>
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
