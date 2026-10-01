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

All state lives under `%ProgramData%\nebula-commander\` (settings, the
DPAPI-encrypted device token, a status file, the service-managed Nebula
install, and Nebula's own `config.yaml`/`dns-client.json`/`nebula.log`), which
is **SYSTEM/Administrators-only** (`harden.py` enforces this on every start).
GUI clients (currently just `client/windows-app/`) never touch it - they use
the named-pipe API (`pipe_protocol.py` / `pipe_server.py`), the Windows
counterpart of the Linux D-Bus service:

- **Read** commands (status, settings, offered routes, redacted config, ...)
  are open to any local user.
- **Manage** commands (settings, enroll, accept/reject routes and exit nodes,
  Nebula install/update, re-poll) require the caller to be an **elevated
  administrator** - the service checks the caller's token on every call.
  Remote (network) clients are rejected outright.

The service only ever runs its own Nebula install (`nebula_install.py`):
downloaded from the official `slackhq/nebula` release, SHA256-verified against
`SHASUM256.txt`, and the whole archive (`nebula.exe`, `nebula-cert.exe`,
`dist\`) extracted into the protected folder. There is no user-configurable
Nebula path.

## Do I need a system service or network adapter?

- **Yes, a Windows Service is installed** (`NebulaCommanderService`) - that's
  what actually runs the VPN. The MSI installer registers it (start type:
  Automatic) and lets local users query its status; starting/stopping it
  needs an elevated administrator.
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
  interval, accept-DNS flag, accepted routes) - machine-wide, written only by
  the service (via the pipe's manage commands).
- The device token is stored DPAPI-encrypted (machine scope) at
  `%ProgramData%\nebula-commander\token.bin`. Machine-scope DPAPI alone would
  let any local process decrypt it; what protects it is the folder's
  SYSTEM/Administrators-only ACL. The app never reads it - token-authenticated
  calls (enroll, advertised routes) happen inside the service.

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
