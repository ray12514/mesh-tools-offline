#!/usr/bin/env python3
"""Prepare the LAMMPS scripts and a verified source archive for offline transfer."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from sources import ROOT, download, import_archive, write_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", nargs="?", default="latest", help="latest or an upstream tag")
    parser.add_argument("--source", type=Path, help="local source archive (requires a release tag)")
    parser.add_argument("--sha256", help="expected SHA-256 for --source")
    parser.add_argument("--packages", type=Path, default=ROOT / "packages.cmake",
                        help="carry this CMake package file in the bundle")
    parser.add_argument("--output", type=Path, default=Path("dist/lammps-offline.tar.gz"))
    args = parser.parse_args()
    if args.source and args.release == "latest":
        parser.error("--source requires an explicit release tag")
    if args.sha256 and not args.source:
        parser.error("--sha256 requires --source")

    with tempfile.TemporaryDirectory(prefix="lammps-source-") as directory:
        if args.source:
            archive, source = import_archive(args.source, args.release, args.sha256, Path(directory))
        else:
            archive, source = download(args.release, Path(directory))
        write_bundle(args.output, archive, source, args.packages)
    print(f"Prepared {source['tag']}: {args.output} and {args.output}.sha256")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
