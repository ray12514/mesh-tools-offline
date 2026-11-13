"""The pinned release archives shared by the fetch and install commands."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
with (ROOT / "sources.json").open() as stream:
    RELEASES = json.load(stream)


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def archive_name(package):
    return RELEASES[package]["url"].rsplit("/", 1)[1]


def verify(package, archive):
    if digest(archive) != RELEASES[package]["sha256"]:
        raise ValueError("SHA-256 mismatch for {}".format(archive))
