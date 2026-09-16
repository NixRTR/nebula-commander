import { useEffect, useState } from "react";
import { getVersionCheck, type VersionCheck } from "../api/client";

/** Fetches the update-check result once. Best-effort: silently returns null on
 * failure (e.g. offline/air-gapped deployments, or the check disabled server-side). */
export function useVersionCheck(): VersionCheck | null {
  const [data, setData] = useState<VersionCheck | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVersionCheck()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        // Best-effort only; leave data as null.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return data;
}
