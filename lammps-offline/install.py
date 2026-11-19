#!/usr/bin/env python3
"""Build and install one LAMMPS variant using CMake and the Cray drivers."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from sources import ROOT, SOURCES, download, import_archive, sha256, staged_source


def extract_source(archive, work, tag):
    if not hasattr(tarfile, "data_filter"):
        raise ValueError("Source extraction requires Python with tarfile.data_filter (e.g. Python 3.12)")
    unpack = work / "source"
    unpack.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(unpack, filter="data")
    sources = [entry for entry in unpack.iterdir() if (entry / "cmake/CMakeLists.txt").is_file()
               and (entry / "src/lammps.cpp").is_file()]
    if len(sources) != 1:
        raise ValueError("Expected one directory with LAMMPS CMake and source files in the archive")
    source = sources[0]
    version_header = (source / "src/version.h").read_text()
    version = re.search(r'^#define\s+LAMMPS_VERSION\s+"([^"]+)"', version_header, re.MULTILINE)
    update = re.search(r'^#define\s+LAMMPS_UPDATE\s+"Update (\d+)"', version_header, re.MULTILINE)
    expected = tag.split("_", 1)[1]
    actual = "".join(version[1].split()).lstrip("0") if version else ""
    if update:
        actual += "_update" + update[1]
    if actual != expected:
        raise ValueError(f"Source version {actual or 'unknown'} does not match release tag {tag}")
    return source


def offline_flags(source):
    """Disable the upstream DOWNLOAD_* options, including package-specific defaults."""
    cmake = source / "cmake"
    download_option = re.compile(r"\b(?i:option)\s*\(\s*(DOWNLOAD_[\w-]+)\b")
    options = {"DOWNLOAD_POTENTIALS"}
    for script in [cmake / "CMakeLists.txt", *cmake.rglob("*.cmake")]:
        options.update(download_option.findall(script.read_text(encoding="utf-8", errors="replace")))
    return ["-DFETCHCONTENT_FULLY_DISCONNECTED:BOOL=ON",
            "-DFETCHCONTENT_UPDATES_DISCONNECTED:BOOL=ON",
            *[f"-D{name}:BOOL=OFF" for name in sorted(options)]]


def build(args, work, stage):
    if args.source:
        archive, receipt = import_archive(args.source, args.release, args.sha256, work)
    elif args.online:
        archive, receipt = download(args.release or "latest", work)
    else:
        archive, receipt = staged_source(SOURCES, args.release)

    source = extract_source(archive, work, receipt["tag"])
    print(f"Building {receipt['tag']} ({args.compiler}/{args.target}); logs: {work}", flush=True)
    flags = offline_flags(source) if not args.online else []
    command = ["bash", str(ROOT / "build.sh"), args.compiler, args.target,
               str(source), str(work), str(args.prefix), str(stage),
               str(args.packages), str(args.jobs), "online" if args.online else "offline",
               args.machine, *flags]
    shutil.copyfile(args.packages, work / "packages.cmake")
    with (work / "build.log").open("w") as log:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, errors="replace", bufsize=1)
        with child.stdout:
            for line in child.stdout:
                log.write(line)
                print(line, end="", flush=True)
        if child.wait():
            raise ValueError(f"Build failed. See {log.name}")

    installed = stage / args.prefix.relative_to(args.prefix.anchor)
    executable = installed / args.executable
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"CMake did not stage an executable at {executable}")
    package_hash = sha256(work / "packages.cmake")
    if sha256(args.packages) != package_hash:
        raise ValueError(f"Package configuration changed during the build: {args.packages}")
    receipt.update({"compiler": args.compiler, "target": args.target, "prefix": str(args.prefix),
                    "executable": args.executable,
                    "packages_sha256": package_hash, "build_directory": str(work)})
    (installed / "build-info.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return installed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--online", action="store_true", help="resolve and download upstream source")
    mode.add_argument("--offline", action="store_true", help="use only staged source and dependencies")
    parser.add_argument("--release", help="upstream tag or latest (online default)")
    parser.add_argument("--source", type=Path, help="local source for --offline (requires a tag)")
    parser.add_argument("--sha256", help="expected SHA-256 for --source")
    parser.add_argument("--compiler", choices=("gnu", "cray"), required=True)
    parser.add_argument("--target", choices=("cpu", "gpu"), required=True)
    parser.add_argument("--machine", help="suffix for lmp (GPU default: kokkos_cuda_cray)")
    parser.add_argument("--prefix", type=Path, required=True, help="new variant installation directory")
    parser.add_argument("--packages", type=Path, default=ROOT / "packages.cmake")
    parser.add_argument("--build-root", type=Path, default=ROOT / "build", help="scratch parent for run logs and objects")
    parser.add_argument("--jobs", type=int, default=4, help="parallel build jobs (default: 4)")
    args = parser.parse_args()
    if args.offline and args.release == "latest":
        parser.error("Offline mode uses the staged release or an explicit tag")
    if args.source and (args.online or not args.release):
        parser.error("--source requires --offline and an explicit --release tag")
    if args.sha256 and not args.source:
        parser.error("--sha256 requires --source")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.machine is None:
        args.machine = "kokkos_cuda_cray" if args.target == "gpu" else ""
    if not re.fullmatch(r"[A-Za-z0-9_+-]*", args.machine):
        parser.error("--machine accepts letters, digits, underscores, plus signs, and hyphens")
    args.executable = "bin/lmp" + ("_" + args.machine if args.machine else "")

    args.packages = args.packages.expanduser().resolve(strict=True)
    # Preserve the final component to detect existing symlinks, including broken ones.
    prefix = args.prefix.expanduser().absolute()
    args.prefix = prefix.parent.resolve() / prefix.name
    args.build_root = args.build_root.expanduser().resolve()
    for path in (ROOT, args.prefix, args.build_root):
        if not re.fullmatch(r"/[A-Za-z0-9_./+@-]+", str(path)):
            parser.error(f"Use paths without spaces or shell punctuation: {path}")
    if args.prefix.exists() or args.prefix.is_symlink():
        raise ValueError(f"Install prefix already exists: {args.prefix}")

    args.prefix.parent.mkdir(parents=True, exist_ok=True)
    lock = args.prefix.with_name(args.prefix.name + ".install-lock")
    lock.mkdir()
    try:
        args.build_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f"{args.compiler}-{args.target}-", dir=args.build_root))
        # Stage onto the install filesystem so publication is one atomic rename.
        with tempfile.TemporaryDirectory(prefix=".lammps-stage-", dir=args.prefix.parent) as directory:
            installed = build(args, work, Path(directory))
            if args.prefix.exists() or args.prefix.is_symlink():
                raise ValueError(f"Install prefix already exists: {args.prefix}")
            installed.rename(args.prefix)
    finally:
        lock.rmdir()
    print(f"Installed {args.prefix / args.executable}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
