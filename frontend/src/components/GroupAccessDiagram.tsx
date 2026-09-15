import { useEffect, useMemo, useState } from "react";
import { Card } from "flowbite-react";
import { listGroupFirewall } from "../api/client";
import type { GroupFirewallConfig } from "../types/networks";
import type { Node } from "../types/nodes";
import { useTheme } from "../contexts/ThemeContext";
import { contrastTextColor } from "../theme/tokens";

interface Props {
  networkId: number;
  /** Already-fetched nodes for this network - used to include groups that have
   * nodes assigned but no firewall row of their own yet. */
  nodes: Node[];
}

interface Point {
  name: string;
  x: number;
  y: number;
  open: boolean;
}

interface Edge {
  from: string;
  to: string;
  label: string;
}

const SIZE = 480;
const CENTER = SIZE / 2;
const NODE_RADIUS = 30;
const CURVE_OFFSET = 18;

function layout(names: string[]): Point[] {
  const radius = Math.min(CENTER - NODE_RADIUS - 20, 70 + names.length * 16);
  return names.map((name, i) => {
    const angle = (2 * Math.PI * i) / names.length - Math.PI / 2;
    return {
      name,
      x: CENTER + (names.length === 1 ? 0 : radius * Math.cos(angle)),
      y: CENTER + (names.length === 1 ? 0 : radius * Math.sin(angle)),
      open: false, // filled in by caller
    };
  });
}

function pullBack(from: Point, to: Point, dist: number): { x: number; y: number } {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  return { x: to.x - (dx / len) * dist, y: to.y - (dy / len) * dist };
}

function edgePath(p1: Point, p2: Point): { d: string; midX: number; midY: number } {
  const start = pullBack(p2, p1, NODE_RADIUS);
  const end = pullBack(p1, p2, NODE_RADIUS + 8);
  const mx = (start.x + end.x) / 2;
  const my = (start.y + end.y) / 2;
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const cx = mx + nx * CURVE_OFFSET;
  const cy = my + ny * CURVE_OFFSET;
  return { d: `M ${start.x} ${start.y} Q ${cx} ${cy} ${end.x} ${end.y}`, midX: cx, midY: cy };
}

export function GroupAccessDiagram({ networkId, nodes }: Props) {
  const { resolve } = useTheme();
  const [groups, setGroups] = useState<GroupFirewallConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const id = setTimeout(() => {
      setLoading(true);
      listGroupFirewall(networkId)
        .then((g) => {
          if (!cancelled) setGroups(g);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load group firewall rules");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [networkId]);

  const { points, edges } = useMemo(() => {
    const names = new Set<string>();
    const byGroup = new Map(groups.map((g) => [g.group_name, g]));
    groups.forEach((g) => {
      names.add(g.group_name);
      (g.inbound_rules || []).forEach((r) => {
        if (r.allowed_group) names.add(r.allowed_group);
      });
    });
    nodes.forEach((n) => {
      if (n.groups && n.groups[0]) names.add(n.groups[0]);
    });

    const sortedNames = Array.from(names).sort((a, b) => a.localeCompare(b));
    const pts = layout(sortedNames).map((p) => {
      const g = byGroup.get(p.name);
      const open = !g || !g.inbound_rules || g.inbound_rules.length === 0;
      return { ...p, open };
    });

    // Merge same (from, to) pairs across multiple rules into one edge.
    const edgeMap = new Map<string, { from: string; to: string; labels: string[] }>();
    groups.forEach((g) => {
      (g.inbound_rules || []).forEach((r) => {
        if (!r.allowed_group || r.allowed_group === g.group_name) return;
        const key = `${r.allowed_group}->${g.group_name}`;
        const label = `${r.protocol} ${r.port_range}`;
        const existing = edgeMap.get(key);
        if (existing) {
          existing.labels.push(label);
        } else {
          edgeMap.set(key, { from: r.allowed_group, to: g.group_name, labels: [label] });
        }
      });
    });
    const edgs: Edge[] = Array.from(edgeMap.values()).map((e) => ({
      from: e.from,
      to: e.to,
      label: e.labels.join(", "),
    }));

    return { points: pts, edges: edgs };
  }, [groups, nodes]);

  if (loading) {
    return (
      <Card>
        <p className="text-gray-600 dark:text-gray-400">Loading group access...</p>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <p className="text-red-600 dark:text-red-400">{error}</p>
      </Card>
    );
  }

  if (points.length === 0) {
    return (
      <Card>
        <p className="text-gray-500 dark:text-gray-400">
          No groups configured yet. Assign a group to a node, or add firewall rules on the Groups page.
        </p>
      </Card>
    );
  }

  const byName = new Map(points.map((p) => [p.name, p]));

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-4 mb-3 text-xs text-gray-500 dark:text-gray-400">
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: resolve("group.restricted") }} />
          Restricted (inbound rules configured)
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded-full border-2 border-dashed"
            style={{ borderColor: resolve("group.open") }}
          />
          Open (any group can reach it)
        </div>
        <div className="flex items-center gap-1.5">
          <svg width="16" height="8" style={{ color: resolve("diagram.edge") }}><line x1="0" y1="4" x2="16" y2="4" stroke="currentColor" strokeWidth="2" markerEnd="url(#legend-arrow)" /></svg>
          A can reach B
        </div>
      </div>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full max-w-lg mx-auto" style={{ color: resolve("diagram.edge") }}>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
          </marker>
          <marker id="legend-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
          </marker>
        </defs>
        {edges.map((e) => {
          const from = byName.get(e.from);
          const to = byName.get(e.to);
          if (!from || !to) return null;
          const { d } = edgePath(from, to);
          return (
            <path key={`${e.from}->${e.to}`} d={d} fill="none" stroke="currentColor" strokeWidth={1.5} markerEnd="url(#arrow)" opacity={0.7}>
              <title>{`${e.from} → ${e.to}: ${e.label}`}</title>
            </path>
          );
        })}
        {points.map((p) => (
          <g key={p.name}>
            <circle
              cx={p.x}
              cy={p.y}
              r={NODE_RADIUS}
              fill={p.open ? "transparent" : resolve("group.restricted")}
              stroke={p.open ? resolve("group.open") : resolve("group.restricted")}
              strokeWidth={2}
              strokeDasharray={p.open ? "4 3" : undefined}
            >
              <title>{p.name}{p.open ? " (open - any group can reach it)" : ""}</title>
            </circle>
            <text
              x={p.x}
              y={p.y}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={11}
              fill={p.open ? "currentColor" : contrastTextColor(resolve("group.restricted"))}
              className="pointer-events-none select-none"
            >
              {p.name.length > 10 ? `${p.name.slice(0, 9)}…` : p.name}
            </text>
          </g>
        ))}
      </svg>
    </Card>
  );
}
