import type { Node } from "../types/nodes";

/** Fallback assumed interval for nodes that haven't reported their real one yet (older ncclient, or never checked in). */
const DEFAULT_INTERVAL_SECONDS = 60;

/**
 * Mobile nodes have no interval of their own to compare against (the interval that matters
 * is whichever lighthouse is pinging them, not something the phone reports) - a fixed
 * freshness window is used instead: a lighthouse report older than this is treated as
 * "unknown" rather than trusted as current.
 */
const MOBILE_STALE_THRESHOLD_SECONDS = 10 * 60;

export type EnrollmentState =
  | { type: "enroll" }
  | { type: "re-enroll" }
  | { type: "active" }
  | { type: "idle"; severity: "success" | "warning" }
  | { type: "offline" }
  | { type: "unknown" };

/**
 * The backend sends naive UTC timestamps with no "Z"/offset suffix. Without a
 * timezone indicator, `new Date(...)` parses the string as local time, which
 * silently corrupts every "time since" comparison by the viewer's UTC offset.
 */
function parseUtcDate(iso: string): Date {
  const hasTimezone = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`);
}

/**
 * Mobile nodes (iOS/Android via the official Mobile Nebula app) never self-report a
 * heartbeat - there is no device token or callback capability for them. Their only
 * activity signal is a lighthouse pinging their Nebula IP and reporting the result.
 */
function getMobileEnrollmentState(node: Node): EnrollmentState {
  if (!node.lighthouse_checked_at) {
    return { type: "unknown" };
  }
  const elapsedSeconds = (Date.now() - parseUtcDate(node.lighthouse_checked_at).getTime()) / 1000;
  if (elapsedSeconds > MOBILE_STALE_THRESHOLD_SECONDS) {
    return { type: "unknown" };
  }
  return node.lighthouse_reachable ? { type: "active" } : { type: "offline" };
}

export function getEnrollmentState(node: Node): EnrollmentState {
  if (node.platform !== "desktop") {
    return getMobileEnrollmentState(node);
  }
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
