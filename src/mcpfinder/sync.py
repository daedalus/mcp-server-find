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


def _canonical_name_token(s: str) -> str:
    """Strip common MCP-ish prefixes/suffixes for monorepo matching."""
    if not s:
        return ""
    t = s.lower()
    for _ in range(3):
        t = re.sub(r"^(mcp|server)+", "", t)
        t = re.sub(r"(mcp|server)+$", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


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


def _extract_repo_key(url: str | None) -> str | None:
    """Extract canonical owner/repo from code-host URL."""
    n = _normalize_repo_url(url)
    if not n:
        return None
    m = re.search(
        r"\b(?:github|gitlab|bitbucket|codeberg)\.(?:com|org|io)\/([^/]+)\/([^/?#]+)", n
    )
    return f"{m.group(1)}/{m.group(2)}" if m else None


def find_existing_server(
    conn: sqlite3.Connection,
    repo_url: str | None,
    package_identifier: str | None,
    registry_type: str | None,
    slug: str,
    name: str | None = None,
) -> str | None:
    """Find an existing server that should be considered the same project."""
    del registry_type  # Reserved for future use
    repo_key = _extract_repo_key(repo_url)

    if repo_key:
        tail = f"/{repo_key}"
        cursor = conn.execute(
            """SELECT id, slug, name, package_identifier FROM servers
               WHERE LOWER(repository_url) LIKE ? OR LOWER(repository_url) LIKE ?""",
            (f"%{tail}", f"%{tail}.git"),
        )
        candidates = cursor.fetchall()

        if len(candidates) == 1:
            return candidates[0]["id"]

        if len(candidates) > 1:
            if package_identifier:
                for c in candidates:
                    if (
                        c["package_identifier"]
                        and c["package_identifier"].lower()
                        == package_identifier.lower()
                    ):
                        return c["id"]
            if slug:
                for c in candidates:
                    if c["slug"] == slug:
                        return c["id"]
            if name:
                token = _canonical_name_token(name)
                if token:
                    for c in candidates:
                        ct = _canonical_name_token(c["name"])
                        if ct and (
                            ct == token or ct.endswith(token) or token.endswith(ct)
                        ):
                            return c["id"]
            return None

    if package_identifier:
        cursor = conn.execute(
            """SELECT id FROM servers
               WHERE LOWER(package_identifier) = LOWER(?)
               LIMIT 1""",
            (package_identifier,),
        )
        row = cursor.fetchone()
        if row:
            return row["id"]

    if slug:
        cursor = conn.execute(
            "SELECT id FROM servers WHERE slug = ? AND source != 'unknown' LIMIT 2",
            (slug,),
        )
        rows = cursor.fetchall()
        if len(rows) == 1:
            return rows[0]["id"]

    return None


def find_official_from_smithery_qualified_name(
    conn: sqlite3.Connection, qualified_name: str | None
) -> str | None:
    """Find Official mirror of a Smithery server."""
    if not qualified_name:
        return None
    tail = qualified_name.lower().replace("/", "-")
    tail = re.sub(r"[^a-z0-9-]", "", tail)
    if not tail:
        return None
    cursor = conn.execute(
        'SELECT id FROM servers WHERE LOWER(name) = ? AND source = "official" LIMIT 1',
        (f"ai.smithery/{tail}",),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


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


def merge_server_data(
    conn: sqlite3.Connection, existing_id: str, new_row: dict[str, Any]
) -> None:
    """Merge richer data from a new source into an existing server."""
    cursor = conn.execute("SELECT * FROM servers WHERE id = ?", (existing_id,))
    existing = cursor.fetchone()
    if not existing:
        return

    updates = []
    values = []

    if new_row.get("description") and len(new_row["description"]) > len(
        existing["description"] or ""
    ):
        updates.append("description = ?")
        values.append(new_row["description"])

    text_fields = [
        "repository_url",
        "remote_url",
        "icon_url",
        "transport_type",
        "registry_type",
        "package_identifier",
    ]
    for f in text_fields:
        if new_row.get(f) and not existing.get(f):
            updates.append(f"{f} = ?")
            values.append(new_row[f])

    if new_row.get("updated_at") and (
        not existing["updated_at"] or new_row["updated_at"] > existing["updated_at"]
    ):
        updates.append("updated_at = ?")
        values.append(new_row["updated_at"])
    if new_row.get("published_at") and not existing["published_at"]:
        updates.append("published_at = ?")
        values.append(new_row["published_at"])

    if new_row.get("env_vars"):
        merged_env_vars = _merge_json_arrays(
            existing["env_vars"], new_row["env_vars"], "name"
        )
        if merged_env_vars:
            updates.append("env_vars = ?")
            values.append(merged_env_vars)

    if new_row.get("raw_data"):
        merged_raw = _merge_raw_data(
            existing["raw_data"],
            new_row.get("raw_data"),
            new_row.get("source", "unknown"),
        )
        if merged_raw:
            updates.append("raw_data = ?")
            values.append(merged_raw)

    if updates:
        values.append(existing_id)
        conn.execute(f"UPDATE servers SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()


def _merge_json_arrays(
    existing_json: str | None, incoming_json: str | None, key: str
) -> str | None:
    """Merge two JSON arrays by key."""
    try:
        existing = json.loads(existing_json or "[]") if existing_json else []
        incoming = json.loads(incoming_json or "[]") if incoming_json else []
        merged = {}
        for item in existing + incoming:
            if isinstance(item, dict) and key in item:
                k = item[key]
                merged[k] = {**merged.get(k, {}), **item}
        return json.dumps(list(merged.values()))
    except (json.JSONDecodeError, TypeError):
        return None


def _merge_raw_data(
    existing_raw: str | None, incoming_raw: str | None, incoming_source: str
) -> str | None:
    """Merge raw data envelopes."""
    try:
        existing_parsed = json.loads(existing_raw) if existing_raw else None
        incoming_parsed = json.loads(incoming_raw) if incoming_raw else None

        if isinstance(existing_parsed, dict) and "bySource" in existing_parsed:
            envelope = existing_parsed
        else:
            envelope = {"primary": existing_parsed, "bySource": {}}

        if incoming_parsed:
            envelope["bySource"][incoming_source] = incoming_parsed
            if not envelope.get("primary"):
                envelope["primary"] = incoming_parsed

        return json.dumps(envelope)
    except (json.JSONDecodeError, TypeError):
        return None
