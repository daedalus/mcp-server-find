"""Build-time enrichment passes.

These are costly probes that fit inside a cron-driven snapshot builder
but shouldn't run in the latency-sensitive client sync path.
"""

import json
import sqlite3

import httpx


class EnrichResult:
    """Result of an enrichment pass."""

    def __init__(
        self,
        probed: int = 0,
        repo_found: int = 0,
        merged: int = 0,
        rate_limited: int = 0,
        errors: int = 0,
        duration_ms: int = 0,
    ) -> None:
        self.probed = probed
        self.repo_found = repo_found
        self.merged = merged
        self.rate_limited = rate_limited
        self.errors = errors
        self.duration_ms = duration_ms


class DeprecationEnrichResult:
    """Result of deprecation enrichment."""

    def __init__(
        self,
        npm: EnrichResult,
        github: EnrichResult,
        flagged: int = 0,
    ) -> None:
        self.npm = npm
        self.github = github
        self.flagged = flagged


async def enrich_smithery_repo_urls(
    conn: sqlite3.Connection,
    token: str | None = None,
    concurrency: int = 8,
    limit: int | None = None,
) -> EnrichResult:
    """Enrich Smithery servers with GitHub repo URLs.

    For every Smithery-only row whose qualifiedName looks like owner/name
    but has no repository_url, probe GitHub for github.com/owner/name.
    """
    import os

    result = EnrichResult()
    token = token or os.environ.get("GITHUB_TOKEN")

    if not token:
        import sys

        sys.stderr.write(
            "[enrich] GITHUB_TOKEN not set — skipping Smithery repo enrichment\n"
        )
        return result

    sql = """SELECT id, raw_data, slug, name, package_identifier, registry_type
              FROM servers
              WHERE source = 'smithery'
                AND (repository_url IS NULL OR repository_url = '')"""
    if limit:
        sql += f" LIMIT {limit}"

    cursor = conn.execute(sql)
    rows = cursor.fetchall()

    queue = []
    for r in rows:
        try:
            raw = json.loads(r["raw_data"] or "{}")
            qn = raw.get("qualifiedName")
        except (json.JSONDecodeError, TypeError):
            qn = None

        if not qn or "/" not in qn:
            continue
        owner, repo = qn.split("/", 1)
        if not owner or not repo:
            continue
        if not owner.replace("_", "").replace("-", "").isalnum():
            continue
        queue.append(
            {
                "id": r["id"],
                "owner": owner,
                "repo": repo,
                "slug": r["slug"],
                "name": r["name"],
            }
        )

    result.probed = len(queue)
    if not queue:
        return result

    headers = {
        "authorization": f"Bearer {token}",
        "accept": "application/vnd.github+json",
        "user-agent": "mcp-server-find-builder",
        nonlocal result

        repo_url = f"https://github.com/{item['owner']}/{item['repo']}".lower()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.github.com/repos/{item['owner']}/{item['repo']}",
                    headers=headers,
                    timeout=10.0,
                )
                if response.status_code == 403:
                    result.rate_limited += 1
                    return
                if response.status_code == 429:
                    result.rate_limited += 1
                    return
                if response.status_code == 404:
                    return
                if not response.is_success:
                    result.errors += 1
                    return

                result.repo_found += 1

                conn.execute(
                    "UPDATE servers SET repository_url = ? WHERE id = ?",
                    (repo_url, item["id"]),
                )
                conn.commit()
        except Exception:
            result.errors += 1

    import asyncio

    tasks = [probe_one(item) for item in queue]
    await asyncio.gather(*tasks, return_exceptions=True)

    return result


async def enrich_deprecation_flags(
    conn: sqlite3.Connection,
    token: str | None = None,
    npm_concurrency: int = 24,
    github_concurrency: int = 8,
    limit: int | None = None,
) -> DeprecationEnrichResult:
    """Probe external sources to flag servers that are end-of-life.

    Checks:
    - npm: fetches registry.npmjs.org/<pkg> and marks deprecated packages
    - GitHub: fetches api.github.com/repos/<owner>/<name> and marks archived repos
    """
    import os

    token = token or os.environ.get("GITHUB_TOKEN")
    npm_result = await _probe_npm_deprecations(conn, npm_concurrency, limit)
    github_result = await _probe_github_archived(conn, token, limit)

    return DeprecationEnrichResult(
        npm=npm_result,
        github=github_result,
        flagged=npm_result.flagged + github_result.flagged,
    )


async def _probe_npm_deprecations(
    conn: sqlite3.Connection,
    concurrency: int = 24,
    limit: int | None = None,
) -> EnrichResult:
    """Probe npm for deprecated packages."""
    result = EnrichResult()

    sql = """SELECT id, package_identifier
             FROM servers
             WHERE registry_type = 'npm'
               AND package_identifier IS NOT NULL
               AND package_identifier != ''
               AND deprecated_npm IS NULL"""
    if limit:
        sql += f" LIMIT {limit}"

    cursor = conn.execute(sql)
    rows = cursor.fetchall()

    result.probed = len(rows)
    if not rows:
        return result

    async def probe(row: dict[str, str]) -> None:
        nonlocal result

        try:
            async with httpx.AsyncClient() as client:
                pkg_id = row["package_identifier"].replace("@", "%40")
                response = await client.get(
                    f"https://registry.npmjs.org/{pkg_id}",
                    timeout=10.0,
                )
                if response.status_code == 429:
                    result.rate_limited += 1
                    return
                if response.status_code == 404:
                    conn.execute(
                        "UPDATE servers SET deprecated_npm = 1 WHERE id = ?",
                        (row["id"],),
                    )
                    result.flagged += 1
                    return
                if not response.is_success:
                    result.errors += 1
                    return

                data = response.json()
                latest = data.get("dist-tags", {}).get("latest")
                deprecated = bool(
                    data.get("time", {}).get("unpublished")
                    or (
                        latest
                        and data.get("versions", {}).get(latest, {}).get("deprecated")
                    )
                )
                conn.execute(
                    "UPDATE servers SET deprecated_npm = ? WHERE id = ?",
                    (1 if deprecated else 0, row["id"]),
                )
                conn.commit()
                if deprecated:
                    result.flagged += 1
        except Exception:
            result.errors += 1

    import asyncio

    tasks = [probe(row) for row in rows]
    await asyncio.gather(*tasks, return_exceptions=True)

    return result


async def _probe_github_archived(
    conn: sqlite3.Connection,
    token: str | None = None,
    limit: int | None = None,
) -> EnrichResult:
    """Probe GitHub for archived repositories."""
    import re

    result = EnrichResult()

    if not token:
        import sys

        sys.stderr.write(
            "[enrich] GITHUB_TOKEN not set — skipping archived-repo enrichment\n"
        )
        return result

    sql = """SELECT id, repository_url
             FROM servers
             WHERE repository_url LIKE 'https://github.com/%'
               AND archived_repo IS NULL"""
    if limit:
        sql += f" LIMIT {limit}"

    cursor = conn.execute(sql)
    rows = cursor.fetchall()

    result.probed = len(rows)
    if not rows:
        return result

    headers = {
        "authorization": f"Bearer {token}",
        "accept": "application/vnd.github+json",
        "user-agent": "mcp-server-find-builder",
        nonlocal result

        match = re.match(r"https://github.com/([^/]+)/([^/#?]+)", row["repository_url"])
        if not match:
            return
        owner, repo_raw = match.groups()
        repo = repo_raw.replace(".git", "")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=headers,
                    timeout=10.0,
                )
                if response.status_code == 403:
                    result.rate_limited += 1
                    return
                if response.status_code == 429:
                    result.rate_limited += 1
                    return
                if response.status_code == 404:
                    conn.execute(
                        "UPDATE servers SET archived_repo = 1 WHERE id = ?",
                        (row["id"],),
                    )
                    result.flagged += 1
                    return
                if not response.is_success:
                    result.errors += 1
                    return

                data = response.json()
                archived = bool(data.get("archived"))
                conn.execute(
                    "UPDATE servers SET archived_repo = ? WHERE id = ?",
                    (1 if archived else 0, row["id"]),
                )
                conn.commit()
                if archived:
                    result.flagged += 1
        except Exception:
            result.errors += 1

    import asyncio

    tasks = [
        probe({"id": r["id"], "repository_url": r["repository_url"]}) for r in rows
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    return result
