import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Card, Button } from "flowbite-react";
import { deleteNetwork } from "../api/client";

const API_BASE = "/api";

const PENDING_DELETE_KEY = "nebula_commander_pending_network_delete";

export interface PendingNetworkDelete {
  networkId: number;
  networkName: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function getPendingNetworkDelete(): PendingNetworkDelete | null {
  try {
    const raw = sessionStorage.getItem(PENDING_DELETE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as PendingNetworkDelete;
    if (typeof data.networkId !== "number" || typeof data.networkName !== "string")
      return null;
    return data;
  } catch {
    return null;
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function setPendingNetworkDelete(data: PendingNetworkDelete): void {
  sessionStorage.setItem(PENDING_DELETE_KEY, JSON.stringify(data));
}

// eslint-disable-next-line react-refresh/only-export-components
export function clearPendingNetworkDelete(): void {
  sessionStorage.removeItem(PENDING_DELETE_KEY);
}

export function ReauthComplete() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token");
  const challenge = searchParams.get("challenge");
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Missing token (and not a challenge redirect) – show error without setState in effect
  const missingTokenError = !token && !challenge;

  useEffect(() => {
    if (challenge && !token) {
      // Dev mode: backend sent us here with challenge; redirect to backend to get token
      window.location.href = `${API_BASE}/auth/reauth/callback?challenge=${encodeURIComponent(challenge)}`;
      return;
    }

    if (!token) return;

    const pending = getPendingNetworkDelete();
    if (!pending) {
      clearPendingNetworkDelete();
      navigate("/networks", { replace: true });
      return;
    }

    deleteNetwork(pending.networkId, token, pending.networkName)
      .then(() => {
        clearPendingNetworkDelete();
        setStatus("success");
        navigate("/networks", { replace: true });
      })
      .catch((e: Error) => {
        setStatus("error");
        setErrorMessage(e.message || "Failed to delete network.");
      });
  }, [token, challenge, navigate]);

  if (missingTokenError || status === "error") {
    return (
      <div className="flex justify-center items-center min-h-[50vh]">
        <Card className="max-w-md">
          <h2 className="text-xl font-semibold text-red-600 dark:text-red-400">
            Error
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            {missingTokenError ? "Missing reauthentication token." : errorMessage}
          </p>
          <Button color="gray" onClick={() => navigate("/networks")}>
            Back to Networks
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex justify-center items-center min-h-[50vh]">
      <Card className="max-w-md">
        <p className="text-gray-600 dark:text-gray-400">
          Completing reauthentication...
        </p>
      </Card>
    </div>
  );
}
