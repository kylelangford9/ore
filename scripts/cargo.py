"""Run cargo for this repo.

On Kyle's PC (Windows, no Visual Studio) this loads the portable MSVC toolchain first and puts
build output on D:, one target folder per checkout so worktrees never wait on each other's lock:

    python scripts/cargo.py check --workspace
    python scripts/cargo.py build -p ore-cli --release

Target: D:\\Build Artifacts\\ore\\target\\<checkout folder name>. Elsewhere it runs cargo as is.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SETUP = r"C:\Users\NSF\dev-tools\apr-msvc\msvc\setup_x64.bat"
TARGET_ROOT = pathlib.Path(r"D:\Build Artifacts\ore\target")


def quote(a: str) -> str:
    return a if a and not any(c in a for c in ' "&|<>^') else '"' + a.replace('"', '\\"') + '"'


def main() -> int:
    if os.name != "nt":
        return subprocess.run(["cargo", *sys.argv[1:]], cwd=REPO).returncode
    if not pathlib.Path("D:\\").exists():
        print("D: is not available; refusing to fall back to C:", file=sys.stderr)
        return 2
    target = TARGET_ROOT / REPO.name
    target.mkdir(parents=True, exist_ok=True)
    cargo = pathlib.Path(os.path.expandvars(r"%USERPROFILE%\.cargo\bin\cargo.exe"))
    bat = pathlib.Path(tempfile.gettempdir()) / f"ore-cargo-{os.getpid()}.cmd"
    bat.write_text(
        "@echo off\r\n"
        f'call "{SETUP}" >nul || exit /b 90\r\n'
        f'cd /d "{REPO}" || exit /b 91\r\n'
        f'"{cargo}" {" ".join(quote(a) for a in sys.argv[1:])}\r\n',
        encoding="utf-8",
    )
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    env.setdefault("CARGO_BUILD_JOBS", "6")
    try:
        return subprocess.run(f'cmd /d /c "{bat}"', env=env).returncode
    finally:
        bat.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
