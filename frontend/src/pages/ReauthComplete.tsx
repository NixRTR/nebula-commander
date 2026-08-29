import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Card, Button } from "flowbite-react";
import {
  createReauthChallenge,
  deleteNetwork,
  deleteNode,
  deleteUser,
  exchangeAuthCode,
  revokeNodeCertificate,
} from "../api/client";

const API_BASE = "/api";

const PENDING_ACTION_KEY = "nebula_commander_pending_reauth_action";

export type PendingReauthAction =
  | { kind: "network-delete"; networkId: number; networkName: string }
  | { kind: "node-delete"; nodeId: number; hostname: string }
  | { kind: "node-revoke-cert"; nodeId: number; hostname: string }
  | { kind: "user-delete"; userId: number; email: string };

// eslint-disable-next-line react-refresh/only-export-components
export function getPendingReauthAction(): PendingReauthAction | null {
  try {
    const raw = sessionStorage.getItem(PENDING_ACTION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PendingReauthAction;
  } catch {
    return null;
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function setPendingReauthAction(data: PendingReauthAction): void {
  sessionStorage.setItem(PENDING_ACTION_KEY, JSON.stringify(data));
}

// eslint-disable-next-line react-refresh/only-export-components
export function clearPendingReauthAction(): void {
  sessionStorage.removeItem(PENDING_ACTION_KEY);
}

/** Create a reauth challenge, stash the pending action, and redirect to the IdP for step-up auth. */
// eslint-disable-next-line react-refresh/only-export-components
export async function startReauthFlow(action: PendingReauthAction): Promise<void> {
  const { reauth_url } = await createReauthChallenge();
  setPendingReauthAction(action);
  window.location.href = reauth_url;
}

const destinationFor = (kind: PendingReauthAction["kind"]): string => {
  switch (kind) {
    case "network-delete":
      return "/networks";
    case "node-delete":
    case "node-revoke-cert":
      return "/nodes";
    case "user-delete":
      return "/users";
  }
};

async function runPendingAction(pending: PendingReauthAction, reauthToken: string): Promise<void> {
  switch (pending.kind) {
    case "network-delete":
      await deleteNetwork(pending.networkId, reauthToken, pending.networkName);
      return;
    case "node-delete":
      await deleteNode(pending.nodeId, reauthToken, pending.hostname);
      return;
    case "node-revoke-cert":
      await revokeNodeCertificate(pending.nodeId, reauthToken, pending.hostname);
      return;
    case "user-delete":
      await deleteUser(pending.userId, reauthToken, pending.email);
      return;
  }
}

export function ReauthComplete() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const code = searchParams.get("code");
  const challenge = searchParams.get("challenge");
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Missing code (and not a challenge redirect) – show error without setState in effect
  const missingCodeError = !code && !challenge;

  useEffect(() => {
    if (challenge && !code) {
      // Dev mode: backend sent us here with challenge; redirect to backend to get the exchange code
      window.location.href = `${API_BASE}/auth/reauth/callback?challenge=${encodeURIComponent(challenge)}`;
      return;
    }

    if (!code) return;

    const pending = getPendingReauthAction();
    if (!pending) {
      clearPendingReauthAction();
      navigate("/", { replace: true });
      return;
    }

    exchangeAuthCode(code)
      .then((reauthToken) => runPendingAction(pending, reauthToken))
      .then(() => {
        clearPendingReauthAction();
        setStatus("success");
        navigate(destinationFor(pending.kind), { replace: true });
      })
      .catch((e: Error) => {
        setStatus("error");
        setErrorMessage(e.message || "Failed to complete the action.");
      });
  }, [code, challenge, navigate]);

  if (missingCodeError || status === "error") {
    return (
      <div className="flex justify-center items-center min-h-[50vh]">
        <Card className="max-w-md">
          <h2 className="text-xl font-semibold text-red-600 dark:text-red-400">
            Error
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            {missingCodeError ? "Missing reauthentication code." : errorMessage}
          </p>
          <Button color="gray" onClick={() => navigate("/")}>
            Back
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
