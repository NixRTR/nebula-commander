import { useEffect, useState } from "react";
import { Card, Button, TextInput, Label, Select } from "flowbite-react";
import { HiPlus } from "react-icons/hi";
import { useNavigate } from "react-router-dom";
import type { Network, NetworkCreate } from "../types/networks";
import type { Node } from "../types/nodes";
import { listNetworks, listNodes, createNetwork } from "../api/client";
import { isNodeActive } from "../utils/nodeStatus";

export function Networks() {
  const navigate = useNavigate();
  const [networks, setNetworks] = useState<Network[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<NetworkCreate>({
    name: "",
    subnet_cidr: "10.100.0.0/24",
    cert_curve: "25519",
  });

  const load = () => {
    setLoading(true);
    Promise.all([listNetworks(), listNodes()])
      .then(([n, nd]) => {
        setNetworks(n);
        setNodes(nd);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const id = setTimeout(load, 0);
    return () => clearTimeout(id);
  }, []);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createNetwork(form)
      .then(() => {
        setForm({ name: "", subnet_cidr: "10.100.0.0/24", cert_curve: "25519" });
        setShowForm(false);
        load();
      })
      .catch((e) => setError(e.message));
  };

  const nodeCounts = (networkId: number): { active: number; total: number } => {
    const inNetwork = nodes.filter((n) => n.network_id === networkId);
    return { active: inNetwork.filter(isNodeActive).length, total: inNetwork.length };
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Networks</h1>
        <Button
          onClick={() => setShowForm(!showForm)}
          color={showForm ? "gray" : "purple"}
          data-onboarding-target="networks-create-button"
        >
          <HiPlus className="mr-2 h-5 w-5" />
          {showForm ? "Cancel" : "Add Network"}
        </Button>
      </div>

      {error && (
        <div className="mb-4 p-4 text-red-700 bg-red-100 rounded-lg dark:bg-red-200 dark:text-red-800">
          {error}
        </div>
      )}

      {showForm && (
        <Card className="mb-6">
          <h2 className="text-xl font-semibold mb-4">Create Network</h2>
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <Label htmlFor="name" value="Network Name" />
              <TextInput
                id="name"
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="my-network"
                required
              />
            </div>
            <div>
              <Label htmlFor="subnet" value="Subnet CIDR" />
              <TextInput
                id="subnet"
                type="text"
                value={form.subnet_cidr}
                onChange={(e) => setForm((f) => ({ ...f, subnet_cidr: e.target.value }))}
                placeholder="10.100.0.0/24"
                required
              />
            </div>
            <div>
              <Label htmlFor="cert_curve" value="Certificate Curve" />
              <Select
                id="cert_curve"
                value={form.cert_curve}
                onChange={(e) =>
                  setForm((f) => ({ ...f, cert_curve: e.target.value as "25519" | "P256" }))
                }
              >
                <option value="25519">Curve25519 (default)</option>
                <option value="P256">P256</option>
              </Select>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Applies to every node on this network. Cannot be changed after creation.
              </p>
            </div>
            <Button type="submit" color="purple">
              Create Network
            </Button>
          </form>
        </Card>
      )}

      {loading ? (
        <Card>
          <p className="text-gray-600 dark:text-gray-400">Loading networks...</p>
        </Card>
      ) : (
        <Card>
          {networks.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-gray-500 dark:text-gray-400 mb-2">No networks yet.</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                Create a network to define your overlay subnet. Configure per-group firewall rules on the Groups page.
              </p>
              <Button color="purple" onClick={() => setShowForm(true)} data-onboarding-target="networks-create-button">
                <HiPlus className="mr-2 h-5 w-5" />
                Add your first network
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
              {networks.map((n) => {
                const { active, total } = nodeCounts(n.id);
                return (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => navigate(`/networks/${n.id}`)}
                    className="relative aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-[var(--nc-bg2-light)] dark:bg-[var(--nc-bg2-dark)] p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
                  >
                    <p className="font-semibold text-lg text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] truncate" title={n.name}>
                      {n.name}
                    </p>
                    <p className="text-xs font-mono text-gray-500 dark:text-gray-400 truncate mb-3">
                      {n.subnet_cidr}
                    </p>
                    <div className="mt-auto grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Nodes</div>
                        <div className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">
                          {active}/{total}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Groups</div>
                        <div className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{n.group_count}</div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">DNS Entries</div>
                        <div className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{n.dns_entry_count}</div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Users</div>
                        <div className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{n.user_count}</div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
