# ncclient – Nebula Commander device client

**License:** GNU GPLv3 or later. See [LICENSE](LICENSE) in this directory.

A small client that works like [Defined.net's dnclient](https://docs.defined.net/glossary/dnclient) and [dnclientd](https://docs.defined.net/glossary/dnclientd): enroll once with a code from Nebula Commander, then run as a daemon to pull config and certificates and optionally **orchestrate the Nebula process** (start/restart it when config changes).

## Install

From PyPI (recommended):

```bash
pip install nebula-commander
```

This installs the `ncclient` command. Requires Python 3.10+.

From source (e.g. repo clone):

```bash
pip install -r client/requirements.txt
# then run as: python -m client --server URL enroll --code XXX
```

Or install the package in development mode from the `client/` directory: `pip install -e .` to get the `ncclient` command.

## Enroll (one-time)

1. In Nebula Commander, open **Nodes**, find your node, and click **Enroll**.
2. Copy the enrollment code and run on the device:

```bash
ncclient enroll --server https://YOUR_NEBULA_COMMANDER_URL --code XXXXXXXX
```

This saves a device token to `~/.config/nebula-commander/token` (or `/etc/nebula-commander/token` when run as root).

## Run (daemon)

Poll for config and certs every 60 seconds, write them to `/etc/nebula` (or another directory), and **run Nebula** (from your PATH) when config changes:

```bash
ncclient run --server https://YOUR_NEBULA_COMMANDER_URL
```

ncclient assumes `nebula` is on your PATH and will start/restart it by default. Options:

- `--output-dir DIR` – where to write `config.yaml`, `ca.crt`, `host.crt` (default: `/etc/nebula` on Linux/macOS, `~/.nebula` on Windows)
- `--interval N` – poll interval in seconds (default: 60)
- `--token-file PATH` – path to device token file
- **`--nebula PATH`** – path to the `nebula` binary **only if it's not in PATH** (e.g. `--nebula /opt/homebrew/bin/nebula`). Omit this when `nebula` is already on your PATH.
- **`--restart-service NAME`** – instead of running nebula directly, restart this systemd service after config updates (e.g. `nebula`). Use **only one** of `--nebula` or `--restart-service`.

Example – nebula in a non-standard location:

```bash
ncclient run --server https://nc.example.com --nebula /usr/local/bin/nebula
```

Example – use systemd to run Nebula; ncclient only restarts the service:

```bash
ncclient run --server https://nc.example.com --restart-service nebula
```

When the certificate was **created** via the server (Create certificate in the Nebula Commander UI), the bundle includes `host.key` and no manual copy is needed. For certificates created via **Sign** (betterkeys, client-generated key), the server does not have the key; place your own `host.key` in the same directory as the generated certs.

**Linux:** Creating the Nebula TUN device requires root. Run ncclient as root so the Nebula process can create the interface, e.g. `sudo ncclient run --server https://...` (or use `--output-dir ~/.nebula` and run as root so nebula reads from a dir that has host.key).

## Troubleshooting

- **No network device (tun) created / can't ping Nebula IP**  
  On Linux, Nebula needs root to create the TUN interface. Run **`sudo ncclient run --server ...`**.  
  If the certificate was **created** via the server (Create certificate in the UI), the bundle includes `host.key` and no manual copy is needed. If it was created via **Sign** (betterkeys), put your `host.key` in the output dir (e.g. `/etc/nebula`). Nebula will exit or fail without `host.key`.  
  Nebula's errors are printed to the same terminal; look for messages like "failed to get tun device" (permission) or "no such file" (missing host.key).

- **Nebula starts then exits**  
  Check the Nebula error lines ncclient prints. Common causes: missing `host.key` (for Sign flow; Create flow includes it in the bundle), wrong config path, or (Linux) need to run as root.

## Running at startup

### Quick install (Linux)

On Linux you can install the systemd service with one command:

```bash
sudo ncclient install
```

This checks that you have already enrolled (token at `/etc/nebula-commander/token`). If not, it prints the exact `ncclient enroll --server URL --code XXXXXXXX` command to run first (get the code from the Nebula Commander UI: Nodes → Enroll). Then it prompts for the server URL and optional settings (output directory, poll interval, nebula path, restart-service), writes `/etc/default/ncclient` and `/etc/systemd/system/ncclient.service`, enables the service, and optionally starts it. Use `--no-start` to enable without starting; use `--non-interactive` with `NEBULA_COMMANDER_SERVER` (and optional env vars) set for scripting.

### Manual setup (all platforms)

Run `ncclient run` under systemd (or your init system) so config and certs stay up to date. ncclient runs `nebula` from your PATH by default; use `--restart-service` if you prefer to have systemd run Nebula and ncclient only restart the service. Example configs are in **`examples/`**; see [examples/README-startup.md](examples/README-startup.md) for step-by-step install on macOS and Windows.

## macOS

ncclient works on macOS (Intel and Apple Silicon). Use Python 3.10+ and install with `pip install nebula-commander`.

- **Token** is stored at `~/.config/nebula-commander/token` (or `/etc/nebula-commander/token` when run as root).
- **Default output dir** is `/etc/nebula` (same as Linux). If you run as a normal user, use `--output-dir ~/.nebula` so you don't need sudo to write config/certs.
- **Nebula**: ncclient runs `nebula` from your PATH by default. After `brew install nebula`, you usually don't need `--nebula`. Use `--nebula /opt/homebrew/bin/nebula` (Apple Silicon) or `--nebula /usr/local/bin/nebula` (Intel) only if it's not on PATH. Do not use `--restart-service`; macOS uses launchd, not systemd.
- To run ncclient in the background, use **launchd** (e.g. a LaunchAgent in `~/Library/LaunchAgents` or a LaunchDaemon in `/Library/LaunchDaemons`).

## Windows 11

ncclient works on Windows 11. Use Python 3.10+ and install with `pip install nebula-commander`.

- **Token** is stored under `%USERPROFILE%\.config\nebula-commander\token`.
- **Default output dir** for config and certs is `%USERPROFILE%\.nebula`. Override with `--output-dir` (e.g. `C:\ProgramData\Nebula` if you run as Administrator).
- **Nebula**: ncclient runs `nebula` from your PATH by default. If `nebula.exe` is not on PATH, use `--nebula "C:\Path\To\nebula.exe"`. Do not use `--restart-service`; there is no systemd on Windows.
- Run ncclient in a terminal or install it as a Windows service (e.g. with NSSM or Task Scheduler) so it keeps running.

### Windows tray app

A **system-tray app** for Windows provides the same enroll-and-poll flow with a GUI: tray icon, Enroll and Settings dialogs, Start/Stop polling, optional bundled Nebula binary, and **Start at login** (Registry Run). See **[client/windows/README.md](windows/README.md)** for how to run from source and how to build `ncclient-tray.exe` (with optional bundled `nebula.exe`) using PyInstaller.
