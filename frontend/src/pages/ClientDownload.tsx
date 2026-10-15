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

const LINUX_DEB_DOWNLOADS = [
  { name: "nebula-commander-client.deb", file: "nebula-commander-client.deb" },
  { name: "nebula-commander-service.deb", file: "nebula-commander-service.deb" },
  { name: "nebula-commander-desktop.deb", file: "nebula-commander-desktop.deb" },
] as const;

const LINUX_RPM_DOWNLOADS = [
  { name: "nebula-commander-client.rpm", file: "nebula-commander-client.rpm" },
  { name: "nebula-commander-service.rpm", file: "nebula-commander-service.rpm" },
  { name: "nebula-commander-desktop.rpm", file: "nebula-commander-desktop.rpm" },
] as const;

const LINUX_FLATPAK_FILE = "org.beardedtek.NebulaCommander.flatpak";

// Signed apt/rpm repository (GitHub Pages, rebuilt on every release by
// .github/workflows/publish-package-repo.yml via packaging/repo/build_repo.py).
const PACKAGE_REPO_URL = "https://pkgs.nebulacommander.com";

const APT_REPO_SNIPPET = `sudo apt install -y curl
sudo install -d -m 0755 /etc/apt/keyrings
sudo curl -fsSL -o /etc/apt/keyrings/nebula-commander.asc ${PACKAGE_REPO_URL}/gpg.key
sudo curl -fsSL -o /etc/apt/sources.list.d/nebula-commander.sources ${PACKAGE_REPO_URL}/deb/nebula-commander.sources
sudo apt update
sudo apt install nebula-commander-desktop nebula-commander-service`;

const DNF_REPO_SNIPPET = `sudo curl -fsSL -o /etc/yum.repos.d/nebula-commander.repo ${PACKAGE_REPO_URL}/rpm/nebula-commander.repo
sudo dnf install nebula-commander-desktop nebula-commander-service`;

// This instance's own URL, so the commands below can be pasted as-is.
const SERVER_URL = typeof window !== "undefined" ? window.location.origin : "https://<YOUR_SERVER>";

const PIP_LINUX_SNIPPET = `sudo python3 -m venv /opt/ncclient
sudo /opt/ncclient/bin/pip install nebula-commander
sudo ln -s /opt/ncclient/bin/ncclient /usr/local/bin/ncclient`;

const STANDALONE_SETUP_SNIPPET = `# 1. Enroll as root
sudo ncclient enroll --server ${SERVER_URL} --code XXXXXXXX
# 2. Install and start the service
sudo ncclient install
# 3. Check that it's running
systemctl status ncclient`;

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
    cap_add:
      - NET_ADMIN
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
        Get the enrollment code from the Nodes page (Enroll button). On Linux, the packages are the easiest way to install it; you can also run ncclient as a standalone binary, via Python, or inside a Docker container.
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
            <h2 className="text-xl font-bold mb-2">Packages (recommended)</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
              The <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code> command, a background service that runs it as root, and a
              GTK4 desktop app for enrollment, status, and subnet route/exit node selection. The app
              talks to the service over a system D-Bus API authorized via polkit. On a server without
              a desktop, install only <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">nebula-commander-service</code>.
            </p>
            <p className="text-gray-700 dark:text-gray-300 mb-4 text-sm">
              <strong>Recommended for Linux nodes other than lighthouses:</strong> install from the package
              repository at <a href={PACKAGE_REPO_URL} className="underline">pkgs.nebulacommander.com</a>.
              It's the only Linux install that can update itself: turn on automatic updates with 
              <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">sudo ncclient auto-update enable</code> (or Settings → Updates in the app), and the
              client upgrades during a daily window. The .deb and .rpm files downloaded directly further down can't.
              For lighthouses, see the Docker tab.
            </p>
            <div className="space-y-4 mb-6">
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Package repository (recommended)</p>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Add the signed repository once and updates arrive with your normal system updates (amd64 and arm64).
                  Debian/Ubuntu:
                </p>
                <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mt-2">{APT_REPO_SNIPPET}</pre>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">Fedora/RHEL:</p>
                <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mt-2">{DNF_REPO_SNIPPET}</pre>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  openSUSE: <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">sudo zypper addrepo {PACKAGE_REPO_URL}/rpm/nebula-commander.repo</code>, then install the same packages.
                  Or download the packages directly:
                </p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">.deb (Debian/Ubuntu and derivatives)</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {LINUX_DEB_DOWNLOADS.map((d) => (
                    <a
                      key={d.file}
                      href={`/downloads/${d.file}`}
                      download={d.file}
                      className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-blue-100 dark:bg-blue-900 hover:bg-blue-200 dark:hover:bg-blue-800 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
                    >
                      <HiDownload className="w-5 h-5 shrink-0" />
                      <span className="text-sm">{d.name}</span>
                    </a>
                  ))}
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Install all three together (apt resolves the dependency order):
                </p>
                <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mt-2">
                  sudo apt install ./nebula-commander-client.deb ./nebula-commander-service.deb ./nebula-commander-desktop.deb
                </pre>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">.rpm (Fedora/RHEL/openSUSE and derivatives)</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {LINUX_RPM_DOWNLOADS.map((d) => (
                    <a
                      key={d.file}
                      href={`/downloads/${d.file}`}
                      download={d.file}
                      className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-blue-100 dark:bg-blue-900 hover:bg-blue-200 dark:hover:bg-blue-800 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
                    >
                      <HiDownload className="w-5 h-5 shrink-0" />
                      <span className="text-sm">{d.name}</span>
                    </a>
                  ))}
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Install all three together (dnf resolves the dependency order):
                </p>
                <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mt-2">
                  sudo dnf install ./nebula-commander-client.rpm ./nebula-commander-service.rpm ./nebula-commander-desktop.rpm
                </pre>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Or with <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">zypper</code> on openSUSE: <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">sudo zypper install ./nebula-commander-*.rpm</code>
                </p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Flatpak</p>
                <a
                  href={`/downloads/${LINUX_FLATPAK_FILE}`}
                  download={LINUX_FLATPAK_FILE}
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-green-100 dark:bg-green-900 hover:bg-green-200 dark:hover:bg-green-800 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>Download {LINUX_FLATPAK_FILE}</span>
                </a>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Not yet on Flathub - install the bundle directly:
                </p>
                <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mt-2">
                  flatpak install --user ./{LINUX_FLATPAK_FILE}
                </pre>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Requires the <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">nebula-commander-service</code> .deb (or equivalent) installed and running separately - the Flatpak is the GUI frontend only.
                </p>
              </div>
            </div>


            <h3 className="text-lg font-semibold mb-2">Then start the service and enroll</h3>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              Get the enrollment code from Nodes → Enroll. Start the service first; it waits for enrollment:
            </p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">{`sudo systemctl enable --now ncclient`}</pre>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              Then enroll in the desktop app (Enrollment tab), or from a shell:
            </p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">{`sudo ncclient enroll --server ${SERVER_URL} --code XXXXXXXX`}</pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-8">
              The service picks up the token right away. Check it with 
              <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">systemctl status ncclient</code>.
            </p>

            <h2 className="text-xl font-bold mb-2">Standalone binary or pip (advanced)</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
              For distributions the packages don't cover. These install only the command; you set up
              the service yourself, as root, and there's no desktop app. Pip in particular is for
              advanced users only: it's easy to end up with a setup that root can't find or that
              stores its token where the service doesn't look.
            </p>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Binary - no Python required</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              {DOWNLOADS.filter((d) => d.platform === "linux").map((d) => (
                <a
                  key={d.file}
                  href={`/downloads/${d.file}`}
                  download={d.file}
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>{d.name}</span>
                </a>
              ))}
            </div>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">{`sudo install -m 0755 ncclient-linux-amd64 /usr/local/bin/ncclient   # or ncclient-linux-arm64`}</pre>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Or pip (Python 3.10+)</p>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
              Install into a root-owned virtualenv, not one in your home directory: the service runs this
              code as root, so your user must not be able to change it.
            </p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">{PIP_LINUX_SNIPPET}</pre>

            <h3 className="text-lg font-semibold mb-2">Then enroll as root and install the service</h3>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              Nebula needs root to create its network interface, so every step runs as root, in this order.
              Get the enrollment code from Nodes → Enroll, then:
            </p>
            <pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded text-sm overflow-x-auto mb-4">{STANDALONE_SETUP_SNIPPET}</pre>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
              <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient install</code> asks for the server URL and options, writes a systemd
              service that runs <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient run</code> as root, and offers to start it. From then on
              the service is the client: don't also run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient run</code> by hand.
            </p>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Keep using <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">sudo</code> for <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient routes</code> and re-enrolling.
              Run as a regular user, <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code> reads that user's own (empty) token and
              settings, not the service's.
            </p>
          </Card>
        </Tabs.Item>

        <Tabs.Item title="Windows">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Downloads</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
              CLI binary, or the MSI installer for the full GUI app.
            </p>
            <div className="space-y-4 mb-6">
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">ncclient (command-line)</p>
                <a
                  href={`/downloads/${DOWNLOADS.find((d) => d.platform === "windows")?.file}`}
                  download
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
                >
                  <HiDownload className="w-5 h-5 shrink-0" />
                  <span>ncclient-windows-amd64.exe</span>
                </a>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">MSI installer (CLI + App)</p>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                  Installs ncclient, the windowed desktop app (enrollment, status, settings - minimizes to tray on close), and the background Windows service, with Start Menu shortcuts and an optional PATH entry.
                </p>
                <a
                  href="/downloads/NebulaCommander-windows-amd64.msi"
                  download="NebulaCommander-windows-amd64.msi"
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-green-100 dark:bg-green-900 hover:bg-green-200 dark:hover:bg-green-800 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
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
                  className="inline-flex items-center gap-2 px-4 py-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] transition-colors"
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

            <h3 className="text-lg font-bold mb-2">Setting up a mobile node</h3>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              On the <strong>Nodes</strong> page, click <strong>Create Node</strong> and set Platform
              to <strong>iOS</strong> or <strong>Android</strong>. Mobile nodes skip enrollment
              entirely (there's no ncclient agent to run) - once created, you'll get a{" "}
              <strong>Download config.yaml</strong> button instead. That file is a complete,
              self-contained Nebula config (certificate, key, and CA embedded) ready to import.
            </p>
            <p className="text-gray-700 dark:text-gray-300 mb-4">
              In the Mobile Nebula app: <strong>Add Site → From file</strong>, then select the
              downloaded file. If the certificate is ever reissued (e.g. after a group change or a
              manual "Reissue Certificate"), download the new file the same way and re-import it.
            </p>

            <h3 className="text-lg font-bold mb-2">Split-horizon DNS</h3>
            <p className="text-gray-700 dark:text-gray-300 mb-2">
              <strong>iOS</strong> gets split-horizon DNS automatically whenever the network's DNS
              is enabled (Network → DNS page) - Mobile Nebula uses Apple's domain-scoped DNS
              matching, so only your mesh domain's queries route through the lighthouse; everything
              else uses normal DNS. No extra configuration needed.
            </p>
            <p className="text-gray-700 dark:text-gray-300">
              <strong>Android</strong> has no domain-scoping capability in the OS - enabling DNS
              there is an explicit opt-in checkbox on the Create Node form, and it's a{" "}
              <strong>full override</strong>: all device DNS routes through the network's
              lighthouse(s) while connected, and breaks entirely if they're unreachable. Off by
              default; only enable it if you understand that tradeoff.
            </p>
          </Card>
        </Tabs.Item>
      </Tabs>
    </div>
  );
}
