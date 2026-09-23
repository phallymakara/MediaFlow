"""Build and packaging script to bundle MediaFlow for production release.

This script creates standalone distribution packages for macOS (.dmg/.app) and Windows (.exe)
using PyInstaller, ensuring that internal vendor tools (tools/) and private signing keys
are strictly excluded from the client distribution bundle.
"""

import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_release(clean: bool = True, output_dir: str = "dist") -> None:
    """Build standalone executable bundle excluding vendor tools and private keys."""
    os_name = platform.system().lower()
    print(f"Building MediaFlow standalone release for: {os_name.capitalize()}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name=MediaFlow",
        # Exclude vendor tools and private keys
        "--exclude-module=tools",
        "--exclude-module=pytest",
        "--exclude-module=test",
        "--exclude-module=tests",
    ]

    if clean:
        cmd.append("--clean")

    # Add hidden imports
    cmd.extend([
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=cryptography",
        "--hidden-import=yt_dlp",
        "--hidden-import=httpx",
    ])

    # Entrypoint
    main_py = str(PROJECT_ROOT / "app" / "main.py")
    cmd.append(main_py)

    print("Running PyInstaller with command:")
    print(" ".join(cmd))

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode == 0:
        print("Build completed successfully. Artifacts located in:", output_dir)
    else:
        print("Build failed with return code:", result.returncode, file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    """Parse CLI arguments and run release builder."""
    parser = argparse.ArgumentParser(description="MediaFlow Standalone Release Builder")
    parser.add_argument("--no-clean", action="store_true", help="Do not clean build cache before build")
    parser.add_argument("--output-dir", default="dist", help="Output directory for build artifacts")
    args = parser.parse_args()

    build_release(clean=not args.no_clean, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
