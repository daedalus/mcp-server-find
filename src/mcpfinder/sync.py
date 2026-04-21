"""Sync engine for fetching servers from multiple MCP registries."""

import json
import re
import sqlite3
from datetime import UTC
from typing import Any
from urllib.parse import urlparse

import httpx

from mcpfinder.categories import extract_keywords
from mcpfinder.db import get_last_sync_timestamp, update_sync_log

REGISTRY_BASE = "https://registry.modelcontextprotocol.io"
GLAMA_BASE = "https://glama.ai/api/mcp/v1"
SMITHERY_BASE = "https://registry.smithery.ai"
PAGE_LIMIT = 100


async def sync_official_registry(conn: sqlite3.Connection) -> int:
    """Sync servers from the Official MCP Registry."""
    last_sync = get_last_sync_timestamp(conn, "official")

    cursor: str | None = None
    total_upserted = 0

    async with httpx.AsyncClient() as client:
        while True:
            url = f"{REGISTRY_BASE}/v0.1/servers"
            params = {"version": "latest", "limit": PAGE_LIMIT}
            if last_sync:
                params["updated_since"] = last_sync
            if cursor:
                params["cursor"] = cursor

            response = await client.get(url, params=params)
            if not response.is_success:
                raise Exception(
                    f"Registry API error: {response.status_code} — {response.text}"
                )

            data = response.json()
            servers = data.get("servers", [])

            if not servers:
                break

            for entry in servers:
                _upsert_official_server(conn, entry)
                _merge_server_sources(conn, entry["server"]["name"], "official")

            total_upserted += len(servers)

            cursor = data.get("metadata", {}).get("nextCursor")
            if not cursor:
                break

            await _delay(100)

    update_sync_log(conn, "official", total_upserted)
    return total_upserted


def _upsert_official_server(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    """Insert or update an official registry server."""
    server = entry["server"]
    meta = entry.get("_meta", {})

    meta_key = None
    for k in meta:
        if "modelcontextprotocol" in k.lower():
            meta_key = k
            break

    meta_info = meta.get(meta_key, {}) if meta_key else {}
    pkg = server.get("packages", [{}])[0] if server.get("packages") else {}
    remote = server.get("remotes", [{}])[0] if server.get("remotes") else {}

    slug = _slugify(server["name"])
    keywords = extract_keywords(server["name"], server.get("description", ""))
    env_vars = pkg.get("environmentVariables", [])

    conn.execute(
        """INSERT INTO servers (
            id, slug, name, description, version, registry_type, package_identifier,
            transport_type, repository_url, repository_source, published_at, updated_at,
            status, popularity_score, categories, keywords, remote_url, has_remote,
            last_synced_at, sources, raw_data, env_vars, source, use_count, verified, icon_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            description = CASE WHEN length(excluded.description) > length(servers.description) THEN excluded.description ELSE servers.description END,
            version = excluded.version,
            registry_type = COALESCE(excluded.registry_type, servers.registry_type),
            package_identifier = COALESCE(excluded.package_identifier, servers.package_identifier),
            transport_type = COALESCE(excluded.transport_type, servers.transport_type),
            repository_url = COALESCE(excluded.repository_url, servers.repository_url),
            repository_source = COALESCE(excluded.repository_source, servers.repository_source),
            published_at = COALESCE(excluded.published_at, servers.published_at),
            updated_at = COALESCE(excluded.updated_at, servers.updated_at),
            status = excluded.status,
            keywords = excluded.keywords,
            remote_url = COALESCE(excluded.remote_url, servers.remote_url),
            has_remote = MAX(excluded.has_remote, servers.has_remote),
            last_synced_at = excluded.last_synced_at,
            raw_data = excluded.raw_data,
            env_vars = CASE WHEN length(excluded.env_vars) > length(servers.env_vars) THEN excluded.env_vars ELSE servers.env_vars END""",
        (
            server["name"],
            slug,
            server["name"],
            server.get("description", ""),
            server.get("version", ""),
            pkg.get("registryType"),
            pkg.get("identifier"),
            pkg.get("transport", {}).get("type"),
            _normalize_repo_url(server.get("repository", {}).get("url")),
            server.get("repository", {}).get("source"),
            meta_info.get("publishedAt"),
            meta_info.get("updatedAt"),
            meta_info.get("status", "active"),
            0,
            "[]",
            json.dumps(keywords),
            remote.get("url"),
            1 if remote else 0,
            _iso_now(),
            "[]",
            json.dumps(entry),
            json.dumps(env_vars),
            "official",
            0,
            0,
            None,
        ),
    )
    conn.commit()


async def sync_glama_registry(conn: sqlite3.Connection) -> int:
    """Sync servers from Glama registry."""
    cursor: str | None = None
    total_upserted = 0

    async with httpx.AsyncClient() as client:
        while True:
            url = f"{GLAMA_BASE}/servers"
            params = {"first": PAGE_LIMIT}
            if cursor:
                params["after"] = cursor

            response = await client.get(url, params=params)
            if not response.is_success:
                raise Exception(
                    f"Glama API error: {response.status_code} — {response.text}"
                )

            data = response.json()
            servers = data.get("servers", [])

            if not servers:
                break

            for entry in servers:
                _upsert_glama_server(conn, entry)

            total_upserted += len(servers)

            page_info = data.get("pageInfo", {})
            cursor = (
                page_info.get("endCursor") if page_info.get("hasNextPage") else None
            )
            if not cursor:
                break

            await _delay(100)

    update_sync_log(conn, "glama", total_upserted)
    return total_upserted


def _upsert_glama_server(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    """Insert or update a Glama server."""
    namespace = entry.get("namespace", "")
    name = f"{namespace}/{entry['name']}" if namespace else entry["name"]
    slug = _slugify(entry.get("slug", name))
    keywords = extract_keywords(name, entry.get("description", ""))

    env_vars = []
    env_schema = entry.get("environmentVariablesJsonSchema", {})
    if env_schema and isinstance(env_schema, dict):
        props = env_schema.get("properties", {})
        for key, val in props.items():
            env_vars.append(
                {"name": key, "description": val.get("description"), "isSecret": False}
            )

    raw_data = json.dumps(entry)
    conn.execute(
        """INSERT INTO servers (
            id, slug, name, description, version, registry_type, package_identifier,
            transport_type, repository_url, repository_source, published_at, updated_at,
            status, popularity_score, categories, keywords, remote_url, has_remote,
            last_synced_at, sources, raw_data, env_vars, source, use_count, verified, icon_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            description = CASE WHEN length(excluded.description) > length(servers.description) THEN excluded.description ELSE servers.description END,
            repository_url = COALESCE(excluded.repository_url, servers.repository_url),
            remote_url = COALESCE(excluded.remote_url, servers.remote_url),
            has_remote = MAX(excluded.has_remote, servers.has_remote),
            last_synced_at = excluded.last_synced_at,
            keywords = excluded.keywords,
            env_vars = CASE WHEN length(excluded.env_vars) > length(servers.env_vars) THEN excluded.env_vars ELSE servers.env_vars END""",
        (
            f"glama:{entry['id']}",
            slug,
            name,
            entry.get("description", ""),
            "",
            None,
            None,
            None,
            _normalize_repo_url(entry.get("repository", {}).get("url")),
            "github" if entry.get("repository", {}).get("url") else None,
            None,
            None,
            "active",
            0,
            "[]",
            json.dumps(keywords),
            entry.get("url"),
            1 if entry.get("url") else 0,
            _iso_now(),
            "[]",
            raw_data,
            json.dumps(env_vars),
            "glama",
            0,
            0,
            None,
        ),
    )
    conn.commit()

    _merge_server_sources(conn, f"glama:{entry['id']}", "glama")


async def sync_smithery_registry(conn: sqlite3.Connection) -> int:
    """Sync servers from Smithery registry."""
    page = 1
    total_upserted = 0

    async with httpx.AsyncClient() as client:
        while True:
            url = f"{SMITHERY_BASE}/servers"
            params = {"page": page, "pageSize": PAGE_LIMIT}

            response = await client.get(url, params=params)
            if not response.is_success:
                raise Exception(
                    f"Smithery API error: {response.status_code} — {response.text}"
                )

            data = response.json()
            servers = data.get("servers", [])

            if not servers:
                break

            for entry in servers:
                _upsert_smithery_server(conn, entry)

            total_upserted += len(servers)

            pagination = data.get("pagination", {})
            if page >= pagination.get("totalPages", 0):
                break
            page += 1

            await _delay(100)

    update_sync_log(conn, "smithery", total_upserted)
    return total_upserted


def _upsert_smithery_server(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    """Insert or update a Smithery server."""
    qualified_name = entry.get("qualifiedName", "")
    slug = _slugify(qualified_name)
    display_name = entry.get("displayName", qualified_name)
    keywords = extract_keywords(display_name, entry.get("description", ""))

    homepage = entry.get("homepage")
    repo_url = None
    repo_source = None
    if homepage:
        parsed = urlparse(homepage)
        if "github" in parsed.netloc or "gitlab" in parsed.netloc:
            repo_url = _normalize_repo_url(homepage)
            repo_source = "github"

    conn.execute(
        """INSERT INTO servers (
            id, slug, name, description, version, registry_type, package_identifier,
            transport_type, repository_url, repository_source, published_at, updated_at,
            status, popularity_score, categories, keywords, remote_url, has_remote,
            last_synced_at, sources, raw_data, env_vars, source, use_count, verified, icon_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            description = CASE WHEN length(excluded.description) > length(servers.description) THEN excluded.description ELSE servers.description END,
            repository_url = COALESCE(excluded.repository_url, servers.repository_url),
            remote_url = COALESCE(excluded.remote_url, servers.remote_url),
            has_remote = MAX(excluded.has_remote, servers.has_remote),
            last_synced_at = excluded.last_synced_at,
            keywords = excluded.keywords,
            use_count = MAX(excluded.use_count, servers.use_count),
            verified = MAX(excluded.verified, servers.verified),
            icon_url = COALESCE(excluded.icon_url, servers.icon_url)""",
        (
            f"smithery:{qualified_name}",
            slug,
            display_name,
            entry.get("description", ""),
            "",
            None,
            None,
            None,
            repo_url,
            repo_source,
            entry.get("createdAt"),
            entry.get("createdAt"),
            "active",
            0,
            "[]",
            json.dumps(keywords),
            f"https://registry.smithery.ai/servers/{qualified_name}"
            if entry.get("remote") and entry.get("isDeployed")
            else None,
            1 if entry.get("remote") and entry.get("isDeployed") else 0,
            _iso_now(),
            "[]",
            json.dumps(entry),
            "[]",
            "smithery",
            entry.get("useCount", 0),
            1 if entry.get("verified") else 0,
            entry.get("iconUrl"),
        ),
    )
    conn.commit()

    _merge_server_sources(conn, f"smithery:{qualified_name}", "smithery")


def _slugify(name: str) -> str:
    """Generate a slug from a server name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _normalize_repo_url(url: str | None) -> str | None:
    """Normalize a repository URL."""
    if not url:
        return None
    url = url.strip().lower()
    if not url:
        return None

    scp_match = re.match(r"^git@([^:]+):(.+)$", url)
    if scp_match:
        url = f"https://{scp_match.group(1)}/{scp_match.group(2)}"

    url = re.sub(r"\.git$", "", url)
    url = url.rstrip("/")
    return url if url else None


def _merge_server_sources(
    conn: sqlite3.Connection, server_id: str, new_source: str
) -> None:
    """Merge a source into a server's sources list."""
    cursor = conn.execute("SELECT sources FROM servers WHERE id = ?", (server_id,))
    row = cursor.fetchone()
    if not row:
        return

    try:
        sources = json.loads(row["sources"]) if row["sources"] else []
    except (json.JSONDecodeError, TypeError):
        sources = []

    if new_source not in sources:
        sources.append(new_source)
        sources.sort()
        conn.execute(
            "UPDATE servers SET sources = ? WHERE id = ?",
            (json.dumps(sources), server_id),
        )
        conn.commit()


async def _delay(ms: int) -> None:
    """Delay helper for rate limiting."""
    import asyncio

    await asyncio.sleep(ms / 1000)


def _iso_now() -> str:
    """Get current ISO timestamp."""
    from datetime import datetime

    return datetime.now(UTC).isoformat()
