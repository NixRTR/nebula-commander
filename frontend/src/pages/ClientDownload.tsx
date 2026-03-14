import { Card, Tabs, type TabsRef } from "flowbite-react";
import { useEffect, useRef } from "react";
import { HiDownload } from "react-icons/hi";

const DOWNLOADS = [
  { name: "Linux (x86_64)", file: "ncclient-linux-amd64", platform: "linux" },
  { name: "Linux (ARM64)", file: "ncclient-linux-arm64", platform: "linux" },
  { name: "Windows (x86_64)", file: "ncclient-windows-amd64.exe", platform: "windows" },
  { name: "macOS (Intel)", file: "ncclient-macos-amd64", platform: "macos" },
  { name: "macOS (Apple Silicon)", file: "ncclient-macos-arm64", platform: "macos" },
] as const;

const TRAY_DOWNLOADS = [
  { name: "Windows Tray App (x86_64)", file: "ncclient-tray-windows-amd64.exe", platform: "windows" },
] as const;

type PlatformTab = "docker" | "linux" | "windows" | "macos" | "mobile";

const TAB_ORDER: PlatformTab[] = ["docker", "linux", "windows", "macos", "mobile"];

function getDefaultPlatformTab(): PlatformTab {
  if (typeof navigator === "undefined") return "linux";
  const ua = navigator.userAgent.toLowerCase();
  const platform = (navigator as { platform?: string }).platform?.toLowerCase() ?? "";
  if (ua.includes("win") || platform.includes("win")) return "windows";
  if (ua.includes("mac") || platform.includes("mac")) return "macos";
  if (ua.includes("linux") || platform.includes("linux")) return "linux";
  return "linux";
}

const DOCKER_COMPOSE_SNIPPET = `services:
  ncclient:
    image: ghcr.io/nixrtr/nebula-commander-ncclient:latest
    network_mode: host
    restart: unless-stopped
    environment:
      NEBULA_COMMANDER_SERVER: "https://<YOUR_SERVER>"
      # One-time enrollment code from the Nodes page
      ENROLL_CODE: "<ENROLL_CODE>"
      # Data directory inside the container
      NEBULA_OUTPUT_DIR: "/data/nebula"
      NEBULA_DEVICE_TOKEN_FILE: "/data/nebula-commander/token"
      # Optional: enable DNS on lighthouses only (network is derived from device token)
      # SERVE_DNS: "true"
    volumes:
      - ncclient-data:/data

volumes:
  ncclient-data:
    driver: local`;

const NEBULA_GOOGLE_PLAY_URL = "https://play.google.com/store/apps/details?id=net.defined.mobile_nebula";
const NEBULA_APP_STORE_URL = "https://apps.apple.com/us/app/mobile-nebula/id1509587936";
// Official store badge assets (Google and Apple guidelines)
const GOOGLE_PLAY_BADGE_URL = "https://play.google.com/intl/en_us/badges/static/images/badges/en_badge_web_generic.png";
// Apple badge: official design (SVG from Apple marketing assets / Wikimedia)
const APP_STORE_BADGE_URL = "https://upload.wikimedia.org/wikipedia/commons/3/3c/Download_on_the_App_Store_Badge.svg";

export function ClientDownload() {
  const tabsRef = useRef<TabsRef>(null);
  const defaultTabIndex = TAB_ORDER.indexOf(getDefaultPlatformTab());

  useEffect(() => {
    tabsRef.current?.setActiveTab(defaultTabIndex);
  }, [defaultTabIndex]);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Experimental Client Download</h1>
      <p className="text-gray-600 dark:text-gray-400 mb-6">
        ncclient is an experimental client application for enrolling devices with Nebula Commander and automatically pulling down Nebula config and certificates. It is a work in progress and not yet recommended for production use, but if you want to try it out or provide feedback, choose your platform below.
      </p>
      <p className="text-gray-600 dark:text-gray-400 mb-6">
        Get the enrollment code from the Nodes page (Enroll button). You can run ncclient as a native binary, via Python, or inside a Docker container.
      </p>

      <Tabs
        aria-label="Client downloads by platform"
        style="underline"
        ref={tabsRef}
      >
        <Tabs.Item title="Docker">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Run ncclient in Docker</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              Use the published image <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ghcr.io/nixrtr/nebula-commander-ncclient:latest</code> to enroll and run a Nebula client inside a container. Replace <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">&lt;YOUR_SERVER&gt;</code> with your Nebula Commander URL and <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">&lt;ENROLL_CODE&gt;</code> with the code from the Nodes page.
            </p>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              Example <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">docker-compose.yml</code>:
            </p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-xs overflow-x-auto mb-4">
              {DOCKER_COMPOSE_SNIPPET}
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              On first start, the container uses <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ENROLL_CODE</code> to enroll and write the device token under <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/data/nebula-commander/token</code>. On subsequent starts, the existing token is reused. If you set <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">SERVE_DNS: "true"</code>, the container will serve DNS when the node is a lighthouse (network is determined from the device token).
            </p>
          </Card>
        </Tabs.Item>

        <Tabs.Item title="Linux">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Downloads</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
              Pre-built command-line executables — no Python required.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              {DOWNLOADS.filter((d) => d.platform === "linux").map((d) => (
                <a
                  key={d.file}
                  href={`/downloads/${d.file}`}
                  download={d.file}
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-900 dark:text-white transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>{d.name}</span>
                </a>
              ))}
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              After download run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">chmod +x ncclient-*</code> then move to <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/usr/local/bin</code> or your PATH.
            </p>

            <h2 className="text-xl font-bold mb-4">Install (Python)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Requires Python 3.10+. From PyPI:</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              pip install nebula-commander
            </pre>

            <h2 className="text-xl font-bold mb-4">Enroll (one-time)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Get the enrollment code from Nebula Commander: Nodes → Enroll. Then run on the device:</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              ncclient --server https://&lt;YOUR_SERVER&gt;:&lt;PORT&gt; enroll --code XXXXXXXX
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Token is saved to <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">~/.config/nebula-commander/token</code> (or <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/etc/nebula-commander/token</code> when run as root).</p>

            <h2 className="text-xl font-bold mb-4">Run (daemon)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Creating the Nebula TUN device requires root on Linux. Run:</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              sudo ncclient --server https://&lt;YOUR_SERVER&gt;:&lt;PORT&gt; run
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Config and certs are written to <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/etc/nebula</code> by default. Use <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">--output-dir</code> to override.</p>

            <h2 className="text-xl font-bold mb-4">Run at startup (systemd)</h2>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              sudo ncclient install
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400">Prompts for server URL and installs the systemd service. Enroll first if you have not already.</p>
          </Card>
        </Tabs.Item>

        <Tabs.Item title="Windows">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Downloads</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
              CLI binary, optional tray app, or single MSI installer.
            </p>
            <div className="space-y-4 mb-6">
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">ncclient (command-line)</p>
                <a
                  href={`/downloads/${DOWNLOADS.find((d) => d.platform === "windows")?.file}`}
                  download
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-900 dark:text-white transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>ncclient-windows-amd64.exe</span>
                </a>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Windows Tray App</p>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                  System-tray app with GUI for enrollment, settings, and auto-start at login. Includes bundled Nebula binary.
                </p>
                {TRAY_DOWNLOADS.map((d) => (
                  <a
                    key={d.file}
                    href={`/downloads/${d.file}`}
                    download={d.file}
                    className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-blue-100 dark:bg-blue-900 hover:bg-blue-200 dark:hover:bg-blue-800 text-gray-900 dark:text-white transition-colors"
                  >
                    <HiDownload className="w-5 h-5 shrink-0" />
                    <span>{d.name}</span>
                  </a>
                ))}
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Or use the <a href="/downloads/NebulaCommander-windows-amd64.msi" className="text-purple-600 dark:text-purple-400 hover:underline">MSI installer</a> to install both ncclient and the tray app and add them to PATH.
                </p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">MSI installer (CLI + Tray)</p>
                <a
                  href="/downloads/NebulaCommander-windows-amd64.msi"
                  download="NebulaCommander-windows-amd64.msi"
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-green-100 dark:bg-green-900 hover:bg-green-200 dark:hover:bg-green-800 text-gray-900 dark:text-white transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>Download NebulaCommander-windows-amd64.msi</span>
                </a>
              </div>
            </div>

            <h2 className="text-xl font-bold mb-4">Install (Python)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Requires Python 3.10+. From PyPI:</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              pip install nebula-commander
            </pre>

            <h2 className="text-xl font-bold mb-4">Enroll (one-time)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Get the enrollment code from Nebula Commander: Nodes → Enroll. Then run in PowerShell or Command Prompt:</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              ncclient --server https://&lt;YOUR_SERVER&gt;:&lt;PORT&gt; enroll --code XXXXXXXX
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Token is saved under <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">%USERPROFILE%\.config\nebula-commander\token</code>.</p>

            <h2 className="text-xl font-bold mb-4">Run (daemon)</h2>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              ncclient --server https://&lt;YOUR_SERVER&gt;:&lt;PORT&gt; run
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Default output dir for config and certs is <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">%USERPROFILE%\.nebula</code>. Override with <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">--output-dir</code> (e.g. <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">C:\ProgramData\Nebula</code> if running as Administrator).</p>
            <p className="text-sm text-gray-600 dark:text-gray-400">Run ncclient in a terminal or install as a Windows service (e.g. Task Scheduler or NSSM) so it keeps running.</p>
          </Card>
        </Tabs.Item>

        <Tabs.Item title="MacOS">
          <Card className="mt-4">
            <div className="p-3 bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg mb-4">
              <p className="text-sm font-medium text-amber-800 dark:text-amber-200">MacOS support is untested.</p>
            </div>

            <h2 className="text-xl font-bold mb-4">Downloads</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
              Pre-built command-line executables — no Python required.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              {DOWNLOADS.filter((d) => d.platform === "macos").map((d) => (
                <a
                  key={d.file}
                  href={`/downloads/${d.file}`}
                  download={d.file}
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-900 dark:text-white transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>{d.name}</span>
                </a>
              ))}
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              After download run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">chmod +x ncclient-*</code> then move to <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/usr/local/bin</code> or your PATH.
            </p>

            <h2 className="text-xl font-bold mb-4">Install (Python)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Requires Python 3.10+. From PyPI (Intel and Apple Silicon):</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              pip install nebula-commander
            </pre>

            <h2 className="text-xl font-bold mb-4">Enroll (one-time)</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-2">Get the enrollment code from Nebula Commander: Nodes → Enroll. Then run:</p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              ncclient --server https://&lt;YOUR_SERVER&gt;:&lt;PORT&gt; enroll --code XXXXXXXX
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Token is stored at <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">~/.config/nebula-commander/token</code> (or <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/etc/nebula-commander/token</code> when run as root).</p>

            <h2 className="text-xl font-bold mb-4">Run (daemon)</h2>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">
              ncclient --server https://&lt;YOUR_SERVER&gt;:&lt;PORT&gt; run
            </pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">Default output dir is <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/etc/nebula</code>. If you run as a normal user, use <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">--output-dir ~/.nebula</code>. After <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">brew install nebula</code>, nebula is usually on PATH; use <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">--nebula /opt/homebrew/bin/nebula</code> (Apple Silicon) or <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">--nebula /usr/local/bin/nebula</code> (Intel) only if needed.</p>
            <p className="text-sm text-gray-600 dark:text-gray-400">To run in the background, use launchd (LaunchAgent in <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">~/Library/LaunchAgents</code> or LaunchDaemon in <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/Library/LaunchDaemons</code>).</p>
          </Card>
        </Tabs.Item>

        <Tabs.Item title="Mobile">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Nebula mobile client</h2>
            <p className="text-gray-700 dark:text-gray-300 mb-4">
              ncclient is not available on mobile. Use the official Nebula app (by Defined Networking) and add certificates from Nebula Commander.
            </p>
            <div className="flex flex-wrap items-center gap-4 mb-6">
              <a
                href={NEBULA_GOOGLE_PLAY_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="focus:outline-none focus:ring-2 focus:ring-purple-500 rounded inline-block h-[52px] w-[180px]"
                aria-label="Get Nebula on Google Play"
              >
                <img
                  src={GOOGLE_PLAY_BADGE_URL}
                  alt="Get it on Google Play"
                  className="h-full w-full object-contain object-left"
                />
              </a>
              <a
                href={NEBULA_APP_STORE_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="focus:outline-none focus:ring-2 focus:ring-purple-500 rounded inline-block h-[52px] w-[180px]"
                aria-label="Download Nebula on the App Store"
              >
                <img
                  src={APP_STORE_BADGE_URL}
                  alt="Download on the App Store"
                  className="h-full w-full object-contain object-left"
                />
              </a>
            </div>

            <h3 className="text-lg font-bold mb-2">Using certificates</h3>
            <p className="text-gray-700 dark:text-gray-300 mb-4">
              Create or sign the node in Nebula Commander (Nodes page), then obtain the certificate bundle (ca.crt, host certificate, host key). Import or paste these into the Nebula mobile app (iOS/Android) following that app’s instructions. The mobile app does not use ncclient or enrollment codes.
            </p>

            <h3 className="text-lg font-bold mb-2">Magic DNS</h3>
            <p className="text-gray-700 dark:text-gray-300">
              Magic DNS (split-horizon DNS provided by ncclient on lighthouses) does not work on mobile clients. Mobile devices will resolve names using their normal DNS (e.g. cellular or Wi‑Fi DNS).
            </p>
          </Card>
        </Tabs.Item>
      </Tabs>
    </div>
  );
}
