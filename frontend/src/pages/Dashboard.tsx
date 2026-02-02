import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, Badge, Button } from "flowbite-react";
import { HiShieldCheck } from "react-icons/hi";
import { apiFetch, listNetworks } from "../api/client";

interface Health {
  status: string;
}

export function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [networkCount, setNetworkCount] = useState<number | null>(null);

  useEffect(() => {
    apiFetch<Health>("/health")
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    listNetworks()
      .then((list) => setNetworkCount(list.length))
      .catch(() => setNetworkCount(0));
  }, []);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card>
          <h3 className="text-lg font-semibold mb-2">API Status</h3>
          {error && (
            <Badge color="failure">Error</Badge>
          )}
          {health && (
            <Badge color="success">{health.status}</Badge>
          )}
          {!health && !error && (
            <Badge color="warning">Loading...</Badge>
          )}
        </Card>

        <Card>
          <h3 className="text-lg font-semibold mb-2">Networks</h3>
          <div className="text-3xl font-bold">{networkCount ?? "—"}</div>
          <p className="text-sm text-gray-600 dark:text-gray-400">Total networks</p>
        </Card>

        <Card>
          <h3 className="text-lg font-semibold mb-2">Nodes</h3>
          <div className="text-3xl font-bold">0</div>
          <p className="text-sm text-gray-600 dark:text-gray-400">Active nodes</p>
        </Card>

        <Card>
          <h3 className="text-lg font-semibold mb-2">Certificates</h3>
          <div className="text-3xl font-bold">0</div>
          <p className="text-sm text-gray-600 dark:text-gray-400">Issued certificates</p>
        </Card>
      </div>

      {/* Next step: Generate certificates (shown when user has at least one network) */}
      {networkCount != null && networkCount > 0 && (
        <Card className="mb-6 border-2 border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-gray-800/50">
          <h2 className="text-xl font-bold mb-2 flex items-center gap-2">
            <HiShieldCheck className="w-6 h-6 text-blue-600 dark:text-blue-400" />
            Next: Generate certificates for your node
          </h2>
          <p className="text-gray-700 dark:text-gray-300 mb-4">
            You have a network. To join a node, generate a keypair on the node, then sign the certificate here.
          </p>
          <Button as={Link} to="/certificates" color="blue" size="lg">
            Generate certificates
          </Button>
        </Card>
      )}

      {/* Welcome Card */}
      <Card>
        <h2 className="text-2xl font-bold mb-4">Welcome to Nebula Commander</h2>
        <p className="text-gray-700 dark:text-gray-300 mb-4">
          Nebula Commander is a self-hosted control plane for managing Nebula overlay networks.
        </p>
        <div className="space-y-2">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            <strong>Getting Started:</strong>
          </p>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-600 dark:text-gray-400">
            <li><Link to="/networks" className="text-blue-600 dark:text-blue-400 hover:underline">Create a network</Link> to get started</li>
            <li><Link to="/certificates" className="text-blue-600 dark:text-blue-400 hover:underline">Generate certificates</Link> for your nodes</li>
            <li>Monitor node status and connectivity</li>
          </ul>
        </div>
      </Card>
    </div>
  );
}
