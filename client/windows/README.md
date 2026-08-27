# Nebula Commander for Windows: Service + Tray

Two pieces work together:

- **`ncclient-service.exe`** — a real Windows Service (`NebulaCommanderService`, runs
  as LocalSystem). Does the actual work: polls Nebula Commander for config/certs,
  runs the Nebula binary, and applies split-horizon DNS. Runs continuously, whether
  or not anyone is logged in, with no UAC prompt (LocalSystem is already fully
  privileged).
- **`ncclient-tray.exe`** — a lightweight, **unelevated** system-tray app for
  enrolling, editing settings, managing the Nebula binary, and starting/stopping/
  restarting the service. It does not run the VPN itself; it talks to the service.

They share state under `%ProgramData%\nebula-commander\` (settings, the
DPAPI-encrypted device token, a status file, the downloaded `nebula.exe`, and
Nebula's own `config.yaml`/`dns-client.json`/`nebula.log`) and a small named pipe
the tray uses to tell the service "act on this change now" instead of waiting for
its next poll cycle. See `client/windows/shared_paths.py`,
`client/windows/pipe_protocol.py`, and `client/windows/service.py` for the details.

## Do I need a system service or network adapter?

- **Yes, a Windows Service is installed** (`NebulaCommanderService`) — that's what
  actually runs the VPN. The MSI installer registers it (start type: Automatic) and
  grants local users start/stop/query rights so the tray's service-control menu
  items work without repeated UAC prompts. The tray itself is **not** installed as
  a service — its own "Run On Startup" option just adds a per-user Registry entry
  (`HKCU\...\Run`) so the tray icon/UI is available after you log in; the VPN keeps
  running via the service regardless of whether the tray is open.
- **Nebula's virtual network adapter.** When the service is running with a valid
  enrollment, Nebula creates a virtual network interface (Nebula on Windows uses
  [Wintun](https://www.wintun.net/)). No separate driver install is required for
  typical use. If you see errors like "create wintun interface failed" in
  `%ProgramData%\nebula-commander\nebula.log`, see
  [Nebula's Windows documentation](https://github.com/slackhq/nebula#windows) and
  [Wintun](https://www.wintun.net/) for troubleshooting.

## Run from source (development)

From the **nebula-commander** repo root (parent of `client/`):

```bash
pip install -r client/windows/requirements.txt
pip install -e client/
```

Tray (unelevated is fine - it only talks to the service, or shows "service not
installed" if you haven't registered one):

```bash
python -m client.windows.tray
```

Service (needs an elevated shell to install/start; pywin32 gives this for free):

```bash
python -m client.windows.service install
python -m client.windows.service start
# or, to see log output directly instead of via the Event Log:
python -m client.windows.service debug
```

## Settings

- Stored in `%ProgramData%\nebula-commander\settings.json` (server URL, poll
  interval, optional Nebula path, accept-DNS flag) - shared between the service and
  the tray, not per-user.
- The device token is stored DPAPI-encrypted (machine scope) at
  `%ProgramData%\nebula-commander\token.bin` - readable by any process on this
  machine (not tied to one user's login session, which is what lets the
  LocalSystem service and the unelevated tray both use it), but not a defense
  against other local users on a shared multi-user machine.

## Bundled Nebula

The tray's **Manage Nebula** menu item downloads the official Nebula Windows
release into the shared `%ProgramData%\nebula-commander\nebula\` directory (or a
custom directory you pick) and offers to upgrade when a newer version is
available. The service reads whichever path is saved in `settings.json`, falling
back to `nebula` on PATH.

`build.py --with-nebula` can additionally bundle a pinned Nebula binary directly
into the **tray** exe at build time, for offline/first-run convenience.

## Auto-start at login (tray only)

Use the tray menu **Run On Startup** (checkable) to add/remove a per-user Registry
entry (`HKCU\...\Run`) so the tray icon appears after you log in. This only
affects the tray UI - the VPN itself runs via the service (start type: Automatic),
independent of any user session.

## Build (PyInstaller)

From **nebula-commander** repo root:

```bash
cd client/windows
pip install -r requirements.txt pyinstaller
python build.py                       # builds both ncclient-tray.exe and ncclient-service.exe
python build.py --target tray         # tray only
python build.py --target service      # service only
python build.py --with-nebula         # also bundle nebula.exe into the tray build
```

See `build.py`, `ncclient-tray.spec`, and `ncclient-service.spec` for details.
Packaging both into an installable MSI (which registers the service and sets up
the shared `%ProgramData%` folder's permissions) is handled by
`installer/windows/Product.wxs` - see `installer/windows/README.md`.
