/**
 * Fetches /api/public-config and injects analytics scripts (Plausible, GA, custom) into document.head.
 * Runs once on mount; no auth required.
 */
import { useEffect, useRef } from "react";

interface PlausibleConfig {
  domain: string;
  scriptSrc: string;
}

interface PublicConfig {
  analytics?: {
    plausible?: PlausibleConfig | null;
    gaMeasurementId?: string | null;
    customScripts?: Array<{ src?: string; inline?: string; defer?: boolean; async?: boolean }>;
  };
}

function injectScripts(config: PublicConfig) {
  const { analytics } = config;
  if (!analytics) return;

  // Plausible: external script + inline queue
  if (analytics.plausible?.domain) {
    const { domain, scriptSrc } = analytics.plausible;
    const script = document.createElement("script");
    script.defer = true;
    script.dataset.domain = domain;
    script.src = scriptSrc;
    document.head.appendChild(script);
    const inline = document.createElement("script");
    inline.textContent =
      "window.plausible = window.plausible || function() { (window.plausible.q = window.plausible.q || []).push(arguments) }";
    document.head.appendChild(inline);
  }

  // Google Analytics (gtag)
  if (analytics.gaMeasurementId) {
    const gid = analytics.gaMeasurementId;
    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${gid}`;
    document.head.appendChild(script);
    const inline = document.createElement("script");
    inline.textContent = `
      window.dataLayer = window.dataLayer || [];
      function gtag(){ dataLayer.push(arguments); }
      gtag('js', new Date());
      gtag('config', '${gid.replace(/'/g, "\\'")}');
    `;
    document.head.appendChild(inline);
  }

  // Custom scripts
  const custom = analytics.customScripts ?? [];
  for (const item of custom) {
    if (item.src) {
      const script = document.createElement("script");
      script.src = item.src;
      if (item.defer) script.defer = true;
      if (item.async) script.async = true;
      document.head.appendChild(script);
    } else if (item.inline) {
      const script = document.createElement("script");
      script.textContent = item.inline;
      document.head.appendChild(script);
    }
  }
}

export function AnalyticsInjector() {
  const injected = useRef(false);

  useEffect(() => {
    if (injected.current) return;
    injected.current = true;

    fetch("/api/public-config", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: PublicConfig | null) => {
        if (data) injectScripts(data);
      })
      .catch(() => {});
  }, []);

  return null;
}
