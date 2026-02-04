import { useEffect, useState } from "react";
import { Card, Table, Button, TextInput, Label } from "flowbite-react";
import { HiPlus } from "react-icons/hi";
import type { Network, NetworkCreate } from "../types/networks";
import { listNetworks, createNetwork } from "../api/client";

export function Networks() {
  const [networks, setNetworks] = useState<Network[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<NetworkCreate>({
    name: "",
    subnet_cidr: "10.100.0.0/24",
  });

  const load = () => {
    setLoading(true);
    listNetworks()
      .then(setNetworks)
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
        setForm({ name: "", subnet_cidr: "10.100.0.0/24" });
        setShowForm(false);
        load();
      })
      .catch((e) => setError(e.message));
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Networks</h1>
        <Button
          onClick={() => setShowForm(!showForm)}
          color={showForm ? "gray" : "blue"}
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
            <Button type="submit" color="blue">
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
          <div className="overflow-x-auto">
            <Table>
              <Table.Head>
                <Table.HeadCell>ID</Table.HeadCell>
                <Table.HeadCell>Name</Table.HeadCell>
                <Table.HeadCell>Subnet</Table.HeadCell>
                <Table.HeadCell>Created</Table.HeadCell>
              </Table.Head>
              <Table.Body className="divide-y">
                {networks.map((n) => (
                  <Table.Row key={n.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                      {n.id}
                    </Table.Cell>
                    <Table.Cell>{n.name}</Table.Cell>
                    <Table.Cell>{n.subnet_cidr}</Table.Cell>
                    <Table.Cell>{new Date(n.created_at).toLocaleString()}</Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
            {networks.length === 0 && (
              <div className="p-8 text-center">
                <p className="text-gray-500 dark:text-gray-400 mb-2">No networks yet.</p>
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                  Create a network to define your overlay subnet. Configure per-group firewall rules on the Groups page.
                </p>
                <Button color="blue" onClick={() => setShowForm(true)} data-onboarding-target="networks-create-button">
                  <HiPlus className="mr-2 h-5 w-5" />
                  Add your first network
                </Button>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
