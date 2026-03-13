import { useEffect, useState } from "react";
import { Card, Table, Button, TextInput, Label, Select, ToggleSwitch } from "flowbite-react";
import type { Network } from "../types/networks";
import { listNetworks } from "../api/client";
import { listNodesForNetwork, getDNSConfig, upsertDNSConfig, listDNSAliases, createDNSAlias, deleteDNSAlias } from "../api/dns";

interface DNSConfig {
  domain: string;
  enabled: boolean;
  upstream_servers: string[];
}

interface NodeItem {
  id: number;
  hostname: string;
  ip_address: string | null;
}

interface DNSAlias {
  id: number;
  alias: string;
  node_id: number;
  node_hostname: string;
}

export function DNS() {
  const [networks, setNetworks] = useState<Network[]>([]);
  const [selectedNetworkId, setSelectedNetworkId] = useState<number | "">("");
  const [config, setConfig] = useState<DNSConfig | null>(null);
  const [domainInput, setDomainInput] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [upstreamServersText, setUpstreamServersText] = useState("");
  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [aliases, setAliases] = useState<DNSAlias[]>([]);
  const [newAlias, setNewAlias] = useState("");
  const [newAliasNodeId, setNewAliasNodeId] = useState<number | "">("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const [savingAlias, setSavingAlias] = useState(false);
  const [deletingAliasId, setDeletingAliasId] = useState<number | null>(null);

  useEffect(() => {
    listNetworks()
      .then(setNetworks)
      .catch((e: any) => setError(e.message || "Failed to load networks"));
  }, []);

  useEffect(() => {
    if (selectedNetworkId === "") {
      setConfig(null);
      setDomainInput("");
      setEnabled(true);
      setNodes([]);
      setAliases([]);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        setLoading(true);
        const [cfg, nodeList, aliasList] = await Promise.all([
          getDNSConfig(selectedNetworkId as number).catch(() => null),
          listNodesForNetwork(selectedNetworkId as number),
          listDNSAliases(selectedNetworkId as number),
        ]);
        if (cancelled) return;
        if (cfg) {
          setConfig(cfg);
          setDomainInput(cfg.domain);
          setEnabled(cfg.enabled);
          setUpstreamServersText((cfg.upstream_servers ?? []).join("\n"));
        } else {
          setConfig(null);
          setDomainInput("");
          setEnabled(true);
          setUpstreamServersText("");
        }
        setNodes(nodeList);
        setAliases(aliasList);
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message || "Failed to load DNS data");
          setNodes([]);
          setAliases([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [selectedNetworkId]);

  const handleSaveConfig = async () => {
    if (selectedNetworkId === "" || !domainInput.trim()) return;
    try {
      setSavingConfig(true);
      const servers = upstreamServersText
        .split(/\n/)
        .map((s) => s.trim())
        .filter(Boolean);
      const body = {
        domain: domainInput.trim(),
        enabled,
        upstream_servers: servers,
      };
      const saved = await upsertDNSConfig(selectedNetworkId as number, body);
      setConfig(saved);
      setUpstreamServersText((saved.upstream_servers ?? []).join("\n"));
    } catch (e: any) {
      setError(e.message || "Failed to save DNS config");
    } finally {
      setSavingConfig(false);
    };
  };

  const handleAddAlias = async () => {
    if (selectedNetworkId === "" || !newAlias.trim() || newAliasNodeId === "") return;
    try {
      setSavingAlias(true);
      const created = await createDNSAlias(selectedNetworkId as number, {
        alias: newAlias.trim(),
        node_id: Number(newAliasNodeId),
      });
      setAliases((prev) => [...prev, created]);
      setNewAlias("");
      setNewAliasNodeId("");
    } catch (e: any) {
      setError(e.message || "Failed to create alias");
    } finally {
      setSavingAlias(false);
    };
  };

  const handleDeleteAlias = async (id: number) => {
    if (selectedNetworkId === "") return;
    try {
      setDeletingAliasId(id);
      await deleteDNSAlias(selectedNetworkId as number, id);
      setAliases((prev) => prev.filter((a) => a.id !== id));
    } catch (e: any) {
      setError(e.message || "Failed to delete alias");
    } finally {
      setDeletingAliasId(null);
    }
  };

  const fqdnFor = (hostname: string) =>
    config ? `${hostname}.${config.domain}` : hostname;

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">DNS</h1>
      <p className="text-gray-600 dark:text-gray-400 mb-4">
        Configure per-network DNS zones served by dnsmasq on lighthouses. Each node
        is exposed as <code>hostname.domain</code>, with optional aliases.
      </p>

      {error && (
        <div className="mb-4 p-4 text-red-700 bg-red-100 rounded-lg dark:bg-red-200 dark:text-red-800 flex justify-between items-center">
          <span>{error}</span>
          <Button size="xs" color="failure" onClick={() => setError(null)}>
            Dismiss
          </Button>
        </div>
      )}

      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <div>
            <Label htmlFor="dns_network_select" value="Network" />
            <Select
              id="dns_network_select"
              value={selectedNetworkId === "" ? "" : String(selectedNetworkId)}
              onChange={(e) =>
                setSelectedNetworkId(
                  e.target.value === "" ? "" : Number(e.target.value)
                )
              }
            >
              <option value="">Select a network</option>
              {networks.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name} ({n.subnet_cidr})
                </option>
              ))}
            </Select>
          </div>
        </div>

        {selectedNetworkId === "" && (
          <p className="text-gray-500 dark:text-gray-400">
            Select a network to manage DNS.
          </p>
        )}

        {selectedNetworkId !== "" && (
          <>
            <div className="mb-6">
              <h2 className="text-xl font-semibold mb-2">Zone</h2>
              <div className="flex flex-wrap items-end gap-4">
                <div>
                  <Label htmlFor="dns_domain" value="Domain" />
                  <TextInput
                    id="dns_domain"
                    value={domainInput}
                    onChange={(e) => setDomainInput(e.target.value)}
                    placeholder="nebula.example.com or nebula"
                    className="w-72"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <ToggleSwitch
                    checked={enabled}
                    label="Enable DNS for this network"
                    onChange={setEnabled}
                  />
                </div>
                <div>
                  <Button
                    color="blue"
                    onClick={handleSaveConfig}
                    disabled={!domainInput.trim() || savingConfig}
                    isProcessing={savingConfig}
                  >
                    Save
                  </Button>
                </div>
              </div>
              <div className="mt-4">
                <Label htmlFor="dns_upstream" value="Upstream DNS servers (one per line)" />
                <textarea
                  id="dns_upstream"
                  value={upstreamServersText}
                  onChange={(e) => setUpstreamServersText(e.target.value)}
                  placeholder="8.8.8.8&#10;1.1.1.1"
                  rows={3}
                  className="mt-1 block w-full max-w-md rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400"
                />
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Used for non-local queries. Leave empty to use container default resolvers.
                </p>
              </div>
            </div>

            <div className="mb-6">
              <h2 className="text-xl font-semibold mb-2">Nodes</h2>
              {loading && (
                <p className="text-gray-500 dark:text-gray-400">
                  Loading nodes...
                </p>
              )}
              {!loading && (
                <div className="overflow-x-auto">
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Hostname</Table.HeadCell>
                      <Table.HeadCell>FQDN</Table.HeadCell>
                      <Table.HeadCell>IP</Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {nodes.map((n) => (
                        <Table.Row key={n.id}>
                          <Table.Cell>{n.hostname}</Table.Cell>
                          <Table.Cell>
                            {config ? fqdnFor(n.hostname) : "—"}
                          </Table.Cell>
                          <Table.Cell>{n.ip_address ?? "pending"}</Table.Cell>
                        </Table.Row>
                      ))}
                      {nodes.length === 0 && (
                        <Table.Row>
                          <Table.Cell colSpan={3}>
                            <span className="text-gray-500 dark:text-gray-400">
                              No nodes in this network yet.
                            </span>
                          </Table.Cell>
                        </Table.Row>
                      )}
                    </Table.Body>
                  </Table>
                </div>
              )}
            </div>

            <div>
              <h2 className="text-xl font-semibold mb-2">Aliases</h2>
              <div className="overflow-x-auto mb-2">
                <Table>
                  <Table.Head>
                    <Table.HeadCell>Alias</Table.HeadCell>
                    <Table.HeadCell>Target node</Table.HeadCell>
                    <Table.HeadCell>FQDN</Table.HeadCell>
                    <Table.HeadCell />
                  </Table.Head>
                  <Table.Body>
                    {aliases.map((a) => (
                      <Table.Row key={a.id}>
                        <Table.Cell>{a.alias}</Table.Cell>
                        <Table.Cell>{a.node_hostname}</Table.Cell>
                        <Table.Cell>
                          {config ? `${a.alias}.${config.domain}` : a.alias}
                        </Table.Cell>
                        <Table.Cell>
                          <Button
                            size="xs"
                            color="failure"
                            onClick={() => handleDeleteAlias(a.id)}
                            disabled={deletingAliasId === a.id}
                            isProcessing={deletingAliasId === a.id}
                          >
                            Remove
                          </Button>
                        </Table.Cell>
                      </Table.Row>
                    ))}
                    {aliases.length === 0 && (
                      <Table.Row>
                        <Table.Cell colSpan={4}>
                          <span className="text-gray-500 dark:text-gray-400">
                            No aliases defined.
                          </span>
                        </Table.Cell>
                      </Table.Row>
                    )}
                    <Table.Row>
                      <Table.Cell>
                        <TextInput
                          value={newAlias}
                          onChange={(e) => setNewAlias(e.target.value)}
                          placeholder="Alias (e.g. api)"
                        />
                      </Table.Cell>
                      <Table.Cell>
                        <Select
                          value={newAliasNodeId === "" ? "" : String(newAliasNodeId)}
                          onChange={(e) =>
                            setNewAliasNodeId(
                              e.target.value === "" ? "" : Number(e.target.value)
                            )
                          }
                        >
                          <option value="">Select node…</option>
                          {nodes.map((n) => (
                            <option key={n.id} value={n.id}>
                              {n.hostname}
                            </option>
                          ))}
                        </Select>
                      </Table.Cell>
                      <Table.Cell colSpan={2}>
                        <Button
                          size="sm"
                          color="blue"
                          onClick={handleAddAlias}
                          disabled={
                            !newAlias.trim() ||
                            newAliasNodeId === "" ||
                            savingAlias
                          }
                          isProcessing={savingAlias}
                        >
                          Add alias
                        </Button>
                      </Table.Cell>
                    </Table.Row>
                  </Table.Body>
                </Table>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

