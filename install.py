#!/usr/bin/env python3
"""Build and publish Gmsh and ADMesh from the local release archives on Linux."""

import argparse
from configparser import ConfigParser, Error as ConfigError
from contextlib import ExitStack
import fcntl
import grp
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from releases import ROOT, RELEASES, archive_name, digest, verify


def run(command, **kwargs):
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def output(command, **kwargs):
    return run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
               universal_newlines=True, **kwargs).stdout.strip()


def directory(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Expected an absolute directory, got {!r}".format(value))
    return path.resolve()


def read_site(path):
    config = ConfigParser(interpolation=None)
    with path.open() as stream:
        config.read_file(stream)
    site = config["site"]
    tag = site["build_tag"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", tag):
        raise ValueError("Use a build_tag such as intel-2025.3 or gcc-13.3")
    if site.getint("jobs") < 1:
        raise ValueError("jobs must be a positive integer")
    return site


def shared_directory(path, gid):
    # Existing site-owned ancestors retain their group, ACLs and modes.
    if path.is_dir():
        return
    shared_directory(path.parent, gid)
    try:
        path.mkdir()
    except FileExistsError:
        if not path.is_dir():
            raise
    else:
        os.chown(str(path), -1, gid)
        path.chmod(0o2775)


def install_modes(prefix, gid):
    for parent, dirs, files in os.walk(str(prefix), followlinks=False):
        os.chown(parent, -1, gid)
        os.chmod(parent, 0o2775)
        for name in dirs + files:
            path = Path(parent, name)
            if path.is_symlink():
                os.lchown(str(path), -1, gid)
            elif path.is_file():
                # Libtool installs its .la metadata with the shared object's mode.
                executable = path.stat().st_mode & 0o111 and path.suffix != ".la"
                os.chown(str(path), -1, gid)
                path.chmod(0o775 if executable else 0o664)


def compiler(site, key, fallback):
    driver = site.get(key) or os.environ.get(key.upper()) or fallback
    path = shutil.which(driver)
    if not path:
        raise ValueError("Cannot find {} compiler {!r} in PATH".format(key, driver))
    return os.path.abspath(path)


def runtime_dirs(site, cc, cxx):
    result = []
    configured = site.get("runtime_dirs", "").strip()
    if configured:
        for entry in configured.split(":"):
            path = directory(entry)
            if not path.is_dir():
                raise ValueError("Missing runtime directory {}".format(path))
            result.append(str(path))
    # Query the selected drivers instead of recording a module's LD_LIBRARY_PATH.
    for driver, sonames in [(cxx, ("libimf.so", "libsvml.so", "libstdc++.so.6")),
                            (cc, ("libintlc.so.5", "libgcc_s.so.1"))]:
        for soname in sonames:
            query = subprocess.run([driver, "-print-file-name=" + soname],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   universal_newlines=True)
            path = Path(query.stdout.strip())
            if query.returncode == 0 and path.is_absolute() and path.is_file():
                result.append(str(path.parent.resolve()))
    return list(dict.fromkeys(result))


def prefix_for(site, package):
    return directory(site["install_root"]) / package / RELEASES[package]["version"] / site["build_tag"]


def module_name(site, package):
    return RELEASES[package]["version"] + "-" + site["build_tag"]


def check_link(link, target):
    if link.is_symlink() and link.resolve() == target:
        return
    if os.path.lexists(str(link)):
        raise ValueError("Module path already belongs to another install: {}".format(link))


def write_module(path, package, prefix):
    path.parent.mkdir()
    path.write_text('#%Module1.0\nmodule-whatis "{} {}"\nconflict {}\n'
                    'prepend-path PATH [file join {{{}}} bin]\n'.format(
                        package, RELEASES[package]["version"], package, prefix))


def check_runtime(package, prefix, paths, env):
    exe = prefix / "bin" / package
    private_lib = prefix / "lib" / "libadmesh.so.1"
    objects = [exe, private_lib] if package == "admesh" else [exe]
    report = []
    for obj in objects:
        dynamic = output(["readelf", "-d", obj], env=env)
        rpath = re.search(r"\(RPATH\).*?\[([^\]]*)\]", dynamic)
        if not rpath or "(RUNPATH)" in dynamic:
            raise ValueError("Expected DT_RPATH in {}".format(obj))
        dirs = rpath.group(1).split(":")
        if dirs[:len(paths)] != paths or "" in dirs:
            raise ValueError("Unexpected RPATH in {}: {}".format(obj, dirs))
        libs = output(["ldd", obj], env=env)
        if "not found" in libs:
            raise ValueError("Unresolved libraries for {}:\n{}".format(obj, libs))
        if package == "admesh" and obj == exe:
            match = re.search(r"libadmesh\.so\.1 => (.+?) \(0x", libs)
            if not match or Path(match.group(1)).resolve() != private_lib.resolve():
                raise ValueError("ADMesh selected the wrong libadmesh:\n" + libs)
        report.extend([str(obj), "RPATH=" + rpath.group(1), libs])
    expected = RELEASES[package]["version"]
    version = output([exe, "--version"], env=env)
    if version != (("ADMesh - version " if package == "admesh" else "") + expected):
        raise ValueError("Unexpected {} version: {}".format(exe, version))
    return "\n".join(report) + "\n"


def module_test(site, module_root, env):
    args = ["bash", ROOT / "modules.sh", module_root]
    for name in ("gmsh", "admesh"):
        args.extend([name + "/" + module_name(site, name), prefix_for(site, name)])
    run(args + [ROOT / "smoke.sh"], env=env)


def install(site, verify_only):
    module_root = directory(site["module_root"])
    env = dict(os.environ, LC_ALL="C", MESH_MODULE_INIT=site.get("module_init", ""))
    clean = {k: v for k, v in env.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
    run(["bash", ROOT / "modules.sh"], env=env)
    if verify_only:
        for name in RELEASES:
            prefix = prefix_for(site, name)
            record = json.loads((prefix / "build-info.json").read_text())
            print(check_runtime(name, prefix, record["rpath"], clean), flush=True)
        module_test(site, module_root, env)
        return

    for name in RELEASES:
        verify(name, ROOT / "sources" / archive_name(name))
    gid = grp.getgrnam(site["group"]).gr_gid if site.get("group") else os.getegid()
    cc, cxx = compiler(site, "cc", "cc"), compiler(site, "cxx", "c++")
    env.update(CC=cc, CXX=cxx)
    extra_dirs = runtime_dirs(site, cc, cxx)
    flags = {k: env.get(k, "") for k in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS")}
    common = dict(cc=cc, cc_version=output([cc, "--version"]).splitlines()[0],
                  cxx=cxx, cxx_version=output([cxx, "--version"]).splitlines()[0],
                  flags=flags, group=grp.getgrgid(gid).gr_name,
                  recipe_sha256=digest(ROOT / "build.sh"))
    for tool in ("cmake", "make", "tar", "readelf", "ldd", "awk"):
        if not shutil.which(tool):
            raise ValueError("Load or install {} before starting the offline build".format(tool))

    work = directory(site["build_root"])
    work.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="mesh-", dir=str(work)))
    print("Private build directory and logs: {}".format(run_dir), flush=True)
    with ExitStack() as locks:
        builds = []
        for name in sorted(RELEASES):
            prefix = prefix_for(site, name)
            versioned = module_name(site, name)
            target = prefix / "modules" / versioned
            link = module_root / name / versioned
            paths = list(dict.fromkeys([str(prefix / "lib")] + extra_dirs))
            # Configure/libtool and the compiler driver tokenize LDFLAGS as words.
            for item in paths + [str(run_dir)]:
                if not re.fullmatch(r"[/A-Za-z0-9._+@%=-]+", item):
                    raise ValueError("Use linker-safe paths without spaces or shell punctuation: " + item)
            shared_directory(prefix.parent, gid)
            shared_directory(link.parent, gid)
            lock_path = prefix.parent / (".install-" + site["build_tag"] + ".lock")
            lock = locks.enter_context(lock_path.open("a+"))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if lock_path.stat().st_uid == os.geteuid():
                os.fchown(lock.fileno(), -1, gid)
                os.fchmod(lock.fileno(), 0o664)
            check_link(link, target)
            record = dict(common, package=name, release=RELEASES[name], rpath=paths)
            if os.path.lexists(str(prefix)):
                info = prefix / "build-info.json"
                if prefix.is_symlink() or not info.is_file() or json.loads(info.read_text()) != record:
                    raise ValueError("Existing build differs at {}. Choose a new build_tag.".format(prefix))
            builds.append((name, prefix, link, target, paths, record))

        # Move only completed staging trees into place. If a test fails, release
        # this attempt's prefixes and links while preserving pre-existing installs.
        with ExitStack() as rollback:
            for name, prefix, link, target, paths, record in builds:
                log = run_dir / (name + ".log")
                if not prefix.exists():
                    pkg_work = run_dir / name
                    pkg_work.mkdir()
                    stage = Path(locks.enter_context(tempfile.TemporaryDirectory(
                        prefix=".stage-", dir=str(prefix.parent))))
                    staged = stage / str(prefix).lstrip("/")
                    rflags = "-Wl,--disable-new-dtags,-rpath," + ":".join(paths)
                    build_env = dict(env, LDFLAGS=(flags["LDFLAGS"] + " " + rflags).strip())
                    print("Building {} with {} (log {})".format(name, cc, log), flush=True)
                    with log.open("w") as stream:
                        run(["bash", ROOT / "build.sh", name, ROOT / "sources" / archive_name(name),
                             prefix, stage, site["jobs"]], cwd=str(pkg_work), env=build_env,
                            stdout=stream, stderr=subprocess.STDOUT)
                    write_module(staged / target.relative_to(prefix), name, prefix)
                    (staged / "build-info.json").write_text(json.dumps(record, indent=2) + "\n")
                    install_modes(staged, gid)
                    staged.rename(prefix)
                    rollback.callback(prefix.rename, staged)
                report = check_runtime(name, prefix, paths, clean)
                (run_dir / (name + "-linkage.txt")).write_text(report)
                print("Verified {} {}".format(name, RELEASES[name]["version"]), flush=True)

            preview = run_dir / "modulefiles"
            for name, prefix, link, target, paths, record in builds:
                test_link = preview / name / link.name
                test_link.parent.mkdir(parents=True)
                test_link.symlink_to(target)
            module_test(site, preview, env)
            for name, prefix, link, target, paths, record in builds:
                check_link(link, target)
                if not link.is_symlink():
                    link.symlink_to(target)
                    rollback.callback(link.unlink)
            module_test(site, module_root, env)
            rollback.pop_all()
        for name, prefix, link, target, paths, record in builds:
            print("{} -> {}".format(link, target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="path to the target site's INI file")
    parser.add_argument("--verify-only", action="store_true",
                        help="check published builds and rerun the module/mesh test")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise ValueError("Run the installer on the target Linux system")
    install(read_site(args.config), args.verify_only)


if __name__ == "__main__":
    try:
        main()
    except BlockingIOError:
        sys.exit("Another installer holds this build's lock. Retry when it finishes.")
    except (OSError, ValueError, KeyError, ConfigError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
