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


def runtime_modules(record):
    loaded_line, *requested = record.read_text().splitlines()
    loaded = loaded_line.split(":")
    required = [next((name for name in loaded if name == module or
                      name.rpartition("/")[0] == module), module) for module in requested]
    required.extend(name for name in loaded if name.partition("/")[0] in
                    {"cpe", "gcc", "gcc-native", "cce"})
    if not all(re.fullmatch(r"[A-Za-z0-9_./+@-]+", name) for name in required):
        raise ValueError("Unexpected module name in the Cray build environment")
    return list(dict.fromkeys(required))


def write_modulefile(path, prefix, tag, compiler, target, required):
    path.parent.mkdir(parents=True)
    modules = " ".join(f"{{{name}}}" for name in required)
    path.write_text(
        "#%Module1.0\n"
        f"module-whatis {{LAMMPS {tag} ({compiler}/{target})}}\n"
        f"module-whatis {{Required modules: {' '.join(required)}}}\n"
        f"set required [list {modules}]\n"
        "if {[module-info mode load]} {\n"
        "    set missing {}\n"
        "    foreach name $required {\n"
        "        if {![is-loaded $name]} { lappend missing $name }\n"
        "    }\n"
        "    if {[llength $missing]} {\n"
        '        error "LAMMPS requires the following modules to be loaded first: [join $missing {, }]. '
        'Select the matching Cray environment, then retry."\n'
        "    }\n"
        "}\n"
        f"prepend-path PATH [file join {{{prefix}}} bin]\n",
        encoding="utf-8",
    )


def build(args, work, stage):
    if args.source:
        archive, receipt = import_archive(args.source, args.release, args.sha256, work)
    elif args.online:
        archive, receipt = download(args.release or "latest", work)
    else:
        archive, receipt = staged_source(SOURCES, args.release)

    tag = receipt["tag"]
    module_version = args.module_version or f"{tag}-{args.compiler}-{args.target}"
    module_name = Path("lammps") / module_version
    module_link = args.module_root / module_name if args.module_root else None
    if module_link:
        module_link.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(module_link):
            raise ValueError(f"Module path already exists: {module_link}")

    source = extract_source(archive, work, tag)
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
    module_path = Path("modulefiles") / module_name
    required = runtime_modules(work / "runtime-modules.txt")
    write_modulefile(installed / module_path, args.prefix, tag, args.compiler, args.target, required)
    receipt.update({"compiler": args.compiler, "target": args.target, "prefix": str(args.prefix),
                    "executable": args.executable,
                    "modulefile": str(module_path), "required_modules": required,
                    "packages_sha256": package_hash, "build_directory": str(work)})
    (installed / "build-info.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return installed, module_path, module_name, module_link, required


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
    parser.add_argument("--module-root", type=Path, help="also publish the modulefile in this MODULEPATH directory")
    parser.add_argument("--module-version", help="modulefile name under lammps/ (default: release-compiler-target)")
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
    if args.module_version is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", args.module_version):
        parser.error("--module-version must be a single module version name")
    args.executable = "bin/lmp" + ("_" + args.machine if args.machine else "")

    args.packages = args.packages.expanduser().resolve(strict=True)
    # Preserve the final component to detect existing symlinks, including broken ones.
    prefix = args.prefix.expanduser().absolute()
    args.prefix = prefix.parent.resolve() / prefix.name
    args.build_root = args.build_root.expanduser().resolve()
    if args.module_root:
        args.module_root = args.module_root.expanduser().resolve()
        if args.module_root == args.prefix / "modulefiles":
            args.module_root = None
        elif args.module_root == args.prefix or args.prefix in args.module_root.parents:
            parser.error("--module-root must be outside the install prefix")
    for path in filter(None, (ROOT, args.prefix, args.build_root, args.module_root)):
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
            installed, module_path, module_name, module_link, required = build(args, work, Path(directory))
            if args.prefix.exists() or args.prefix.is_symlink():
                raise ValueError(f"Install prefix already exists: {args.prefix}")
            installed.rename(args.prefix)
            if module_link:
                try:
                    module_link.symlink_to(args.prefix / module_path)
                except OSError:
                    args.prefix.rename(installed)
                    raise
    finally:
        lock.rmdir()
    print(f"Installed {args.prefix / args.executable}")
    module_root = args.module_root or args.prefix / "modulefiles"
    print(f"Load the required modules first: {' '.join(required)}")
    print(f"Then run: module use {module_root} && module load {module_name}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
