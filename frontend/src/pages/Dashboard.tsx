import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, Badge, Button } from "flowbite-react";
import { HiShieldCheck, HiKey } from "react-icons/hi";
import { apiFetch, listNetworks, listNodes } from "../api/client";

interface Health {
  status: string;
}

export function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [networkCount, setNetworkCount] = useState<number | null>(null);
  const [nodeCount, setNodeCount] = useState<number | null>(null);
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

  useEffect(() => {
    listNodes()
      .then((list) => setNodeCount(list.length))
      .catch(() => setNodeCount(0));
  }, []);

  const hasNetworks = (networkCount ?? 0) > 0;
  const hasNodes = (nodeCount ?? 0) > 0;

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
          <div className="text-3xl font-bold">{nodeCount ?? "—"}</div>
          <p className="text-sm text-gray-600 dark:text-gray-400">Enrolled nodes</p>
        </Card>

      </div>

      {/* Onboarding: next step cards */}
      {networkCount != null && (
        <div className="space-y-4 mb-6">
          {!hasNetworks && (
            <Card className="border-2 border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-gray-800/50">
              <h2 className="text-xl font-bold mb-2 flex items-center gap-2">
                <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">1</span>
                Create your first network
              </h2>
              <p className="text-gray-700 dark:text-gray-300 mb-4">
                A network defines the overlay (e.g. subnet). Create one to get started.
              </p>
              <Button as={Link} to="/networks" color="blue" size="lg">
                Go to Networks
              </Button>
            </Card>
          )}

          {hasNetworks && !hasNodes && (
            <Card className="border-2 border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-gray-800/50">
              <h2 className="text-xl font-bold mb-2 flex items-center gap-2">
                <HiKey className="w-6 h-6 text-blue-600 dark:text-blue-400" />
                <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">2</span>
                Create and enroll a node
              </h2>
              <p className="text-gray-700 dark:text-gray-300 mb-4">
                On the Nodes page, create a node and use the enrollment code with <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code> on the device to join.
              </p>
              <Button as={Link} to="/nodes" color="blue" size="lg">
                Go to Nodes
              </Button>
            </Card>
          )}

          {hasNetworks && hasNodes && (
            <Card className="border-2 border-green-200 dark:border-green-800 bg-green-50/50 dark:bg-gray-800/50">
              <h2 className="text-xl font-bold mb-2 flex items-center gap-2">
                <HiShieldCheck className="w-6 h-6 text-green-600 dark:text-green-400" />
                You&apos;re all set
              </h2>
              <p className="text-gray-700 dark:text-gray-300">
                You have networks and enrolled nodes. Use <Link to="/nodes" className="text-blue-600 dark:text-blue-400 hover:underline">Nodes</Link> to manage devices and download configs.
              </p>
            </Card>
          )}
        </div>
      )}

      {/* Welcome Card */}
      <Card>
        <h2 className="text-2xl font-bold mb-4">Welcome to Nebula Commander</h2>
        <p className="text-gray-700 dark:text-gray-300 mb-4">
          Nebula Commander is a self-hosted control plane for managing Nebula overlay networks.
        </p>
        <div className="space-y-2">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            <strong>Getting started:</strong>
          </p>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-600 dark:text-gray-400">
            <li><Link to="/networks" className="text-blue-600 dark:text-blue-400 hover:underline">Create a network</Link> to define your overlay</li>
            <li><Link to="/nodes" className="text-blue-600 dark:text-blue-400 hover:underline">Create and enroll nodes</Link> with <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code> and monitor status</li>
          </ul>
        </div>
      </Card>
    </div>
  );
}
