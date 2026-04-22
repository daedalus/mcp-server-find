"""Pre-built DB snapshot bootstrap.

Downloads a gzipped SQLite file produced by a scheduled builder
and atomically installs it into the data dir. This replaces the ~11 min
cold-start sync with a ~5-10s download on first run.
"""

import gzip
import hashlib
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from mcpfinder.db import get_data_dir

DEFAULT_SNAPSHOT_BASE = "https://mcpfinder.dev/api/v1/snapshot"


class SnapshotManifest:
    """Snapshot manifest from the server."""

    def __init__(
        self,
        published_at: str,
        server_count: int,
        sha256: str,
        size_bytes: int,
        url: str,
        builder: str | None = None,
    ) -> None:
        self.published_at = published_at
        self.server_count = server_count
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.url = url
        self.builder = builder

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotManifest":
        return cls(
            published_at=data.get("publishedAt", ""),
            server_count=data.get("serverCount", 0),
            sha256=data.get("sha256", ""),
            size_bytes=data.get("sizeBytes", 0),
            url=data.get("url", ""),
            builder=data.get("builder"),
        )


class BootstrapResult:
    """Result of a bootstrap operation."""

    def __init__(
        self,
        ok: bool,
        reason: str | None = None,
        servers: int | None = None,
        published_at: str | None = None,
        bytes_downloaded: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.ok = ok
        self.reason = reason
        self.servers = servers
        self.published_at = published_at
        self.bytes_downloaded = bytes_downloaded
        self.duration_ms = duration_ms


async def fetch_snapshot_manifest(
    base_url: str = DEFAULT_SNAPSHOT_BASE,
) -> SnapshotManifest | None:
    """Fetch the snapshot manifest."""
    url = base_url.rstrip("/") + "/manifest.json"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0)
            if not response.is_success:
                return None
            data = response.json()
            return SnapshotManifest.from_dict(data)
    except Exception:
        return None


def _file_exists_non_empty(path: str) -> bool:
    """Check if file exists and is non-empty."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


async def bootstrap_from_snapshot(
    base_url: str | None = None,
    db_path: str | None = None,
    force: bool = False,
) -> BootstrapResult:
    """Download and install a snapshot database."""
    t0 = datetime.now(UTC)
    base = (base_url or DEFAULT_SNAPSHOT_BASE).rstrip("/")

    if db_path is None:
        db_path = os.path.join(get_data_dir(), "data.db")

    if not force and _file_exists_non_empty(db_path):
        return BootstrapResult(ok=False, reason="db-already-exists")

    manifest = await fetch_snapshot_manifest(base)
    if not manifest:
        return BootstrapResult(ok=False, reason="manifest-fetch-failed")

    data_url = (
        manifest.url
        if manifest.url.startswith("http")
        else f"{base}/{manifest.url.lstrip('/')}"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(data_url, timeout=120.0)
            if not response.is_success:
                return BootstrapResult(
                    ok=False, reason=f"download-failed-{response.status_code}"
                )

            content = await response.aread()
    except Exception as e:
        return BootstrapResult(ok=False, reason=f"download-failed: {e}")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    tmp_path = f"{db_path}.download.{os.getpid()}"

    try:
        decompressed = gzip.decompress(content)
    except Exception as e:
        return BootstrapResult(ok=False, reason=f"decompress-failed: {e}")

    hasher = hashlib.sha256()
    hasher.update(decompressed)
    got_sha = hasher.hexdigest()

    if manifest.sha256 and got_sha != manifest.sha256:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return BootstrapResult(
            ok=False,
            reason=f"sha256-mismatch (expected {manifest.sha256}, got {got_sha})",
        )

    try:
        with open(tmp_path, "wb") as f:
            f.write(decompressed)
        os.rename(tmp_path, db_path)
    except OSError as e:
        return BootstrapResult(ok=False, reason=f"install-failed: {e}")

    duration_ms = int((datetime.now(UTC) - t0).total_seconds() * 1000)

    return BootstrapResult(
        ok=True,
        servers=manifest.server_count,
        published_at=manifest.published_at,
        bytes_downloaded=len(content),
        duration_ms=duration_ms,
    )
