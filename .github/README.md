# GitHub configuration

This directory contains GitHub Actions workflows and related config.

- **workflows/** — CI/CD pipelines. See [workflows/README.md](workflows/README.md) for details.

---

## Testing workflows locally with act

You can run GitHub Actions locally with [act](https://github.com/nektos/act) to test workflow changes without pushing.

### What works

- **Linux jobs** — act runs steps in Docker. Use a Ubuntu image to test jobs that use `runs-on: ubuntu-22.04` (e.g. Linux ncclient builds, or the Docker image workflow).
- **Fast feedback** — Edit `.github/workflows/*.yml` and run `act` to check syntax and step order without committing.

### What doesn’t work

- **Windows / macOS** — act does not provide real Windows or macOS runners (it uses Linux containers). Jobs that use `windows-latest` or `macos-*` (Windows ncclient, tray, MSI; macOS builds) will not run as on GitHub. Test those by pushing or using “Run workflow” on GitHub.
- **Release upload** — The release job needs `GITHUB_TOKEN` and artifacts from other jobs. You can run it with act only if you simulate or skip the release step.
- **Tag events** — Workflows triggered by `on: push: tags: v*` must be simulated with an event file (see below).

### Setup

1. **Install act** — [Installation guide](https://github.com/nektos/act#installation) (e.g. `choco install act-cli` on Windows, or download the latest release).
2. **Docker** — act needs Docker (or compatible runtime) to run job containers.

### Usage

From the repository root:

```bash
# List all jobs in the default workflow(s)
act -l

# Run a specific job (use a Ubuntu image for Linux jobs)
act -j "Build Linux (x86_64)" -P ubuntu-22.04=ubuntu:22.04

# Run the workflow for a normal push (Linux jobs only; Windows/macOS will be skipped or fail)
act push -P ubuntu-22.04=ubuntu:22.04
```

To simulate a **tag push** (e.g. to test the release path), create an event file and run:

```bash
# event.json
echo '{"ref":"refs/tags/v0.1.12","repository":{"name":"nebula-commander"}}' > .github/event.json
act push -e .github/event.json -P ubuntu-22.04=ubuntu:22.04
```

(Release upload will still require `GITHUB_TOKEN` and may be skipped or fail locally.)

### Platform image mapping

Use `-P` to map runner labels to local Docker images so Linux steps run in a suitable environment:

| Runner (in workflow) | Example act mapping |
|----------------------|----------------------|
| `ubuntu-22.04`       | `-P ubuntu-22.04=ubuntu:22.04` |
| `ubuntu-latest`      | `-P ubuntu-latest=ubuntu:24.04` |

Windows and macOS runner labels have no effect in act; those jobs run in Linux containers or are skipped.

---

## Running Windows (and macOS) jobs locally

act only runs Linux in Docker, so Windows and macOS jobs need a different approach.

### Option 1: Self-hosted runner

Run the real GitHub Actions Windows job on your own machine by installing a [self-hosted runner](https://docs.github.com/en/actions/using-github-hosted-runners/using-self-hosted-runners) on a Windows PC:

1. **Add a runner** — Repo → Settings → Actions → Runners → New self-hosted runner → follow the Windows steps. The runner gets a label like `self-hosted` and `Windows` (or `X64`).
2. **Use it in a workflow** — Either:
   - Trigger the existing workflow from the Actions tab (Run workflow). Windows jobs will run on GitHub’s `windows-latest` unless you change the workflow to use your runner.
   - Or add a **separate** workflow (e.g. `.github/workflows/build-windows-local.yml`) that uses `runs-on: [self-hosted, Windows]` and copies the Windows build steps from `build-ncclient-binaries.yml`. Run that workflow manually; it will execute on your Windows machine.

The runner must have Python 3.11, Node (if needed), and enough tools to build ncclient and the tray app. Same idea applies for macOS if you have a Mac and add a macOS self-hosted runner.

### Option 2: Run the same steps manually (no GitHub)

Replicate the Windows job steps in PowerShell on your machine. From the repo root:

**ncclient CLI (client/binaries):**

```powershell
python -m pip install --upgrade pip
pip install -r client/binaries/requirements.txt
pip install -r client/requirements.txt
cd client/binaries
python build.py
# optional: python build.py --test
# output: dist/ncclient.exe
```

**ncclient-tray (client/windows):**

```powershell
pip install -r client/requirements.txt
pip install -r client/windows/requirements.txt
pip install pyinstaller
cd client/windows
python build.py
# output: dist/ncclient-tray.exe
```

**MSI (installer/windows):** After both exes exist, copy them into `installer/windows/redist/` as `ncclient.exe` and `ncclient-tray.exe`, then see [installer/windows/README.md](../installer/windows/README.md) (install WiX, add Util extension, run `wix build`).

This gives you the same build artifacts as the Windows job without using GitHub at all. Use it to iterate on build fixes or verify the pipeline steps.
