import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "flowbite-react";
import { HiPlus } from "react-icons/hi";
import type { Network } from "../types/networks";
import type { Node } from "../types/nodes";
import { listGroupFirewall } from "../api/client";
import { listDNSAliases } from "../api/dns";
import { isNodeActive, isNodeOffline } from "../utils/nodeStatus";
import { usePermissions } from "../contexts/PermissionContext";

type StatState =
  | { status: "loading" }
  | { status: "ok"; count: number }
  | { status: "restricted" }
  | { status: "error" };

interface NetworkStatusProps {
  networks: Network[];
  nodes: Node[];
}

function StatusDot({ total, active, offline }: { total: number; active: number; offline: number }) {
  let color = "#9ca3af"; // gray-400: no nodes yet
  if (total > 0) {
    if (offline > 0) color = "#dc2626"; // red-600: at least one node offline
    else if (active === total) color = "#16a34a"; // green-600: fully active
    else color = "#d97706"; // amber-600: partial (idle, not yet offline)
  }
  return <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ backgroundColor: color }} />;
}

function StatCell({ state, singular, plural }: { state: StatState; singular: string; plural: string }) {
  if (state.status === "loading") {
    return <span className="text-sm text-gray-400 dark:text-gray-500">Loading&hellip;</span>;
  }
  if (state.status === "restricted") {
    return (
      <span
        className="text-sm text-gray-400 dark:text-gray-500"
        title="You don't have permission to view this on this network"
      >
        Restricted
      </span>
    );
  }
  if (state.status === "error") {
    return <span className="text-sm text-gray-400 dark:text-gray-500">&mdash;</span>;
  }
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-2xl font-bold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{state.count}</span>
      <span className="text-sm text-gray-400 dark:text-gray-500">
        {state.count === 1 ? singular : plural}
      </span>
    </div>
  );
}

export function NetworkStatus({ networks, nodes }: NetworkStatusProps) {
  const navigate = useNavigate();
  const { hasNetworkPermission } = usePermissions();
  const [dnsCounts, setDnsCounts] = useState<Record<number, StatState>>({});
  const [groupCounts, setGroupCounts] = useState<Record<number, StatState>>({});

  useEffect(() => {
    let cancelled = false;

    networks.forEach((net) => {
      if (hasNetworkPermission(net.id, "owner")) {
        setDnsCounts((m) => ({ ...m, [net.id]: { status: "loading" } }));
        listDNSAliases(net.id)
          .then((records) => {
            if (!cancelled) {
              setDnsCounts((m) => ({ ...m, [net.id]: { status: "ok", count: records.length } }));
            }
          })
          .catch(() => {
            if (!cancelled) {
              setDnsCounts((m) => ({ ...m, [net.id]: { status: "error" } }));
            }
          });
      } else {
        setDnsCounts((m) => ({ ...m, [net.id]: { status: "restricted" } }));
      }

      if (hasNetworkPermission(net.id, "can_manage_firewall")) {
        setGroupCounts((m) => ({ ...m, [net.id]: { status: "loading" } }));
        listGroupFirewall(net.id)
          .then((groups) => {
            if (!cancelled) {
              setGroupCounts((m) => ({ ...m, [net.id]: { status: "ok", count: groups.length } }));
            }
          })
          .catch(() => {
            if (!cancelled) {
              setGroupCounts((m) => ({ ...m, [net.id]: { status: "error" } }));
            }
          });
      } else {
        setGroupCounts((m) => ({ ...m, [net.id]: { status: "restricted" } }));
      }
    });

    return () => {
      cancelled = true;
    };
    // hasNetworkPermission is a fresh function reference every render; keying the
    // fetch off it would refetch on every re-render instead of only when the
    // network list changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [networks]);

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <h1 className="text-3xl font-bold">Network Status</h1>
        <Button as={Link} to="/networks" color="purple">
          <HiPlus className="mr-2 h-5 w-5" />
          Add Network
        </Button>
      </div>
      <p className="text-gray-600 dark:text-gray-400 mb-6">
        Overview of nodes, DNS records, and groups across your networks.
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {networks.map((net) => {
          const netNodes = nodes.filter((n) => n.network_id === net.id);
          const total = netNodes.length;
          const active = netNodes.filter(isNodeActive).length;
          const offline = netNodes.filter(isNodeOffline).length;
          const dnsState = dnsCounts[net.id] ?? { status: "loading" as const };
          const groupState = groupCounts[net.id] ?? { status: "loading" as const };

          return (
            <button
              key={net.id}
              type="button"
              onClick={() => navigate(`/networks/${net.id}`)}
              className="relative aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-[var(--nc-bg2-light)] dark:bg-[var(--nc-bg2-dark)] p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
            >
              <p className="font-semibold text-lg text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] truncate" title={net.name}>
                {net.name}
              </p>
              <p className="text-xs font-mono text-gray-500 dark:text-gray-400 truncate mb-3">
                {net.subnet_cidr}
              </p>

              <div className="mt-auto grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
                    <StatusDot total={total} active={active} offline={offline} />
                    Nodes
                  </div>
                  <div className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">
                    {active}/{total}
                  </div>
                  {offline > 0 && (
                    <div className="text-xs text-red-600 dark:text-red-400">{offline} offline</div>
                  )}
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">DNS Records</div>
                  <StatCell state={dnsState} singular="record" plural="records" />
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Groups</div>
                  <StatCell state={groupState} singular="group" plural="groups" />
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
