# Quick Start Guide - Building ncclient Executables

## Step 1: Install PyInstaller

```bash
cd client/binaries
pip install -r requirements.txt
```

## Step 2: Build for Your Platform

### Windows (PowerShell)

```powershell
cd client\binaries
python build.py
```

### Linux/macOS

```bash
cd client/binaries
python build.py
```

## Step 3: Test the Executable

### Windows

```powershell
.\dist\ncclient.exe --help
.\dist\ncclient.exe enroll --help
```

### Linux/macOS

```bash
./dist/ncclient --help
./dist/ncclient enroll --help
```

## Step 4: Test with Build Script

```bash
python build.py --test
```

This will build and run automated tests.

## What Gets Created

- **Single executable file**: `dist/ncclient` (or `ncclient.exe` on Windows)
- **Size**: ~15-20 MB (includes Python + all dependencies)
- **No Python required**: Users can run it without installing Python

## Distribution

The executable in `dist/` is completely standalone. You can:

1. Copy it to any machine with the same OS
2. Rename it if desired
3. Put it in `/usr/local/bin` (Linux/macOS) or `C:\Program Files\` (Windows)
4. Distribute via GitHub Releases

## Cleaning Up

```bash
python build.py --clean
```

## Troubleshooting

### "PyInstaller not found"

```bash
pip install pyinstaller
```

### "Module not found" errors during build

The spec file includes hidden imports for `requests` and its dependencies. If you add new dependencies to ncclient, update the `hiddenimports` list in `ncclient.spec`.

### Large file size

The executable includes the entire Python interpreter. To reduce size:

1. UPX compression is enabled (requires UPX to be installed)
2. Unnecessary modules are excluded in the spec file
3. Consider using `--onedir` mode instead of `--onefile` (faster startup, slightly smaller)

### Testing on target platform

Always test the executable on a clean machine without Python installed to ensure all dependencies are bundled correctly.

## Next Steps

- See `README.md` for detailed documentation
- See `github-actions-example.yml` for automated builds
- See `ncclient.spec` for build configuration
