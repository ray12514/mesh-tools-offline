#!/usr/bin/env python3
"""Assemble a source-only transfer bundle on a connected or staging machine."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from releases import ROOT, RELEASES, archive_name, digest, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-dir", type=Path, metavar="DIR",
                        help="use previously downloaded release archives in DIR")
    parser.add_argument("--output", type=Path, default=Path("mesh-tools-offline.tar.gz"))
    args = parser.parse_args()
    output = args.output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(output.parent)) as tmp:
        bundle = Path(tmp) / "bundle.tar.gz"
        with tarfile.open(str(bundle), "w:gz", compresslevel=1) as tar:
            for name in ("README.md", "home.ini", "site.ini", "sources.json", "releases.py",
                         "prepare.py", "install.py", "build.sh", "modules.sh", "smoke.sh"):
                tar.add(str(ROOT / name), arcname="mesh-tools/" + name)
            for name, release in RELEASES.items():
                filename = archive_name(name)
                if args.from_dir:
                    source = args.from_dir / filename
                else:
                    source = Path(tmp) / filename
                    subprocess.run(["curl", "--fail", "--location", "--retry", "3",
                                    "--output", str(source), release["url"]], check=True)
                verify(name, source)
                print("Verified " + filename, flush=True)
                tar.add(str(source), arcname="mesh-tools/sources/" + filename)
        checksum = digest(bundle)
        receipt = Path(tmp) / "checksum"
        receipt.write_text("{}  {}\n".format(checksum, output.name))
        os.replace(str(bundle), str(output))
        os.replace(str(receipt), str(output) + ".sha256")
    print("Transfer {} and its .sha256 file.".format(output))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
