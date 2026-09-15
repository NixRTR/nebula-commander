import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, Table, Button, TextInput, Label, Select, Modal } from "flowbite-react";
import { HiPlus, HiTrash } from "react-icons/hi";
import type { Network, GroupFirewallConfig, InboundFirewallRule } from "../types/networks";
import {
  listNetworks,
  listGroupFirewall,
  updateGroupFirewall,
  deleteGroupFirewall,
} from "../api/client";

const PROTOCOLS: InboundFirewallRule["protocol"][] = ["any", "tcp", "udp", "icmp"];

const emptyRule = (): InboundFirewallRule => ({
  allowed_group: "",
  protocol: "any",
  port_range: "any",
  description: "",
});

export function Groups() {
  const [searchParams] = useSearchParams();
  const [networks, setNetworks] = useState<Network[]>([]);
  const [selectedNetworkId, setSelectedNetworkId] = useState<number | "">(() => {
    const n = searchParams.get("network");
    return n ? Number(n) : "";
  });
  const [groupList, setGroupList] = useState<GroupFirewallConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailGroup, setDetailGroup] = useState<string | null>(null);
  const [draftRules, setDraftRules] = useState<Record<string, InboundFirewallRule[]>>({});
  const [newGroupName, setNewGroupName] = useState("");
  const [showAddGroup, setShowAddGroup] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    listNetworks()
      .then(setNetworks)
      .catch(() => setNetworks([]));
  }, []);

  useEffect(() => {
    if (selectedNetworkId === "") {
      return;
    }

    let cancelled = false;

    const loadGroups = async () => {
      try {
        setLoading(true);
        setGroupList([]);
        const groups = await listGroupFirewall(selectedNetworkId as number);
        if (!cancelled) {
          setGroupList(groups);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message);
          setGroupList([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadGroups();

    return () => {
      cancelled = true;
    };
  }, [selectedNetworkId]);

  const getRules = (groupName: string): InboundFirewallRule[] => {
    if (draftRules[groupName]) return draftRules[groupName];
    const g = groupList.find((x) => x.group_name === groupName);
    return g?.inbound_rules ?? [];
  };

  const setRules = (groupName: string, rules: InboundFirewallRule[]) => {
    setDraftRules((s) => ({ ...s, [groupName]: rules }));
  };

  const addRule = (groupName: string) => {
    setRules(groupName, [...getRules(groupName), emptyRule()]);
  };

  const removeRule = (groupName: string, idx: number) => {
    setRules(groupName, getRules(groupName).filter((_, i) => i !== idx));
  };

  const updateRule = (
    groupName: string,
    idx: number,
    field: keyof InboundFirewallRule,
    value: string
  ) => {
    const rules = [...getRules(groupName)];
    rules[idx] = { ...rules[idx], [field]: value };
    setRules(groupName, rules);
  };

  const handleSave = (groupName: string) => {
    if (selectedNetworkId === "") return;
    const rules = getRules(groupName);
    setSaving(groupName);
    updateGroupFirewall(selectedNetworkId as number, groupName, { inbound_rules: rules })
      .then(() => listGroupFirewall(selectedNetworkId as number).then(setGroupList))
      .then(() =>
        setDraftRules((s) => {
          const next = { ...s };
          delete next[groupName];
          return next;
        })
      )
      .catch((e) => setError(e.message))
      .finally(() => setSaving(null));
  };

  const handleDeleteGroup = (groupName: string) => {
    if (selectedNetworkId === "" || !window.confirm(`Remove group "${groupName}" and its rules?`))
      return;
    setDeleting(groupName);
    deleteGroupFirewall(selectedNetworkId as number, groupName)
      .then(() => listGroupFirewall(selectedNetworkId as number).then(setGroupList))
      .then(() => {
        setDraftRules((s) => {
          const next = { ...s };
          delete next[groupName];
          return next;
        });
        if (detailGroup === groupName) setDetailGroup(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setDeleting(null));
  };

  const handleAddGroup = () => {
    const name = newGroupName.trim();
    if (selectedNetworkId === "" || !name) return;
    setSaving(name);
    updateGroupFirewall(selectedNetworkId as number, name, { inbound_rules: [] })
      .then(() => listGroupFirewall(selectedNetworkId as number).then(setGroupList))
      .then(() => {
        setNewGroupName("");
        setShowAddGroup(false);
        setDetailGroup(name);
      })
      .catch((e) => setError(e.message))
      .finally(() => setSaving(null));
  };

  const detailRules = detailGroup ? getRules(detailGroup) : [];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Groups (Roles)</h1>
      <p className="text-gray-600 dark:text-gray-400 mb-4">
        Inbound traffic is denied by default. Configure per-group inbound rules to allow traffic from specific groups.
        Each node has one group; rules here define who can reach nodes in that group.
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
            <Label htmlFor="network_select" value="Network" />
            <Select
              id="network_select"
              value={selectedNetworkId === "" ? "" : String(selectedNetworkId)}
              onChange={(e) =>
                setSelectedNetworkId(e.target.value === "" ? "" : Number(e.target.value))
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
          {selectedNetworkId !== "" && (
            <>
              {!showAddGroup && (
                <Button
                  size="sm"
                  color="gray"
                  onClick={() => setShowAddGroup(true)}
                  className="mt-6"
                >
                  <HiPlus className="w-4 h-4 mr-1" />
                  Add group
                </Button>
              )}
            </>
          )}
        </div>

        {showAddGroup && selectedNetworkId !== "" && (
          <div className="flex flex-wrap gap-2 items-center p-2 bg-gray-50 dark:bg-gray-800 rounded mb-4">
            <TextInput
              className="w-48"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              placeholder="Group name (e.g. servers)"
            />
            <Button
              size="sm"
              color="blue"
              onClick={handleAddGroup}
              disabled={!newGroupName.trim() || saving !== null}
              isProcessing={saving !== null}
            >
              Create
            </Button>
            <Button size="sm" color="gray" onClick={() => setShowAddGroup(false)}>
              Cancel
            </Button>
          </div>
        )}

        {selectedNetworkId === "" && (
          <p className="text-gray-500 dark:text-gray-400">Select a network to manage groups.</p>
        )}

        {selectedNetworkId !== "" && loading && (
          <p className="text-gray-500 dark:text-gray-400">Loading groups...</p>
        )}

        {selectedNetworkId !== "" && !loading && (
          <>
            {groupList.length === 0 && !showAddGroup ? (
              <p className="text-gray-500 dark:text-gray-400 py-4">
                No groups yet. Add a group to define inbound rules for nodes in that group.
              </p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {groupList.map((gf) => {
                  const ruleCount = (gf.inbound_rules || []).length;
                  const open = ruleCount === 0;
                  return (
                    <button
                      key={gf.group_name}
                      type="button"
                      onClick={() => setDetailGroup(gf.group_name)}
                      className="relative aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
                    >
                      <p className="font-semibold text-gray-900 dark:text-white truncate" title={gf.group_name}>
                        {gf.group_name}
                      </p>
                      <div className="mt-auto">
                        {open ? (
                          <span className="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                            <span className="inline-block w-2.5 h-2.5 rounded-full border-2 border-dashed border-gray-400" />
                            Open
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                            <span className="inline-block w-2.5 h-2.5 rounded-full bg-purple-500" />
                            {ruleCount} rule{ruleCount === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </>
        )}
      </Card>

      <Modal show={detailGroup !== null} onClose={() => setDetailGroup(null)} size="4xl">
        <Modal.Header>{detailGroup}</Modal.Header>
        <Modal.Body>
          {detailGroup && (
            <>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                Inbound firewall rules: allow traffic from the specified group to this group.
                Port range: single port, comma list, or ranges (e.g. 22,80-88,443).
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <Table.Head>
                    <Table.HeadCell>Allowed group</Table.HeadCell>
                    <Table.HeadCell>Protocol</Table.HeadCell>
                    <Table.HeadCell>Port range</Table.HeadCell>
                    <Table.HeadCell>Description</Table.HeadCell>
                    <Table.HeadCell></Table.HeadCell>
                  </Table.Head>
                  <Table.Body>
                    {detailRules.map((r, idx) => (
                      <Table.Row key={idx}>
                        <Table.Cell>
                          <Select
                            value={r.allowed_group || "All"}
                            onChange={(e) => updateRule(detailGroup, idx, "allowed_group", e.target.value)}
                            className="min-w-[120px]"
                          >
                            <option value="All">All</option>
                            {groupList.map((g) => (
                              <option key={g.group_name} value={g.group_name}>
                                {g.group_name}
                              </option>
                            ))}
                          </Select>
                        </Table.Cell>
                        <Table.Cell>
                          <Select
                            value={r.protocol}
                            onChange={(e) =>
                              updateRule(detailGroup, idx, "protocol", e.target.value as InboundFirewallRule["protocol"])
                            }
                          >
                            {PROTOCOLS.map((p) => (
                              <option key={p} value={p}>
                                {p}
                              </option>
                            ))}
                          </Select>
                        </Table.Cell>
                        <Table.Cell>
                          <TextInput
                            value={r.port_range}
                            onChange={(e) => updateRule(detailGroup, idx, "port_range", e.target.value)}
                            placeholder="any or 22,80-88"
                            className="min-w-[120px]"
                          />
                        </Table.Cell>
                        <Table.Cell>
                          <TextInput
                            value={r.description ?? ""}
                            onChange={(e) => updateRule(detailGroup, idx, "description", e.target.value)}
                            placeholder="Optional"
                            className="min-w-[140px]"
                          />
                        </Table.Cell>
                        <Table.Cell>
                          <Button
                            type="button"
                            size="xs"
                            color="failure"
                            onClick={() => removeRule(detailGroup, idx)}
                          >
                            <HiTrash className="w-4 h-4" />
                          </Button>
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </div>
              <Button
                type="button"
                size="xs"
                color="gray"
                onClick={() => addRule(detailGroup)}
                className="mt-2"
              >
                <HiPlus className="w-4 h-4 mr-1" />
                Add firewall rule
              </Button>
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button
            type="button"
            color="blue"
            onClick={() => detailGroup && handleSave(detailGroup)}
            disabled={saving !== null}
            isProcessing={detailGroup !== null && saving === detailGroup}
          >
            Save
          </Button>
          <Button
            type="button"
            color="failure"
            onClick={() => detailGroup && handleDeleteGroup(detailGroup)}
            disabled={deleting !== null}
            isProcessing={detailGroup !== null && deleting === detailGroup}
          >
            <HiTrash className="w-4 h-4 mr-1" />
            Delete Group
          </Button>
          <Button type="button" color="gray" onClick={() => setDetailGroup(null)}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
