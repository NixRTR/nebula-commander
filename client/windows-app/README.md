# Nebula Commander for Windows: native app (WinUI 3)

A windowed, side-tab (Status / Enrollment / Settings) desktop app that
minimizes to the tray on close instead of exiting. It's a native front end
for the `NebulaCommanderService` Windows Service (`client/windows/service.py`)
- it doesn't run the VPN itself, doesn't change the service or its IPC
contract, and shares the same `%ProgramData%\nebula-commander\` state
(settings, the DPAPI-encrypted device token, `status.json`,
`available-routes.json`, and Nebula's own
`config.yaml`/`dns-client.json`/`nebula.log`) and named pipe
(`client/windows/pipe_protocol.py`) used to nudge the service to act
immediately instead of waiting for its next poll cycle.

This is the **only** GUI now (the installer's finish-dialog checkbox launches
it) - an older Python/Tkinter system-tray-only app that used to ship
alongside it has been removed.

## Prerequisites

- [.NET SDK](https://dotnet.microsoft.com/download) matching the
  `TargetFramework` in `NebulaCommanderApp.csproj` (currently
  `net10.0-windows10.0.26100.0`) - `dotnet --list-sdks` to check what's
  installed.
- Windows 10 1809+ (`TargetPlatformMinVersion` `10.0.17763.0`) or Windows 11,
  x64. The project also declares `x86`/`ARM64` platforms but only x64 has
  been built/tested.
- No separate Windows App SDK runtime install needed - it's referenced as a
  NuGet package (`Microsoft.WindowsAppSDK`) and bundled at publish time (see
  below), not installed system-wide.

## Run from source (development)

From this directory:

```powershell
dotnet build   # or: dotnet run
```

`dotnet run` launches the built exe directly and blocks until the window
closes (including if it's minimized to the tray - closing from the tray's
Exit menu item is what actually ends the process). For faster iteration,
`dotnet build` then run
`bin\Debug\net10.0-windows10.0.26100.0\win-x64\NebulaCommanderApp.exe`
directly.

No elevation needed - it only talks to the already-installed,
already-elevated `NebulaCommanderService` (service start/stop/restart works
unelevated because the MSI grants Authenticated Users those specific rights
on the service - see `installer/windows/Product.wxs`'s `GrantServiceControlAcl`).
If the service isn't installed/running yet, the Status page reflects that
rather than failing.

## Build (self-contained single-file publish)

```powershell
dotnet publish -c Release -r win-x64
```

Output: `bin\Release\net10.0-windows10.0.26100.0\win-x64\publish\NebulaCommanderApp.exe`
- one file (~335 MB - it bundles the full .NET runtime and Windows App SDK
  runtime, so the published exe has no prerequisites to install on the
  target machine). `WindowsAppSDKSelfContained`, `SelfContained`, and
  `PublishSingleFile` are already set in the csproj, so no extra publish
  flags are needed.

Packaging into the installable MSI (alongside `ncclient.exe`/
`ncclient-service.exe`) is handled by
`installer/windows/Product.wxs` - see `installer/windows/README.md`. CI
publishes this exe automatically on a version tag (`build-windows-app` job
in `.github/workflows/build-ncclient-binaries.yml`).

## Project layout

```
App.xaml(.cs)              startup: enrolled? -> Status page : Enrollment page
MainWindow.xaml(.cs)       NavigationView shell (side tabs); Closing -> hide to tray
Pages/
  StatusPage               server/service/interface/DNS/routing status, live
  EnrollmentPage           enroll/re-enroll with a code
  SettingsPage             server/interval/Nebula path/DNS toggle, Nebula binary
                            download, run-on-startup
Services/
  SharedPaths               %ProgramData%\nebula-commander\ path resolution
  SettingsStore, StatusStore, RoutesStore   settings.json / status.json /
                            available-routes.json read(/write)
  TokenStore                 token.bin via DPAPI (ProtectedData, LocalMachine
                            scope, no entropy) - see "Notes" below
  PipeClient                 \\.\pipe\NebulaCommanderControl client
  ServiceControl              ServiceController wrapper (status/start/stop/restart)
  BackendClient               HTTP: enroll, /api/health, /api/device/advertised-routes
  ConfigYaml                  minimal read of config.yaml's tun.dev/unsafe_routes
  NebulaDownload               GitHub-releases download/version-check for nebula.exe
  AutoStart                   HKCU Run-key toggle
  CidrUtil                    CIDR overlap check for the subnet-route picker
Tray/
  TrayIcon                    System.Windows.Forms.NotifyIcon + context menu
```

## Notes for anyone touching this project

- **`UseWindowsForms=true` doesn't work here.** `Tray/TrayIcon.cs` needs
  `System.Windows.Forms.NotifyIcon` (WinUI 3 has no first-party tray icon
  API), but setting the standard `<UseWindowsForms>true</UseWindowsForms>`
  MSBuild property pulls in the WindowsDesktop SDK's WPF/WinForms XAML
  markup-compiler targets, which then collide with the WinUI XAML compiler
  over this project's own `.xaml` files (`MC6000: must include
  PresentationCore, PresentationFramework`). The csproj instead uses
  `<FrameworkReference Include="Microsoft.WindowsDesktop.App.WindowsForms" />`,
  which gets the `System.Windows.Forms`/`System.Drawing` assemblies without
  that side effect.
- **`PublishSingleFile` requires `EnableMsixTooling=true`**, even though this
  app is unpackaged (`WindowsPackageType=None`, no MSIX produced) - the
  single-file bundler's `resources.pri` generation depends on that tooling
  being enabled. It's not related to actually producing an MSIX package;
  `WindowsPackageType=None` is what controls that.
- **The published single-file exe extracts bundled content (e.g.
  `Assets/AppIcon.ico`) to `%TEMP%\.net\NebulaCommanderApp\<hash>\` at
  runtime**, and `AppContext.BaseDirectory` is redirected there - standard
  .NET single-file behavior, not something this project's code needs to
  account for (relative-path file lookups like `Assets/AppIcon.ico` resolve
  correctly with no special-casing).
- **`TokenStore.cs`'s DPAPI usage must stay byte-compatible with
  `client/token_store.py`**: `ProtectedData.Protect(data, null,
  DataProtectionScope.LocalMachine)` is the .NET equivalent of
  `win32crypt.CryptProtectData(data, "nebula-commander-token", None, None,
  None, CRYPTPROTECT_LOCAL_MACHINE | CRYPTPROTECT_UI_FORBIDDEN)` - no extra
  entropy either side (the Python side's description string is DPAPI
  metadata, not entropy, so it doesn't need to match). This is what lets the
  LocalSystem service and this app both read/write the same `token.bin`.
- **Nebula's firewall `cidr` field is combinable with `local_cidr`** (since
  Nebula 1.9.0) and matches the peer's certificate-verified overlay IP, not
  a spoofable source address - this is what makes `CidrUtil`'s
  client-side-only overlap check meaningful pre-flight validation rather
  than the actual security boundary (that's enforced server-side in
  generated firewall rules - see `docs/unsafe-routes.md`).
