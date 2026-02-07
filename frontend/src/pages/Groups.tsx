import { useEffect, useState } from "react";
import { Card, Table, Button, TextInput, Label, Select } from "flowbite-react";
import { HiPlus, HiTrash, HiChevronDown, HiChevronRight } from "react-icons/hi";
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
  const [networks, setNetworks] = useState<Network[]>([]);
  const [selectedNetworkId, setSelectedNetworkId] = useState<number | "">("");
  const [groupList, setGroupList] = useState<GroupFirewallConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
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
    setLoading(true);
    setGroupList([]);
    listGroupFirewall(selectedNetworkId as number)
      .then(setGroupList)
      .catch((e) => {
        setError(e.message);
        setGroupList([]);
      })
      .finally(() => setLoading(false));
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
        if (expandedGroup === groupName) setExpandedGroup(null);
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
        setExpandedGroup(name);
      })
      .catch((e) => setError(e.message))
      .finally(() => setSaving(null));
  };

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
          <div className="space-y-2">
            {groupList.map((gf) => {
              const isExpanded = expandedGroup === gf.group_name;
              const rules = getRules(gf.group_name);
              return (
                <div
                  key={gf.group_name}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
                >
                  <div className="flex items-center gap-2 p-2 bg-gray-50 dark:bg-gray-800">
                    <Button
                      type="button"
                      size="xs"
                      color="gray"
                      onClick={() => setExpandedGroup(isExpanded ? null : gf.group_name)}
                    >
                      {isExpanded ? (
                        <HiChevronDown className="w-4 h-4" />
                      ) : (
                        <HiChevronRight className="w-4 h-4" />
                      )}
                    </Button>
                    <span className="font-medium flex-1">{gf.group_name}</span>
                    <Button
                      type="button"
                      size="xs"
                      color="blue"
                      onClick={() => handleSave(gf.group_name)}
                      disabled={saving !== null}
                      isProcessing={saving === gf.group_name}
                    >
                      Save
                    </Button>
                    <Button
                      type="button"
                      size="xs"
                      color="failure"
                      onClick={() => handleDeleteGroup(gf.group_name)}
                      disabled={deleting !== null}
                      isProcessing={deleting === gf.group_name}
                    >
                      <HiTrash className="w-4 h-4" />
                    </Button>
                  </div>
                  {isExpanded && (
                    <div className="p-4 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700">
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
                            {rules.map((r, idx) => (
                              <Table.Row key={idx}>
                                <Table.Cell>
                                  <TextInput
                                    value={r.allowed_group}
                                    onChange={(e) =>
                                      updateRule(gf.group_name, idx, "allowed_group", e.target.value)
                                    }
                                    placeholder="e.g. laptops or All"
                                    className="min-w-[120px]"
                                  />
                                </Table.Cell>
                                <Table.Cell>
                                  <Select
                                    value={r.protocol}
                                    onChange={(e) =>
                                      updateRule(
                                        gf.group_name,
                                        idx,
                                        "protocol",
                                        e.target.value as InboundFirewallRule["protocol"]
                                      )
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
                                    onChange={(e) =>
                                      updateRule(gf.group_name, idx, "port_range", e.target.value)
                                    }
                                    placeholder="any or 22,80-88"
                                    className="min-w-[120px]"
                                  />
                                </Table.Cell>
                                <Table.Cell>
                                  <TextInput
                                    value={r.description ?? ""}
                                    onChange={(e) =>
                                      updateRule(gf.group_name, idx, "description", e.target.value)
                                    }
                                    placeholder="Optional"
                                    className="min-w-[140px]"
                                  />
                                </Table.Cell>
                                <Table.Cell>
                                  <Button
                                    type="button"
                                    size="xs"
                                    color="failure"
                                    onClick={() => removeRule(gf.group_name, idx)}
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
                        onClick={() => addRule(gf.group_name)}
                        className="mt-2"
                      >
                        <HiPlus className="w-4 h-4 mr-1" />
                        Add firewall rule
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
            {groupList.length === 0 && !showAddGroup && (
              <p className="text-gray-500 dark:text-gray-400 py-4">
                No groups yet. Add a group to define inbound rules for nodes in that group.
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
