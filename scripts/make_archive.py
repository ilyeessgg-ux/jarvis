"""Create the release zip from the one-folder PyInstaller build.

Compress-Archive is slow and can stall on large trees, so releases use
Python's zipfile module instead. Entries are rooted at the archive top level
(JARVIS.exe, _internal/, README.md, ...) so users can extract and run.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def make_archive(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise SystemExit(f"Source folder not found: {source}")
    if destination.exists():
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)

    files = 0
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source).as_posix()
            if path.is_dir():
                archive.write(path, relative + "/")
            else:
                archive.write(path, relative)
                files += 1

    size = destination.stat().st_size
    print(f"Archived {files} files to {destination} ({size / 1024 / 1024:.1f} MB)")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "Usage: make_archive.py <source-folder> <destination-zip>",
            file=sys.stderr,
        )
        return 2
    make_archive(Path(argv[1]), Path(argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
