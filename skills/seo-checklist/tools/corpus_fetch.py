"""Fetch and extract pinned npm package corpora with a shared local cache."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
from collections.abc import Callable
from pathlib import PurePosixPath


HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".calibration-cache")


def package_basename(package: str) -> str:
    return package.rsplit("/", 1)[-1]


def tarball_url(package: str, version: str) -> str:
    base = package_basename(package)
    return f"https://registry.npmjs.org/{package}/-/{base}-{version}.tgz"


def _cache_path(package: str, version: str, cache_dir: str) -> str:
    safe = package.replace("@", "").replace("/", "-")
    return os.path.join(cache_dir, f"{safe}-{version}.tgz")


def _fetch(package: str, version: str, cache_dir: str,
           max_response_bytes: int) -> bytes:
    path = _cache_path(package, version, cache_dir)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()

    scripts = os.path.join(os.path.dirname(HERE), "scripts")
    sys.path.insert(0, scripts)
    from lib.safe_http import safe_get

    print(f"fetching {package}@{version}", file=sys.stderr)
    response = safe_get(
        tarball_url(package, version),
        timeout=60,
        max_response_bytes=max_response_bytes,
    )
    data = response.content
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return data


def fetch_package(
    package: str,
    version: str,
    include: Callable[[str], bool],
    *,
    cache_dir: str = CACHE,
    max_response_bytes: int = 64 * 1024 * 1024,
) -> tuple[dict, dict[str, bytes]]:
    """Return a hashed manifest and selected regular files from a pinned tarball."""
    archive = _fetch(package, version, cache_dir, max_response_bytes)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile() or not include(member.name):
                continue
            handle = tf.extractfile(member)
            if handle is not None:
                files[member.name] = handle.read()
    manifest = {
        "package": package,
        "version": version,
        "sha256": hashlib.sha256(archive).hexdigest(),
        "file_count": len(files),
    }
    return manifest, files


def display_path(package: str, version: str, member_name: str) -> str:
    parts = PurePosixPath(member_name).parts
    if parts and parts[0] == "package":
        parts = parts[1:]
    return str(PurePosixPath(f"{package_basename(package)}-{version}", *parts))
