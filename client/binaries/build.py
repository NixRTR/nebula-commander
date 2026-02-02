#!/usr/bin/env python3
"""
Build script for ncclient executables using PyInstaller.

Usage:
    python build.py              # Build for current platform
    python build.py --clean      # Clean build artifacts
    python build.py --test       # Build and run basic tests
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_platform_name():
    """Get normalized platform name for output."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "linux":
        return f"linux-{machine}"
    elif system == "darwin":
        return f"macos-{machine}"
    elif system == "windows":
        return f"windows-{machine}"
    return f"{system}-{machine}"


def clean():
    """Remove build artifacts."""
    print("Cleaning build artifacts...")
    dirs_to_remove = ["build", "dist", "__pycache__"]
    files_to_remove = ["*.spec~"]
    
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            print(f"  Removing {dir_name}/")
            shutil.rmtree(dir_name)
    
    print("Clean complete.")


def check_pyinstaller():
    """Check if PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("ERROR: PyInstaller is not installed.")
        print("Install with: pip install pyinstaller")
        return False


def build():
    """Build the executable using PyInstaller."""
    if not check_pyinstaller():
        return False
    
    print(f"\nBuilding ncclient for {get_platform_name()}...")
    print("-" * 60)
    
    # Run PyInstaller (use python -m to avoid PATH issues)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--clean", "ncclient.spec"],
            check=True,
            capture_output=False,
        )
        print("-" * 60)
        print("Build successful!")
        
        # Show output location
        exe_name = "ncclient.exe" if platform.system() == "Windows" else "ncclient"
        exe_path = Path("dist") / exe_name
        
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\nExecutable: {exe_path.absolute()}")
            print(f"Size: {size_mb:.2f} MB")
            return True
        else:
            print(f"\nWARNING: Expected executable not found at {exe_path}")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print("\nERROR: pyinstaller command not found.")
        print("Install with: pip install pyinstaller")
        return False


def test():
    """Run basic tests on the built executable."""
    exe_name = "ncclient.exe" if platform.system() == "Windows" else "ncclient"
    exe_path = Path("dist") / exe_name
    
    if not exe_path.exists():
        print(f"ERROR: Executable not found at {exe_path}")
        print("Run build first: python build.py")
        return False
    
    print(f"\nTesting {exe_path}...")
    print("-" * 60)
    
    # Test 1: Help command
    print("\nTest 1: --help")
    try:
        result = subprocess.run(
            [str(exe_path), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("[PASS] Help command works")
            print(result.stdout[:200] + "..." if len(result.stdout) > 200 else result.stdout)
        else:
            print(f"[FAIL] Help command failed with exit code {result.returncode}")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"[FAIL] Help command failed: {e}")
        return False
    
    # Test 2: Version check (via help output)
    print("\nTest 2: Command structure")
    try:
        result = subprocess.run(
            [str(exe_path), "enroll", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and "code" in result.stdout.lower():
            print("[PASS] Enroll subcommand works")
        else:
            print("[FAIL] Enroll subcommand failed")
            return False
    except Exception as e:
        print(f"[FAIL] Enroll subcommand test failed: {e}")
        return False
    
    print("\n" + "-" * 60)
    print("All tests passed!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build ncclient executable with PyInstaller"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build artifacts and exit",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run tests after building",
    )
    
    args = parser.parse_args()
    
    # Change to script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    if args.clean:
        clean()
        return 0
    
    # Build
    if not build():
        return 1
    
    # Test if requested
    if args.test:
        if not test():
            return 1
    
    print("\n" + "=" * 60)
    print("SUCCESS!")
    print("=" * 60)
    
    exe_name = "ncclient.exe" if platform.system() == "Windows" else "ncclient"
    print(f"\nYour executable is ready: dist/{exe_name}")
    print("\nNext steps:")
    print(f"  1. Test it: ./dist/{exe_name} --help")
    print(f"  2. Test enrollment: ./dist/{exe_name} enroll --server URL --code CODE")
    print(f"  3. Distribute the dist/{exe_name} file to users")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
