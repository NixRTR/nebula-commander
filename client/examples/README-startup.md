# Running ncclient at startup

ncclient can run at boot/login on **Linux** (systemd), **macOS** (launchd), and **Windows 11** (Task Scheduler or NSSM). Enroll once with a code from the Nebula Commander UI, then install the service so config and certs stay up to date and Nebula runs automatically.

**Linux:** The easiest way is **`sudo ncclient install`**, which prompts for the server URL and optional env vars and installs the systemd unit and `/etc/default/ncclient`. See the main [README](../README.md) for details.

---

## Linux (systemd)

If you prefer to install the unit manually instead of using `ncclient install`:

1. **Install ncclient and enroll once**
   ```bash
   pip install nebula-commander
   ncclient enroll --server https://YOUR_NEBULA_COMMANDER_URL --code XXXXXXXX
   ```
   If you use `/etc/nebula` for output, run enroll as root so the token can be written to `/etc/nebula-commander/token`.

2. **Install the systemd unit**
   ```bash
   sudo cp examples/ncclient.service /etc/systemd/system/
   ```

3. **Configure the server URL (and optional options)**
   ```bash
   sudo nano /etc/default/ncclient
   ```
   Set at least:
   ```
   NEBULA_COMMANDER_SERVER=https://your-nebula-commander.example.com
   ```
   Optional (see `examples/ncclient.env.example`):
   - `NEBULA_COMMANDER_OUTPUT_DIR=/etc/nebula`
   - `NEBULA_COMMANDER_INTERVAL=60`
   - `NEBULA_COMMANDER_RESTART_SERVICE=nebula` (if Nebula is a separate systemd service)
   - `NEBULA_COMMANDER_NEBULA=/usr/bin/nebula` (if nebula is not on PATH)

4. **Fix ExecStart path if needed**  
   If `ncclient` is not in `/usr/bin` (e.g. installed with `pip install --user`, so it's in `~/.local/bin`), override the service:
   ```bash
   sudo systemctl edit ncclient
   ```
   Add:
   ```ini
   [Service]
   ExecStart=/home/YOUR_USER/.local/bin/ncclient run
   ```

5. **Enable and start**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now ncclient
   sudo systemctl status ncclient
   ```

---

## macOS (launchd)

1. **Install ncclient and enroll once**
   ```bash
   pip install nebula-commander
   ncclient enroll --server https://YOUR_NEBULA_COMMANDER_URL --code XXXXXXXX
   ```

2. **Copy and edit the LaunchAgent**
   - **User-level** (runs when you log in): `~/Library/LaunchAgents/`
   - **System-level** (runs at boot): `/Library/LaunchDaemons/` (requires root)
   ```bash
   cp examples/com.nixrtr.ncclient.plist ~/Library/LaunchAgents/
   ```
   Edit the plist:
   - Set `NEBULA_COMMANDER_SERVER` in `EnvironmentVariables` to your Nebula Commander URL.
   - Set the first item in `ProgramArguments` to the full path of `ncclient` (run `which ncclient`, e.g. `/opt/homebrew/bin/ncclient` on Apple Silicon).

3. **Load and start**
   ```bash
   launchctl load ~/Library/LaunchAgents/com.nixrtr.ncclient.plist
   ```
   To unload: `launchctl unload ~/Library/LaunchAgents/com.nixrtr.ncclient.plist`

   Logs go to `/tmp/ncclient.log` and `/tmp/ncclient.err` (edit the plist to change paths).

---

## Windows 11

### Option A: Task Scheduler (built-in)

1. **Install and enroll**
   ```powershell
   pip install nebula-commander
   ncclient enroll --server https://YOUR_NEBULA_COMMANDER_URL --code XXXXXXXX
   ```

2. **Edit the PowerShell script**
   Edit `examples/ncclient-run-windows.ps1` and set `NEBULA_COMMANDER_SERVER` to your URL.

3. **Create a scheduled task**
   - Open **Task Scheduler**.
   - Create Task (not Basic Task).
   - **General**: "Run whether user is logged on or not" if you want it at boot; otherwise "Run only when user is logged on".
   - **Triggers**: New → "At log on" (or "At startup" for run-at-boot).
   - **Actions**: New → Program: `powershell.exe`, Arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\path\to\nebula-commander\client\examples\ncclient-run-windows.ps1"`.
   - **Settings**: Allow task to be run on demand; optionally "Run task as soon as possible after a scheduled start is missed".

4. **Run the task**  
   Task Scheduler → right‑click the task → Run. Check that ncclient is running (e.g. in Task Manager or `Get-Process`).

### Option B: NSSM (Windows service)

[NSSM](https://nssm.cc/) runs a process as a Windows service.

1. Install ncclient and enroll (same as above).
2. Install NSSM (e.g. `winget install NSSM.NSSM` or download from nssm.cc).
3. From an **elevated** command prompt:
   ```cmd
   nssm install NebulaCommander "C:\path\to\python.exe" "-m" "ncclient" "run"
   ```
   If ncclient is installed as a script: `nssm install NebulaCommander "C:\Users\You\AppData\Local\Programs\Python\Python312\Scripts\ncclient.exe" "run"`.
4. Set the environment in NSSM:  
   NSSM → Service NebulaCommander → Edit → Application tab → AppEnvironmentExtra:  
   `NEBULA_COMMANDER_SERVER=https://your-nebula-commander.example.com`
5. Start the service: `nssm start NebulaCommander`.

---

## Environment variables (all platforms)

When using `ncclient run` (with no `--server`), these are read from the environment (e.g. systemd `EnvironmentFile`, launchd `EnvironmentVariables`, or Windows task/env):

| Variable | Description | Default |
|----------|--------------|---------|
| `NEBULA_COMMANDER_SERVER` | Nebula Commander base URL | (required) |
| `NEBULA_COMMANDER_OUTPUT_DIR` | Where to write config/certs | `/etc/nebula` (Linux/macOS), `~/.nebula` (Windows) |
| `NEBULA_COMMANDER_INTERVAL` | Poll interval (seconds) | 60 |
| `NEBULA_COMMANDER_TOKEN_FILE` | Device token file path | `~/.config/nebula-commander/token` or `/etc/nebula-commander/token` (root) |
| `NEBULA_COMMANDER_NEBULA` | Path to nebula binary (if not in PATH) | (use `nebula` from PATH) |
| `NEBULA_COMMANDER_RESTART_SERVICE` | systemd service to restart (Linux only) | (ncclient runs nebula directly if unset) |

Command-line arguments override these (e.g. `ncclient run --server https://...`).
