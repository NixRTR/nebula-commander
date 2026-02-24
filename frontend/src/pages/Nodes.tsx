import { useCallback, useEffect, useState, Fragment } from "react";
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
import { HiCheckCircle, HiXCircle, HiClock, HiDownload, HiPencil, HiPlus, HiTrash, HiClipboard, HiChevronDown, HiChevronRight } from "react-icons/hi";
import type { Node, LighthouseOptions, LoggingOptions, PunchyOptions } from "../types/nodes";
import type { Network } from "../types/networks";
import {
  listNodes,
  listNetworks,
  getNode,
  updateNode,
  getNodeConfigBlob,
  createEnrollmentCode,
  listGroupFirewall,
  createCertificate,
  checkIpAvailable,
  deleteNode,
  revokeNodeCertificate,
  reenrollNode,
} from "../api/client";
import type { CreateEnrollmentCodeResponse } from "../api/client";

type EnrollmentState =
  | { type: "enroll" }
  | { type: "re-enroll" }
  | { type: "active" }
  | { type: "idle"; severity: "success" | "warning" | "failure" };

function getEnrollmentState(node: Node): EnrollmentState {
  if (!node.first_polled_at) {
    return { type: "enroll" };
  }
  if (node.last_seen) {
    const lastSeenDate = new Date(node.last_seen);
    const now = new Date();
    const minutesSinceLastSeen = (now.getTime() - lastSeenDate.getTime()) / (1000 * 60);
    if (minutesSinceLastSeen > 24 * 60) {
      return { type: "re-enroll" };
    }
    if (minutesSinceLastSeen <= 30) {
      return { type: "active" };
    }
    if (minutesSinceLastSeen <= 60) {
      return { type: "idle", severity: "success" };
    }
    if (minutesSinceLastSeen <= 180) {
      return { type: "idle", severity: "warning" };
    }
    return { type: "idle", severity: "failure" };
  }
  return { type: "re-enroll" };
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
  const [deviceDetailsModal, setDeviceDetailsModal] = useState<{
    node: Node | null;
    isEditing: boolean;
    showSaved: boolean;
    savedFading: boolean;
  }>({ node: null, isEditing: false, showSaved: false, savedFading: false });
  const [deviceDetailsForm, setDeviceDetailsForm] = useState<{
    group: string;
    is_lighthouse: boolean;
    is_relay: boolean;
    public_endpoint: string;
    serve_dns: boolean;
    dns_host: string;
    dns_port: string;
    interval_seconds: string;
    log_level: string;
    log_format: string;
    log_disable_timestamp: boolean;
    log_timestamp_format: string;
    punchy_respond: boolean;
    punchy_delay: string;
    punchy_respond_delay: string;
  }>({
    group: "",
    is_lighthouse: false,
    is_relay: false,
    public_endpoint: "",
    serve_dns: false,
    dns_host: "0.0.0.0",
    dns_port: "53",
    interval_seconds: "60",
    log_level: "info",
    log_format: "text",
    log_disable_timestamp: false,
    log_timestamp_format: "",
    punchy_respond: true,
    punchy_delay: "",
    punchy_respond_delay: "",
  });
  const [saving, setSaving] = useState(false);
  const [reEnrollModal, setReEnrollModal] = useState<{
    open: boolean;
    node: Node | null;
    processing: boolean;
  }>({ open: false, node: null, processing: false });
  const [revokeModal, setRevokeModal] = useState<{
    open: boolean;
    node: Node | null;
    processing: boolean;
  }>({ open: false, node: null, processing: false });
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [enrollmentCodeModal, setEnrollmentCodeModal] = useState<{
    open: boolean;
    data: CreateEnrollmentCodeResponse | null;
    nodeId: number | null;
    loading: boolean;
    enrollmentSuccess: boolean;
  }>({ open: false, data: null, nodeId: null, loading: false, enrollmentSuccess: false });

  const [showCreateNodeForm, setShowCreateNodeForm] = useState(false);
  const [createNodeForm, setCreateNodeForm] = useState({
    network_id: 0,
    name: "",
    group: "",
    suggested_ip: "",
    duration_days: "365",
    is_lighthouse: false,
    is_relay: false,
    public_endpoint: "",
    serve_dns: false,
    dns_host: "0.0.0.0",
    dns_port: "53",
    interval_seconds: "60",
  });
  const [nodeNameError, setNodeNameError] = useState<string | null>(null);
  const [suggestedIpError, setSuggestedIpError] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createGroupOptions, setCreateGroupOptions] = useState<string[]>([]);
  const [editGroupOptions, setEditGroupOptions] = useState<string[]>([]);

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

  useEffect(() => {
    const nid = createNodeForm.network_id;
    if (!nid) {
      queueMicrotask(() => setCreateGroupOptions([]));
      return;
    }
    let cancelled = false;
    listGroupFirewall(nid)
      .then((list) => {
        if (cancelled) return;
        const names = list.map((g) => g.group_name);
        setCreateGroupOptions(names);
        setCreateNodeForm((prev) =>
          prev.network_id === nid && prev.group && !names.includes(prev.group) ? { ...prev, group: "" } : prev
        );
      })
      .catch(() => {
        if (!cancelled) setCreateGroupOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [createNodeForm.network_id]);

  useEffect(() => {
    const networkId = deviceDetailsModal.node?.network_id;
    if (!networkId) {
      queueMicrotask(() => setEditGroupOptions([]));
      return;
    }
    let cancelled = false;
    listGroupFirewall(networkId)
      .then((list) => {
        if (!cancelled) setEditGroupOptions(list.map((g) => g.group_name));
      })
      .catch(() => {
        if (!cancelled) setEditGroupOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [deviceDetailsModal.node?.network_id]);

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
    if (nodeNameError || suggestedIpError) return;
    setCreateSubmitting(true);
    const firstInNetwork = isFirstNodeInNetwork(createNodeForm.network_id);
    const body = {
      network_id: createNodeForm.network_id,
      name: createNodeForm.name.trim(),
      group: createNodeForm.group.trim() || undefined,
      suggested_ip: createNodeForm.suggested_ip.trim() || undefined,
      duration_days: createNodeForm.duration_days ? parseInt(createNodeForm.duration_days, 10) : undefined,
      is_lighthouse: firstInNetwork ? true : createNodeForm.is_lighthouse,
      is_relay: createNodeForm.is_relay,
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
        setCreateNodeForm((f) => ({ ...f, name: "", group: "", suggested_ip: "" }));
        setNodeNameError(null);
        setSuggestedIpError(null);
        loadNodes();
        setShowCreateNodeForm(false);
        return createEnrollmentCode(res.node_id, 24);
      })
      .then((enrollData) => {
        setEnrollmentCodeModal({
          open: true,
          data: enrollData,
          nodeId: enrollData.node_id,
          loading: false,
          enrollmentSuccess: false,
        });
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

  const getNetworkName = (networkId: number): string => {
    const network = networks.find((n) => n.id === networkId);
    return network?.name ?? `Network ${networkId}`;
  };

  const isFirstNodeInNetwork = (networkId: number): boolean =>
    nodes.filter((n) => n.network_id === networkId).length === 0;

  const isOnlyLighthouseInNetwork = (node: Node): boolean =>
    !!node?.is_lighthouse &&
    nodes.filter((n) => n.network_id === node.network_id && n.is_lighthouse).length === 1;

  const toggleDeviceDetails = (node: Node) => {
    if (deviceDetailsModal.node?.id === node.id) {
      setDeviceDetailsModal({ node: null, isEditing: false, showSaved: false, savedFading: false });
      return;
    }
    setDeviceDetailsModal({ node, isEditing: false, showSaved: false, savedFading: false });
    const opts = node.lighthouse_options;
    const logOpts = node.logging_options;
    setDeviceDetailsForm({
      is_lighthouse: node.is_lighthouse,
      is_relay: node.is_relay,
      public_endpoint: node.public_endpoint ?? "",
      group: (node.groups && node.groups[0]) ?? "",
      serve_dns: opts?.serve_dns ?? false,
      dns_host: opts?.dns_host ?? "0.0.0.0",
      dns_port: String(opts?.dns_port ?? 53),
      interval_seconds: String(opts?.interval_seconds ?? 60),
      log_level: logOpts?.level ?? "info",
      log_format: logOpts?.format ?? "text",
      log_disable_timestamp: logOpts?.disable_timestamp ?? false,
      log_timestamp_format: logOpts?.timestamp_format ?? "",
      punchy_respond: node.punchy_options?.respond ?? true,
      punchy_delay: node.punchy_options?.delay ?? "",
      punchy_respond_delay: node.punchy_options?.respond_delay ?? "",
    });
    setDownloadError(null);
  };

  const closeDeviceDetailsModal = () => {
    setDeviceDetailsModal({ node: null, isEditing: false, showSaved: false, savedFading: false });
  };

  const hasDeviceDetailsFormChanges = (): boolean => {
    const node = deviceDetailsModal.node;
    if (!node) return false;
    const nodeGroup = (node.groups && node.groups[0]) ?? "";
    const formGroup = deviceDetailsForm.group ?? "";
    const groupEqual = (formGroup.trim() || "") === (nodeGroup.trim() || "");
    const opts = node.lighthouse_options;
    const logOpts = node.logging_options;
    return (
      !groupEqual ||
      deviceDetailsForm.is_lighthouse !== node.is_lighthouse ||
      deviceDetailsForm.is_relay !== node.is_relay ||
      (deviceDetailsForm.public_endpoint ?? "") !== (node.public_endpoint ?? "") ||
      deviceDetailsForm.serve_dns !== (opts?.serve_dns ?? false) ||
      (deviceDetailsForm.dns_host ?? "0.0.0.0") !== (opts?.dns_host ?? "0.0.0.0") ||
      String(deviceDetailsForm.dns_port ?? 53) !== String(opts?.dns_port ?? 53) ||
      String(deviceDetailsForm.interval_seconds ?? 60) !== String(opts?.interval_seconds ?? 60) ||
      (deviceDetailsForm.log_level ?? "info") !== (logOpts?.level ?? "info") ||
      (deviceDetailsForm.log_format ?? "text") !== (logOpts?.format ?? "text") ||
      deviceDetailsForm.log_disable_timestamp !== (logOpts?.disable_timestamp ?? false) ||
      (deviceDetailsForm.log_timestamp_format ?? "") !== (logOpts?.timestamp_format ?? "") ||
      deviceDetailsForm.punchy_respond !== (node.punchy_options?.respond ?? true) ||
      (deviceDetailsForm.punchy_delay ?? "") !== (node.punchy_options?.delay ?? "") ||
      (deviceDetailsForm.punchy_respond_delay ?? "") !== (node.punchy_options?.respond_delay ?? "")
    );
  };

  const handleSaveDeviceDetails = (e: React.FormEvent) => {
    e.preventDefault();
    const node = deviceDetailsModal.node;
    if (!node) return;
    if (
      deviceDetailsForm.is_lighthouse === false &&
      node.is_lighthouse === true &&
      isOnlyLighthouseInNetwork(node)
    ) {
      setError("Cannot remove the only lighthouse. Designate another node as lighthouse first.");
      return;
    }
    setSaving(true);
    const group = deviceDetailsForm.group?.trim() || null;
    const lighthouse_options: LighthouseOptions = {
      serve_dns: deviceDetailsForm.serve_dns,
      dns_host: deviceDetailsForm.dns_host || "0.0.0.0",
      dns_port: parseInt(deviceDetailsForm.dns_port, 10) || 53,
      interval_seconds: parseInt(deviceDetailsForm.interval_seconds, 10) || 60,
    };
    const logging_options: LoggingOptions = {
      level: (deviceDetailsForm.log_level || "info") as LoggingOptions["level"],
      format: (deviceDetailsForm.log_format || "text") as LoggingOptions["format"],
      disable_timestamp: deviceDetailsForm.log_disable_timestamp,
      timestamp_format: deviceDetailsForm.log_timestamp_format.trim() || undefined,
    };
    const punchy_options: PunchyOptions = {
      respond: deviceDetailsForm.punchy_respond,
      delay: deviceDetailsForm.punchy_delay.trim() || undefined,
      respond_delay: deviceDetailsForm.punchy_respond_delay.trim() || undefined,
    };
    updateNode(node.id, {
      is_lighthouse: deviceDetailsForm.is_lighthouse,
      is_relay: deviceDetailsForm.is_relay,
      public_endpoint: deviceDetailsForm.public_endpoint.trim() || null,
      group,
      lighthouse_options,
      logging_options,
      punchy_options,
    })
      .then(() => {
        setDeviceDetailsModal((s) => ({ ...s, showSaved: true, savedFading: false }));
        setTimeout(() => setDeviceDetailsModal((s) => ({ ...s, savedFading: true })), 500);
        setTimeout(() => {
          getNode(node.id).then((updated) => {
            setDeviceDetailsModal((s) => ({ ...s, node: updated, isEditing: false, showSaved: false, savedFading: false }));
            setDeviceDetailsForm({
              group: (updated.groups && updated.groups[0]) ?? "",
              is_lighthouse: updated.is_lighthouse,
              is_relay: updated.is_relay,
              public_endpoint: updated.public_endpoint ?? "",
              serve_dns: updated.lighthouse_options?.serve_dns ?? false,
              dns_host: updated.lighthouse_options?.dns_host ?? "0.0.0.0",
              dns_port: String(updated.lighthouse_options?.dns_port ?? 53),
              interval_seconds: String(updated.lighthouse_options?.interval_seconds ?? 60),
              log_level: updated.logging_options?.level ?? "info",
              log_format: updated.logging_options?.format ?? "text",
              log_disable_timestamp: updated.logging_options?.disable_timestamp ?? false,
              log_timestamp_format: updated.logging_options?.timestamp_format ?? "",
              punchy_respond: updated.punchy_options?.respond ?? true,
              punchy_delay: updated.punchy_options?.delay ?? "",
              punchy_respond_delay: updated.punchy_options?.respond_delay ?? "",
            });
          });
          loadNodes();
        }, 2000);
      })
      .catch((e) => setError(e.message))
      .finally(() => setSaving(false));
  };

  const openReEnrollModal = (node: Node) => {
    setReEnrollModal({ open: true, node, processing: false });
  };

  const closeReEnrollModal = () => {
    setReEnrollModal({ open: false, node: null, processing: false });
  };

  const handleReEnrollConfirm = () => {
    const node = reEnrollModal.node;
    if (!node) return;
    setReEnrollModal((s) => ({ ...s, processing: true }));
    reenrollNode(node.id)
      .then(() => {
        closeReEnrollModal();
        closeDeviceDetailsModal();
        loadNodes();
        return createEnrollmentCode(node.id, 24);
      })
      .then((enrollData) => {
        setEnrollmentCodeModal({
          open: true,
          data: enrollData,
          nodeId: enrollData.node_id,
          loading: false,
          enrollmentSuccess: false,
        });
      })
      .catch((e) => setError(e.message))
      .finally(() => setReEnrollModal((s) => ({ ...s, processing: false })));
  };

  const openRevokeModal = (node: Node) => {
    setRevokeModal({ open: true, node, processing: false });
  };

  const closeRevokeModal = () => {
    setRevokeModal({ open: false, node: null, processing: false });
  };

  const handleRevokeConfirm = () => {
    const node = revokeModal.node;
    if (!node) return;
    setRevokeModal((s) => ({ ...s, processing: true }));
    revokeNodeCertificate(node.id)
      .then(() => {
        closeRevokeModal();
        closeDeviceDetailsModal();
        loadNodes();
      })
      .catch((e) => setError(e.message))
      .finally(() => setRevokeModal((s) => ({ ...s, processing: false })));
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

  const openEnrollmentCodeModal = (node: Node) => {
    setEnrollmentCodeModal({
      open: true,
      data: null,
      nodeId: node.id,
      loading: true,
      enrollmentSuccess: false,
    });
    createEnrollmentCode(node.id, 24)
      .then((data) =>
        setEnrollmentCodeModal((s) => ({ ...s, data, loading: false }))
      )
      .catch((e) => {
        setError(e.message);
        setEnrollmentCodeModal((s) => ({ ...s, loading: false, nodeId: null }));
      });
  };

  const closeEnrollmentCodeModal = () => {
    setEnrollmentCodeModal({
      open: false,
      data: null,
      nodeId: null,
      loading: false,
      enrollmentSuccess: false,
    });
  };

  const handleEnrollmentContinue = () => {
    closeEnrollmentCodeModal();
    loadNodes();
  };

  // Poll for enrollment success (first_polled_at) while enrollment section is visible
  useEffect(() => {
    if (
      !enrollmentCodeModal.open ||
      !enrollmentCodeModal.nodeId ||
      enrollmentCodeModal.enrollmentSuccess ||
      enrollmentCodeModal.loading
    ) {
      return;
    }
    const interval = setInterval(() => {
      getNode(enrollmentCodeModal.nodeId!)
        .then((node) => {
          if (node.first_polled_at) {
            setEnrollmentCodeModal((s) => ({ ...s, enrollmentSuccess: true }));
          }
        })
        .catch(() => {});
    }, 2500);
    return () => clearInterval(interval);
  }, [
    enrollmentCodeModal.open,
    enrollmentCodeModal.nodeId,
    enrollmentCodeModal.enrollmentSuccess,
    enrollmentCodeModal.loading,
  ]);

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
                color={showCreateNodeForm ? "gray" : "purple"}
                onClick={() => {
                  setShowCreateNodeForm((v) => !v);
                  setNodeNameError(null);
                  setSuggestedIpError(null);
                }}
                data-onboarding-target="nodes-create-button"
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
                        setCreateNodeForm((f) => ({
                          ...f,
                          network_id: v,
                          is_lighthouse: nodes.filter((n) => n.network_id === v).length === 0 ? true : f.is_lighthouse,
                        }));
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
                      <Label htmlFor="create_node_group" value="Group (one role, e.g. servers)" />
                      {createGroupOptions.length === 0 ? (
                        <>
                          <Select
                            id="create_node_group"
                            value=""
                            disabled
                            className="w-full"
                          >
                            <option value="">No groups configured</option>
                          </Select>
                          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                            In order to use groups, please add one first.
                          </p>
                        </>
                      ) : (
                        <Select
                          id="create_node_group"
                          value={createNodeForm.group}
                          onChange={(e) => setCreateNodeForm((f) => ({ ...f, group: e.target.value }))}
                          className="w-full"
                        >
                          <option value="">No group</option>
                          {createGroupOptions.map((g) => (
                            <option key={g} value={g}>
                              {g}
                            </option>
                          ))}
                        </Select>
                      )}
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
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="create_node_lighthouse"
                        checked={createNodeForm.is_lighthouse}
                        onChange={(e) =>
                          setCreateNodeForm((f) => ({ ...f, is_lighthouse: e.target.checked }))
                        }
                        disabled={isFirstNodeInNetwork(createNodeForm.network_id)}
                      />
                      <Label htmlFor="create_node_lighthouse">Lighthouse</Label>
                      {isFirstNodeInNetwork(createNodeForm.network_id) && (
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          The first node in this network must be a lighthouse.
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="create_node_relay"
                        checked={createNodeForm.is_relay}
                        onChange={(e) =>
                          setCreateNodeForm((f) => ({ ...f, is_relay: e.target.checked }))
                        }
                      />
                      <Label htmlFor="create_node_relay">Relay</Label>
                    </div>
                  </div>
                  {(createNodeForm.is_lighthouse || createNodeForm.is_relay) && (
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
                      {createNodeForm.is_lighthouse && (
                        <>
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
                    </>
                  )}
                  <Button
                    type="submit"
                    color="purple"
                    isProcessing={createSubmitting}
                    disabled={createSubmitting || !!nodeNameError || !!suggestedIpError}
                  >
                    Create Node
                  </Button>
                </form>
              )}
            </div>
          )}

          {enrollmentCodeModal.open && (
            <Card className="mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Enrollment code for {enrollmentCodeModal.nodeId != null ? (nodes.find((n) => n.id === enrollmentCodeModal.nodeId)?.hostname ?? `Node ${enrollmentCodeModal.nodeId}`) : "new node"}
              </h3>
              <div className="pt-2">
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
                      <div className="flex flex-wrap gap-2 justify-between items-center mb-1">
                        <Label value="Code" />
                        <Button
                          size="xs"
                          color="gray"
                          onClick={() =>
                            enrollmentCodeModal.data &&
                            navigator.clipboard.writeText(enrollmentCodeModal.data.code)
                          }
                        >
                          <HiClipboard className="w-4 h-4 mr-1" /> Copy
                        </Button>
                      </div>
                      <p className="mt-1 p-3 bg-gray-100 dark:bg-gray-800 rounded font-mono text-lg">
                        {enrollmentCodeModal.data.code}
                      </p>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      On the device, run (replace with your Nebula Commander URL if needed):
                    </p>
                    <div className="flex flex-wrap gap-2 justify-between items-start">
                      <pre className="flex-1 min-w-0 p-3 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto whitespace-pre">
                        {`ncclient --server ${typeof window !== "undefined" && window.location?.origin ? window.location.origin : "http://your-server"} enroll --code ${enrollmentCodeModal.data.code}`}
                      </pre>
                      <Button
                        size="xs"
                        color="gray"
                        className="shrink-0"
                        onClick={() => {
                          const server =
                            typeof window !== "undefined" && window.location?.origin
                              ? window.location.origin
                              : "http://your-server";
                          const cmd = `ncclient --server ${server} enroll --code ${enrollmentCodeModal.data!.code}`;
                          navigator.clipboard.writeText(cmd);
                        }}
                      >
                        <HiClipboard className="w-4 h-4 mr-1" /> Copy
                      </Button>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      Then run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient --server &lt;URL&gt; run</code> to poll for config and certs every minute.
                    </p>
                    <div className="flex items-center gap-2 pt-2">
                      {enrollmentCodeModal.enrollmentSuccess ? (
                        <>
                          <span
                            className="flex h-3 w-3 rounded-full bg-green-500"
                            title="Enrollment successful"
                          />
                          <span className="text-green-600 dark:text-green-400 font-medium">
                            Enrollment Successful!
                          </span>
                        </>
                      ) : (
                        <>
                          <span
                            className="flex h-3 w-3 rounded-full bg-red-500 animate-pulse"
                            title="Waiting for enrollment"
                          />
                          <span className="text-red-600 dark:text-red-400">Waiting for enrollment</span>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2 pt-4 border-t border-gray-200 dark:border-gray-700 mt-4">
                <Button color="gray" onClick={closeEnrollmentCodeModal}>
                  {enrollmentCodeModal.enrollmentSuccess ? "Close" : "Cancel"}
                </Button>
                {enrollmentCodeModal.enrollmentSuccess && (
                  <Button color="success" onClick={handleEnrollmentContinue}>
                    Continue
                  </Button>
                )}
              </div>
            </Card>
          )}

          <div className="overflow-x-auto">
            <Table>
              <Table.Head>
                <Table.HeadCell>Hostname</Table.HeadCell>
                <Table.HeadCell>Network</Table.HeadCell>
                <Table.HeadCell>IP Address</Table.HeadCell>
                <Table.HeadCell>Type</Table.HeadCell>
                <Table.HeadCell>Status</Table.HeadCell>
                <Table.HeadCell>Details</Table.HeadCell>
                <Table.HeadCell>Enrollment</Table.HeadCell>
                <Table.HeadCell>Actions</Table.HeadCell>
              </Table.Head>
              <Table.Body className="divide-y">
                {nodes.map((n) => {
                  const enrollState = getEnrollmentState(n);
                  return (
                    <Fragment key={n.id}>
                    <Table.Row className="bg-white dark:border-gray-700 dark:bg-gray-800">
                      <Table.Cell>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => toggleDeviceDetails(n)}
                            className="p-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                            aria-label={deviceDetailsModal.node?.id === n.id ? "Collapse" : "Expand"}
                          >
                            {deviceDetailsModal.node?.id === n.id ? (
                              <HiChevronDown className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                            ) : (
                              <HiChevronRight className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleDeviceDetails(n)}
                            className="text-purple-600 hover:text-purple-800 dark:text-purple-400 dark:hover:text-purple-300 cursor-pointer underline font-medium text-left"
                          >
                            {n.hostname}
                          </button>
                        </div>
                      </Table.Cell>
                      <Table.Cell>{getNetworkName(n.network_id)}</Table.Cell>
                      <Table.Cell>{n.ip_address || "—"}</Table.Cell>
                      <Table.Cell>
                        <div className="flex flex-wrap gap-1">
                          {n.is_lighthouse && (
                            <Badge color="purple" size="sm">
                              Lighthouse
                            </Badge>
                          )}
                          {n.is_relay && (
                            <Badge color="indigo" size="sm">
                              Relay
                            </Badge>
                          )}
                          {!n.is_lighthouse && !n.is_relay && (
                            <span className="text-gray-600 dark:text-gray-400">Node</span>
                          )}
                        </div>
                      </Table.Cell>
                      <Table.Cell>{getStatusBadge(n.status)}</Table.Cell>
                      <Table.Cell>
                        <Button size="xs" color="gray" onClick={() => toggleDeviceDetails(n)}>
                          Details
                        </Button>
                      </Table.Cell>
                      <Table.Cell>
                        {enrollState.type === "enroll" && (
                          <Button size="xs" color="purple" onClick={() => openEnrollmentCodeModal(n)}>
                            Enroll
                          </Button>
                        )}
                        {enrollState.type === "re-enroll" && (
                          <Button size="xs" color="warning" onClick={() => openEnrollmentCodeModal(n)}>
                            Re-Enroll
                          </Button>
                        )}
                        {enrollState.type === "active" && (
                          <Badge color="success">Active</Badge>
                        )}
                        {enrollState.type === "idle" && (
                          <Badge
                            color={
                              enrollState.severity === "success"
                                ? "success"
                                : enrollState.severity === "warning"
                                  ? "warning"
                                  : "failure"
                            }
                          >
                            Idle
                          </Badge>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        <div className="flex flex-wrap gap-2 items-center">
                          <Button size="xs" color="gray" onClick={() => handleDownloadConfig(n)}>
                            <HiDownload className="w-4 h-4 mr-1" />
                            Config
                          </Button>
                          <Button size="xs" color="failure" onClick={() => openDeleteModal(n)}>
                            <HiTrash className="w-4 h-4 mr-1" />
                            Delete
                          </Button>
                        </div>
                      </Table.Cell>
                    </Table.Row>
                    {deviceDetailsModal.node?.id === n.id && (
                      <Table.Row key={`${n.id}-details`} className="bg-gray-50 dark:bg-gray-800/80">
                        <Table.Cell colSpan={8} className="p-0 align-top">
                          <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                            <form onSubmit={handleSaveDeviceDetails} className="space-y-6">
                              {deviceDetailsModal.node && (
                                <>
                                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                                    <div className="min-w-0">
                                      <Label value="ID" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={String(deviceDetailsModal.node.id)}>{deviceDetailsModal.node.id}</p>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="Hostname" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={deviceDetailsModal.node.hostname}>{deviceDetailsModal.node.hostname}</p>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="Network" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={getNetworkName(deviceDetailsModal.node.network_id)}>
                                        {getNetworkName(deviceDetailsModal.node.network_id)}
                                      </p>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="IP Address" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={deviceDetailsModal.node.ip_address || "—"}>
                                        {deviceDetailsModal.node.ip_address || "—"}
                                      </p>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="Status" className="text-gray-500 dark:text-gray-400" />
                                      <div className="mt-1">{getStatusBadge(deviceDetailsModal.node.status)}</div>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="Created At" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={deviceDetailsModal.node.created_at ? new Date(deviceDetailsModal.node.created_at).toLocaleString() : "—"}>
                                        {deviceDetailsModal.node.created_at
                                          ? new Date(deviceDetailsModal.node.created_at).toLocaleString()
                                          : "—"}
                                      </p>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="Last Seen" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={deviceDetailsModal.node.last_seen ? new Date(deviceDetailsModal.node.last_seen).toLocaleString() : "—"}>
                                        {deviceDetailsModal.node.last_seen
                                          ? new Date(deviceDetailsModal.node.last_seen).toLocaleString()
                                          : "—"}
                                      </p>
                                    </div>
                                    <div className="min-w-0">
                                      <Label value="First Polled At" className="text-gray-500 dark:text-gray-400" />
                                      <p className="text-gray-900 dark:text-white truncate" title={deviceDetailsModal.node.first_polled_at ? new Date(deviceDetailsModal.node.first_polled_at).toLocaleString() : "—"}>
                                        {deviceDetailsModal.node.first_polled_at
                                          ? new Date(deviceDetailsModal.node.first_polled_at).toLocaleString()
                                          : "—"}
                                      </p>
                                    </div>
                                  </div>

                                  <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-4">
                                    <div className="min-w-0">
                                      <Label htmlFor="dd_group" value="Group (one role)" className="text-gray-500 dark:text-gray-400" />
                                      {editGroupOptions.length === 0 ? (
                                        <>
                                          <Select
                                            id="dd_group"
                                            value=""
                                            disabled
                                            className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 cursor-default" : ""}`}
                                          >
                                            <option value="">No groups configured</option>
                                          </Select>
                                          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                                            In order to use groups, please add one first.
                                          </p>
                                        </>
                                      ) : (
                                        <Select
                                          id="dd_group"
                                          value={deviceDetailsForm.group}
                                          onChange={(e) => setDeviceDetailsForm((f) => ({ ...f, group: e.target.value }))}
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 cursor-default" : ""}`}
                                        >
                                          <option value="">No group</option>
                                          {[
                                            ...(deviceDetailsForm.group && !editGroupOptions.includes(deviceDetailsForm.group)
                                              ? [deviceDetailsForm.group]
                                              : []),
                                            ...editGroupOptions,
                                          ].map((g) => (
                                            <option key={g} value={g}>
                                              {g}
                                            </option>
                                          ))}
                                        </Select>
                                      )}
                                    </div>
                                    <div className="flex flex-wrap items-center gap-4">
                                      <div className="flex items-center gap-2">
                                        <Checkbox
                                          id="dd_is_lighthouse"
                                          checked={deviceDetailsForm.is_lighthouse}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, is_lighthouse: e.target.checked }))
                                          }
                                          disabled={!deviceDetailsModal.isEditing}
                                        />
                                        <Label htmlFor="dd_is_lighthouse">Lighthouse</Label>
                                      </div>
                                      <div className="flex items-center gap-2">
                                        <Checkbox
                                          id="dd_is_relay"
                                          checked={deviceDetailsForm.is_relay}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, is_relay: e.target.checked }))
                                          }
                                          disabled={!deviceDetailsModal.isEditing}
                                        />
                                        <Label htmlFor="dd_is_relay">Relay</Label>
                                      </div>
                                    </div>
                                    {deviceDetailsModal.isEditing &&
                                      deviceDetailsModal.node &&
                                      isOnlyLighthouseInNetwork(deviceDetailsModal.node) && (
                                        <p className="text-sm text-amber-600 dark:text-amber-400">
                                          This is the only lighthouse in the network; it cannot be unchecked until another node is set as lighthouse.
                                        </p>
                                      )}
                                  </div>

                                  {(deviceDetailsForm.is_lighthouse || deviceDetailsForm.is_relay) && (
                                    <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-4">
                                      <div className="min-w-0">
                                        <Label htmlFor="dd_public_endpoint" value="Public endpoint (hostname or IP:port)" className="text-gray-500 dark:text-gray-400" />
                                        <TextInput
                                          id="dd_public_endpoint"
                                          value={deviceDetailsForm.public_endpoint}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, public_endpoint: e.target.value }))
                                          }
                                          placeholder="lighthouse.example.com:4242"
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                        />
                                      </div>
                                      {deviceDetailsForm.is_lighthouse && (
                                      <div>
                                        <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                                          Lighthouse options
                                        </p>
                                        <div className="flex items-center gap-2 mb-3">
                                          <Checkbox
                                            id="dd_serve_dns"
                                            checked={deviceDetailsForm.serve_dns}
                                            onChange={(e) =>
                                              setDeviceDetailsForm((f) => ({ ...f, serve_dns: e.target.checked }))
                                            }
                                            disabled={!deviceDetailsModal.isEditing}
                                          />
                                          <Label htmlFor="dd_serve_dns">Serve DNS</Label>
                                        </div>
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                                          <div className="min-w-0">
                                            <Label htmlFor="dd_dns_host" value="DNS host" className="text-gray-500 dark:text-gray-400" />
                                            <TextInput
                                              id="dd_dns_host"
                                              value={deviceDetailsForm.dns_host}
                                              onChange={(e) =>
                                                setDeviceDetailsForm((f) => ({ ...f, dns_host: e.target.value }))
                                              }
                                              disabled={!deviceDetailsModal.isEditing}
                                              className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                            />
                                          </div>
                                          <div className="min-w-0">
                                            <Label htmlFor="dd_dns_port" value="DNS port" className="text-gray-500 dark:text-gray-400" />
                                            <TextInput
                                              id="dd_dns_port"
                                              type="number"
                                              value={deviceDetailsForm.dns_port}
                                              onChange={(e) =>
                                                setDeviceDetailsForm((f) => ({ ...f, dns_port: e.target.value }))
                                              }
                                              disabled={!deviceDetailsModal.isEditing}
                                              className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                            />
                                          </div>
                                          <div className="min-w-0">
                                            <Label htmlFor="dd_interval" value="Report interval (seconds)" className="text-gray-500 dark:text-gray-400" />
                                            <TextInput
                                              id="dd_interval"
                                              type="number"
                                              value={deviceDetailsForm.interval_seconds}
                                              onChange={(e) =>
                                                setDeviceDetailsForm((f) => ({ ...f, interval_seconds: e.target.value }))
                                              }
                                              disabled={!deviceDetailsModal.isEditing}
                                              className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                            />
                                          </div>
                                        </div>
                                      </div>
                                      )}
                                    </div>
                                  )}

                                  <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-4">
                                    <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                                      Logging (Nebula config)
                                    </p>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                                      <div className="min-w-0">
                                        <Label htmlFor="dd_log_level" value="Level" className="text-gray-500 dark:text-gray-400" />
                                        <Select
                                          id="dd_log_level"
                                          value={deviceDetailsForm.log_level}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, log_level: e.target.value }))
                                          }
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                        >
                                          <option value="panic">panic</option>
                                          <option value="fatal">fatal</option>
                                          <option value="error">error</option>
                                          <option value="warning">warning</option>
                                          <option value="info">info</option>
                                          <option value="debug">debug</option>
                                        </Select>
                                      </div>
                                      <div className="min-w-0">
                                        <Label htmlFor="dd_log_format" value="Format" className="text-gray-500 dark:text-gray-400" />
                                        <Select
                                          id="dd_log_format"
                                          value={deviceDetailsForm.log_format}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, log_format: e.target.value }))
                                          }
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                        >
                                          <option value="text">text</option>
                                          <option value="json">json</option>
                                        </Select>
                                      </div>
                                      <div className="min-w-0 flex items-end pb-2">
                                        <div className="flex items-center gap-2">
                                          <Checkbox
                                            id="dd_log_disable_timestamp"
                                            checked={deviceDetailsForm.log_disable_timestamp}
                                            onChange={(e) =>
                                              setDeviceDetailsForm((f) => ({ ...f, log_disable_timestamp: e.target.checked }))
                                            }
                                            disabled={!deviceDetailsModal.isEditing}
                                          />
                                          <Label htmlFor="dd_log_disable_timestamp">Disable timestamp</Label>
                                        </div>
                                      </div>
                                      <div className="min-w-0">
                                        <Label htmlFor="dd_log_timestamp_format" value="Timestamp format (Go format, optional)" className="text-gray-500 dark:text-gray-400" />
                                        <TextInput
                                          id="dd_log_timestamp_format"
                                          value={deviceDetailsForm.log_timestamp_format}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, log_timestamp_format: e.target.value }))
                                          }
                                          placeholder="e.g. 2006-01-02T15:04:05.000Z07:00"
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                        />
                                      </div>
                                    </div>
                                  </div>

                                  <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-4">
                                    <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                                      Punchy (NAT traversal)
                                    </p>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                                      <div className="min-w-0 flex items-end pb-2">
                                        <div className="flex items-center gap-2">
                                          <Checkbox
                                            id="dd_punchy_respond"
                                            checked={deviceDetailsForm.punchy_respond}
                                            onChange={(e) =>
                                              setDeviceDetailsForm((f) => ({ ...f, punchy_respond: e.target.checked }))
                                            }
                                            disabled={!deviceDetailsModal.isEditing}
                                          />
                                          <Label htmlFor="dd_punchy_respond">Respond (punch back)</Label>
                                        </div>
                                      </div>
                                      <div className="min-w-0">
                                        <Label htmlFor="dd_punchy_delay" value="Delay (e.g. 1s)" className="text-gray-500 dark:text-gray-400" />
                                        <TextInput
                                          id="dd_punchy_delay"
                                          value={deviceDetailsForm.punchy_delay}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, punchy_delay: e.target.value }))
                                          }
                                          placeholder="1s"
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                        />
                                      </div>
                                      <div className="min-w-0">
                                        <Label htmlFor="dd_punchy_respond_delay" value="Respond delay (e.g. 5s)" className="text-gray-500 dark:text-gray-400" />
                                        <TextInput
                                          id="dd_punchy_respond_delay"
                                          value={deviceDetailsForm.punchy_respond_delay}
                                          onChange={(e) =>
                                            setDeviceDetailsForm((f) => ({ ...f, punchy_respond_delay: e.target.value }))
                                          }
                                          placeholder="5s"
                                          disabled={!deviceDetailsModal.isEditing}
                                          className={`min-w-0 w-full ${!deviceDetailsModal.isEditing ? "bg-gray-50 dark:bg-gray-800 border-none cursor-default" : ""}`}
                                        />
                                      </div>
                                    </div>
                                  </div>

                                  <div className="flex flex-wrap items-center justify-between gap-2 pt-4 border-t border-gray-200 dark:border-gray-700">
                                    <div className="flex flex-wrap gap-2">
                                      <Button type="button" color="gray" onClick={closeDeviceDetailsModal}>
                                        Close
                                      </Button>
                                      {!deviceDetailsModal.isEditing ? (
                                        <Button
                                          type="button"
                                          color="gray"
                                          onClick={() => setDeviceDetailsModal((s) => ({ ...s, isEditing: true }))}
                                        >
                                          <HiPencil className="w-4 h-4 mr-1" />
                                          Edit
                                        </Button>
                                      ) : (
                                        <Button
                                          type="button"
                                          color="gray"
                                          onClick={() => {
                                            const node = deviceDetailsModal.node;
                                            if (node) {
                                              setDeviceDetailsForm({
                                                group: (node.groups && node.groups[0]) ?? "",
                                                is_lighthouse: node.is_lighthouse,
                                                is_relay: node.is_relay,
                                                public_endpoint: node.public_endpoint ?? "",
                                                serve_dns: node.lighthouse_options?.serve_dns ?? false,
                                                dns_host: node.lighthouse_options?.dns_host ?? "0.0.0.0",
                                                dns_port: String(node.lighthouse_options?.dns_port ?? 53),
                                                interval_seconds: String(node.lighthouse_options?.interval_seconds ?? 60),
                                                log_level: node.logging_options?.level ?? "info",
                                                log_format: node.logging_options?.format ?? "text",
                                                log_disable_timestamp: node.logging_options?.disable_timestamp ?? false,
                                                log_timestamp_format: node.logging_options?.timestamp_format ?? "",
                                                punchy_respond: node.punchy_options?.respond ?? true,
                                                punchy_delay: node.punchy_options?.delay ?? "",
                                                punchy_respond_delay: node.punchy_options?.respond_delay ?? "",
                                              });
                                              setDeviceDetailsModal((s) => ({ ...s, isEditing: false }));
                                            }
                                          }}
                                        >
                                          Cancel
                                        </Button>
                                      )}
                                      {deviceDetailsModal.node && (
                                        <>
                                          <Button
                                            type="button"
                                            color="warning"
                                            onClick={() => openReEnrollModal(deviceDetailsModal.node!)}
                                          >
                                            Re-Enroll
                                          </Button>
                                          {deviceDetailsModal.node.ip_address && (
                                            <Button
                                              type="button"
                                              color="failure"
                                              onClick={() => openRevokeModal(deviceDetailsModal.node!)}
                                            >
                                              Revoke Certificate
                                            </Button>
                                          )}
                                        </>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-2">
                                      {deviceDetailsModal.isEditing && hasDeviceDetailsFormChanges() && (
                                        deviceDetailsModal.showSaved ? (
                                          <span
                                            className={`inline-flex items-center gap-1 text-green-600 dark:text-green-400 text-sm font-medium transition-opacity duration-500 ease-in-out ${
                                              deviceDetailsModal.savedFading ? "opacity-0" : "opacity-100"
                                            }`}
                                          >
                                            <HiCheckCircle className="w-5 h-5" />
                                            Saved
                                          </span>
                                        ) : (
                                          <Button
                                            type="submit"
                                            color="purple"
                                            isProcessing={saving}
                                            disabled={saving}
                                          >
                                            Save
                                          </Button>
                                        )
                                      )}
                                    </div>
                                  </div>
                                </>
                              )}
                            </form>
                          </div>
                        </Table.Cell>
                      </Table.Row>
                    )}
                    </Fragment>
                  );
                })}
              </Table.Body>
            </Table>
            {nodes.length === 0 && (
              <div className="p-4 text-center text-gray-500 dark:text-gray-400">
                No nodes yet. Create a node to get started.
              </div>
            )}
          </div>
        </Card>
      )}

      <Modal show={reEnrollModal.open} onClose={closeReEnrollModal} size="md">
        <Modal.Header>Re-Enroll Device</Modal.Header>
        <Modal.Body>
          <p className="text-gray-700 dark:text-gray-300">
            This will generate a new certificate for this device. The current certificate will be
            revoked and any node currently enrolled with the old certificate will no longer function.
            Do you want to continue?
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button color="gray" onClick={closeReEnrollModal}>
            Cancel
          </Button>
          <Button
            color="warning"
            onClick={handleReEnrollConfirm}
            isProcessing={reEnrollModal.processing}
            disabled={reEnrollModal.processing}
          >
            Re-Enroll
          </Button>
        </Modal.Footer>
      </Modal>

      <Modal show={revokeModal.open} onClose={closeRevokeModal} size="md">
        <Modal.Header>Revoke Certificate</Modal.Header>
        <Modal.Body>
          <p className="text-gray-700 dark:text-gray-300">
            This will revoke the node&apos;s certificate and take it offline. The node will no
            longer be able to connect to the network. You can re-enroll it later to issue a new
            certificate. Do you want to continue?
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button color="gray" onClick={closeRevokeModal}>
            Cancel
          </Button>
          <Button
            color="failure"
            onClick={handleRevokeConfirm}
            isProcessing={revokeModal.processing}
            disabled={revokeModal.processing}
          >
            Revoke
          </Button>
        </Modal.Footer>
      </Modal>

      <Modal show={deleteModal.open} onClose={closeDeleteModal} size="md">
        <Modal.Header>Delete node</Modal.Header>
        <Modal.Body>
          {deleteModal.step === 1 && deleteModal.node && (
            <div className="space-y-4">
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete the node <strong>{deleteModal.node.hostname}</strong>? This will remove the node, its certificate, enrollment codes, and release its IP. This cannot be undone.
              </p>
              {isOnlyLighthouseInNetwork(deleteModal.node) && (
                <Alert color="failure">
                  Cannot delete the only lighthouse. Designate another node as lighthouse first, or delete the network.
                </Alert>
              )}
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
                disabled={deleteModal.node ? isOnlyLighthouseInNetwork(deleteModal.node) : false}
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

    </div>
  );
}
