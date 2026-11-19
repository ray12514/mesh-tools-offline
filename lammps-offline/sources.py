"""Fetch an upstream release or verify a previously staged source archive."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"
API = "https://api.github.com/repos/lammps/lammps/releases"
RELEASE = re.compile(r"(?:stable|patch)_\d{1,2}[A-Z][a-z]{2}\d{4}(?:_update\d+)?")
FILES = (
    "README.md", "prepare.py", "sources.py", "install.py", "build.sh",
    "load-env.sh", "packages.cmake", "cmake/h200.cmake", "cmake/cray-link.sh",
    "smoke.sh", "smoke.sbatch", "in.smoke",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_sha256(path, expected):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        raise ValueError("Expected a 64-digit SHA-256 checksum")
    actual = sha256(path)
    if actual != expected.lower():
        raise ValueError(f"SHA-256 mismatch for {path}: expected {expected}, got {actual}")
    return actual


def release_tag(value):
    if not RELEASE.fullmatch(value):
        raise ValueError(f"Invalid LAMMPS release tag: {value!r}")
    return value


def request(url, output=None):
    command = ["curl", "-fsSL", "--retry", "3", "--connect-timeout", "20",
               "--proto", "=https", "--proto-redir", "=https"]
    if output is None:
        return subprocess.check_output(command + [url], text=True)
    subprocess.run(command + ["--output", str(output), url], check=True)


def download(release, directory):
    endpoint = "latest" if release == "latest" else "tags/" + release_tag(release)
    data = json.loads(request(f"{API}/{endpoint}"))
    if release == "latest" and not stable(data):
        releases = json.loads(request(f"{API}?per_page=100"))
        data = next((item for item in releases if stable(item)), None)
        if data is None:
            raise ValueError("No recent stable release found; pass a release tag")
    tag = release_tag(data["tag_name"])
    if release != "latest" and tag != release:
        raise ValueError(f"GitHub returned {tag} for requested tag {release}")

    filename = f"lammps-src-{tag.split('_', 1)[1]}.tar.gz"
    assets = {asset["name"]: asset for asset in data["assets"]}
    if filename not in assets:
        raise ValueError(f"No upstream source asset named {filename}; supply a local archive")
    asset = assets[filename]
    url = asset["browser_download_url"]
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        expected = digest.removeprefix("sha256:")
    elif "SHA256SUMS" in assets:
        sums = request(assets["SHA256SUMS"]["browser_download_url"])
        expected = next((line.split()[0] for line in sums.splitlines()
                         if len(line.split()) == 2 and line.split()[1].lstrip("*") == filename), "")
    else:
        expected = ""
    if not expected:
        raise ValueError(f"No upstream SHA-256 found for {filename}; supply a local archive")

    archive = directory / filename
    request(url, archive)
    actual = check_sha256(archive, expected)
    return archive, {"tag": tag, "archive": filename, "sha256": actual, "url": url}


def stable(release):
    return release["tag_name"].startswith("stable_") and not release["prerelease"]


def import_archive(path, release, expected, directory):
    tag = release_tag(release)
    archive = directory / f"lammps-src-{tag.split('_', 1)[1]}.tar.gz"
    shutil.copyfile(path, archive)
    actual = check_sha256(archive, expected) if expected else sha256(archive)
    return archive, {"tag": tag, "archive": archive.name, "sha256": actual, "url": None}


def staged_source(directory, release):
    receipt = directory / "source.json"
    if not receipt.is_file():
        raise ValueError(f"No staged source at {receipt}. Run prepare.py or pass --source and a tag.")
    source = json.loads(receipt.read_text())
    tag = release_tag(source["tag"])
    if release and tag != release:
        raise ValueError(f"Staged release is {tag}, requested {release}")
    filename = f"lammps-src-{tag.split('_', 1)[1]}.tar.gz"
    if source["archive"] != filename:
        raise ValueError(f"Unexpected source archive name in {receipt}")
    archive = directory / filename
    check_sha256(archive, source["sha256"])
    return archive, source


def write_bundle(output, archive, source, packages):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as work:
        work = Path(work)
        (work / "source.json").write_text(json.dumps(source, indent=2) + "\n")
        bundle = work / output.name
        with tarfile.open(bundle, "w:gz", compresslevel=1) as tar:
            for name in FILES:
                tar.add(packages if name == "packages.cmake" else ROOT / name,
                        arcname="lammps-offline/" + name)
            tar.add(archive, arcname="lammps-offline/sources/" + archive.name)
            tar.add(work / "source.json", arcname="lammps-offline/sources/source.json")
        checksum = work / (output.name + ".sha256")
        checksum.write_text(f"{sha256(bundle)}  {output.name}\n")
        os.replace(bundle, output)
        os.replace(checksum, output.with_name(checksum.name))
