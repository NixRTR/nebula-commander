# Nebula Commander for Windows: Service

> **Looking for the GUI?** See
> [client/windows-app/README.md](../windows-app/README.md) - the native
> WinUI 3 windowed app that talks to the service documented here. (The
> older Python/Tkinter system-tray app that used to live in this directory
> has been removed; the WinUI 3 app is the only GUI client now.)

**`ncclient-service.exe`** is a real Windows Service (`NebulaCommanderService`,
runs as LocalSystem). Does the actual work: polls Nebula Commander for
config/certs, runs the Nebula binary, and applies split-horizon DNS. Runs
continuously, whether or not anyone is logged in, with no UAC prompt
(LocalSystem is already fully privileged).

GUI clients (currently just `client/windows-app/`) talk to it via shared state
under `%ProgramData%\nebula-commander\` (settings, the DPAPI-encrypted device
token, a status file, the downloaded `nebula.exe`, and Nebula's own
`config.yaml`/`dns-client.json`/`nebula.log`) and a small named pipe used to
tell the service "act on this change now" instead of waiting for its next
poll cycle. See `client/windows/shared_paths.py`,
`client/windows/pipe_protocol.py`, and `client/windows/service.py` for the
details.

## Do I need a system service or network adapter?

- **Yes, a Windows Service is installed** (`NebulaCommanderService`) - that's
  what actually runs the VPN. The MSI installer registers it (start type:
  Automatic) and grants local users start/stop/query rights so GUI clients'
  service-control actions work without repeated UAC prompts.
- **Nebula's virtual network adapter.** When the service is running with a
  valid enrollment, Nebula creates a virtual network interface (Nebula on
  Windows uses [Wintun](https://www.wintun.net/)). No separate driver install
  is required for typical use. If you see errors like "create wintun
  interface failed" in `%ProgramData%\nebula-commander\nebula.log`, see
  [Nebula's Windows documentation](https://github.com/slackhq/nebula#windows)
  and [Wintun](https://www.wintun.net/) for troubleshooting.

## Run from source (development)

From the **nebula-commander** repo root (parent of `client/`):

```bash
pip install -r client/windows/requirements.txt
pip install -e client/
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
  interval, optional Nebula path, accept-DNS flag) - shared between the
  service and any GUI client, not per-user.
- The device token is stored DPAPI-encrypted (machine scope) at
  `%ProgramData%\nebula-commander\token.bin` - readable by any process on this
  machine (not tied to one user's login session, which is what lets the
  LocalSystem service and an unelevated GUI client both use it), but not a
  defense against other local users on a shared multi-user machine.

## Build (PyInstaller)

From **nebula-commander** repo root:

```bash
cd client/windows
pip install -r requirements.txt pyinstaller
python build.py
```

See `build.py` and `ncclient-service.spec` for details. Packaging into an
installable MSI (which registers the service and sets up the shared
`%ProgramData%` folder's permissions) is handled by
`installer/windows/Product.wxs` - see `installer/windows/README.md`.
