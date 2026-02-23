import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, Badge } from "flowbite-react";
import { apiFetch } from "../api/client";
import { useOnboarding } from "../contexts/OnboardingContext";

interface Health {
  status: string;
  debug?: boolean;
}

export function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const { restart } = useOnboarding();

  useEffect(() => {
    apiFetch<Health>("/health")
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);

  const handleRestartOnboarding = () => {
    restart();
    navigate("/");
  };

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Home</h1>

      {/* Optional API Status and debug: Restart onboarding */}
      {(health || error) && (
        <div className="mb-6 flex flex-wrap items-center gap-3">
          {error && <Badge color="failure">API Error</Badge>}
          {health && !error && (
            <Badge color="success">API {health.status}</Badge>
          )}
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
      )}

      <div className="space-y-8">
        <Card>
          <h2 className="text-2xl font-bold mb-4">What is Nebula Commander?</h2>
          <p className="text-gray-700 dark:text-gray-300 mb-4">
            Nebula Commander is a self-hosted control plane for Nebula overlay networks.
            You create networks (defining your overlay subnet), issue certificates for
            nodes (hosts), and enroll devices using the <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code> client.
            Nebula Commander does not replace Nebula; it centralizes CA and config so
            devices can pull their config and certs and run Nebula automatically.
          </p>
        </Card>

        <Card>
          <h2 className="text-2xl font-bold mb-4">How it works</h2>
          <ol className="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300">
            <li>Create a network in Nebula Commander to define your overlay (e.g. subnet).</li>
            <li>Create nodes (hosts) and get enrollment codes from the UI.</li>
            <li>On each device, install <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code>, run enroll with the code, then run the daemon; ncclient pulls config and certs and runs Nebula.</li>
          </ol>
        </Card>

        <Card>
          <h2 className="text-2xl font-bold mb-4">Getting Started</h2>
          <ul className="list-disc list-inside space-y-2 text-gray-700 dark:text-gray-300">
            <li>
              <Link to="/networks" className="text-purple-600 dark:text-purple-400 hover:underline">
                Create a network
              </Link>{" "}
              to define your overlay subnet.
            </li>
            <li>
              <Link to="/nodes" className="text-purple-600 dark:text-purple-400 hover:underline">
                Create and enroll a node
              </Link>{" "}
              to get an enrollment code.
            </li>
            <li>
              <Link to="/client-download" className="text-purple-600 dark:text-purple-400 hover:underline">
                Install ncclient
              </Link>{" "}
              on your device (Linux, Windows, or Mac) and run enroll, then run.
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
