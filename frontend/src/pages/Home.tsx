import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Badge } from "flowbite-react";
import { apiFetch, listNetworks, listNodes } from "../api/client";
import { useOnboarding } from "../contexts/OnboardingContext";
import { GettingStarted } from "./GettingStarted";
import { NetworkStatus } from "./NetworkStatus";
import type { Network } from "../types/networks";
import type { Node } from "../types/nodes";

interface Health {
  status: string;
  debug?: boolean;
}

export function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<
    { status: "loading" } | { status: "error" } | { status: "ok"; networks: Network[]; nodes: Node[] }
  >({ status: "loading" });
  const navigate = useNavigate();
  const { restart } = useOnboarding();

  useEffect(() => {
    apiFetch<Health>("/health")
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    Promise.all([listNetworks(), listNodes()])
      .then(([networks, nodes]) => setOverview({ status: "ok", networks, nodes }))
      .catch(() => setOverview({ status: "error" }));
  }, []);

  const handleRestartOnboarding = () => {
    restart();
    navigate("/");
  };

  const hasEnrolledNode = overview.status === "ok" && overview.nodes.some((n) => !!n.first_polled_at);
  const showGettingStarted =
    overview.status !== "ok" ||
    overview.networks.length === 0 ||
    overview.nodes.length === 0 ||
    !hasEnrolledNode;

  const statusBadgeRow = (health || error) && (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      {error && <Badge color="failure">API Error</Badge>}
      {health && !error && <Badge color="success">API {health.status}</Badge>}
      {health?.debug === true && (
        <button
          type="button"
          onClick={handleRestartOnboarding}
          className="text-sm text-purple-600 dark:text-purple-400 hover:underline"
        >
          Restart onboarding
        </button>
      )}
    </div>
  );

  if (overview.status === "loading") {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-6">Home</h1>
        {statusBadgeRow}
        <Card>
          <p className="text-gray-600 dark:text-gray-400">Loading&hellip;</p>
        </Card>
      </div>
    );
  }

  if (showGettingStarted) {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-6">Home</h1>
        {statusBadgeRow}
        <GettingStarted />
      </div>
    );
  }

  return (
    <div>
      {statusBadgeRow}
      <NetworkStatus networks={overview.networks} nodes={overview.nodes} />
    </div>
  );
}
