import { Card, Tabs } from "flowbite-react";
import { HiDownload } from "react-icons/hi";

const DOWNLOADS = [
  { name: "Linux (x86_64)", file: "ncclient-linux-amd64", platform: "linux" },
  { name: "Linux (ARM64)", file: "ncclient-linux-arm64", platform: "linux" },
  { name: "Windows (x86_64)", file: "ncclient-windows-amd64.exe", platform: "windows" },
  { name: "Windows (ARM64)", file: "ncclient-windows-arm64.exe", platform: "windows" },
  { name: "macOS (Intel)", file: "ncclient-macos-amd64", platform: "macos" },
  { name: "macOS (Apple Silicon)", file: "ncclient-macos-arm64", platform: "macos" },
] as const;

export function ClientDownload() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Client Download</h1>
      <p className="text-gray-600 dark:text-gray-400 mb-6">
        Install and run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">ncclient</code> on your device to enroll with Nebula Commander and pull config and certificates. Get the enrollment code from the Nodes page (Enroll button).
      </p>

      <Card className="mb-6">
        <h2 className="text-xl font-bold mb-2">Download ncclient (standalone)</h2>
        <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
          Pre-built executables — no Python required. Served from this server so no internet access is needed after deployment.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {DOWNLOADS.map((d) => (
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
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-3">
          Linux/macOS: after download run <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">chmod +x ncclient-*</code> then move to <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">/usr/local/bin</code> or your PATH.
        </p>
      </Card>

      <h2 className="text-xl font-bold mb-4">Alternative: install via Python (PyPI)</h2>
      <Tabs aria-label="Client installation instructions" style="underline">
        <Tabs.Item active title="Linux">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Install</h2>
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
            <h2 className="text-xl font-bold mb-4">Install</h2>
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

        <Tabs.Item title="Mac">
          <Card className="mt-4">
            <h2 className="text-xl font-bold mb-4">Install</h2>
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
      </Tabs>
    </div>
  );
}
