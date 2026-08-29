import type { Node } from "../types/nodes";

/** Fallback assumed interval for nodes that haven't reported their real one yet (older ncclient, or never checked in). */
const DEFAULT_INTERVAL_SECONDS = 60;

export type EnrollmentState =
  | { type: "enroll" }
  | { type: "re-enroll" }
  | { type: "active" }
  | { type: "idle"; severity: "success" | "warning" }
  | { type: "offline" };

/**
 * The backend sends naive UTC timestamps with no "Z"/offset suffix. Without a
 * timezone indicator, `new Date(...)` parses the string as local time, which
 * silently corrupts every "time since" comparison by the viewer's UTC offset.
 */
function parseUtcDate(iso: string): Date {
  const hasTimezone = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`);
}

export function getEnrollmentState(node: Node): EnrollmentState {
  if (!node.first_polled_at) {
    return { type: "enroll" };
  }
  if (!node.last_seen) {
    return { type: "re-enroll" };
  }
  const lastSeenDate = parseUtcDate(node.last_seen);
  const elapsedSeconds = (Date.now() - lastSeenDate.getTime()) / 1000;
  const interval = node.checkin_interval_seconds ?? DEFAULT_INTERVAL_SECONDS;

  if (elapsedSeconds > 24 * 60 * 60) {
    return { type: "re-enroll" };
  }
  if (elapsedSeconds >= 10 * interval) {
    return { type: "offline" };
  }
  if (elapsedSeconds <= interval) {
    return { type: "active" };
  }
  if (elapsedSeconds <= 3 * interval) {
    return { type: "idle", severity: "success" };
  }
  return { type: "idle", severity: "warning" };
}

export function isNodeActive(node: Node): boolean {
  return getEnrollmentState(node).type === "active";
}

export function isNodeOffline(node: Node): boolean {
  return getEnrollmentState(node).type === "offline";
}
