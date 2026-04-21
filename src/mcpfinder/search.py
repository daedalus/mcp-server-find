"""Search engine using SQLite FTS5 for MCP server discovery."""

import json
import re
import sqlite3
from datetime import UTC
from typing import Any

from mcpfinder.categories import categorize_server
from mcpfinder.types import (
    ConfidenceBreakdown,
    RegistryEnvVar,
    SearchResult,
    ServerDetail,
    ToolSummary,
    TrustSignals,
)

SEARCH_ALIASES = {
    "gh": "github",
    "gl": "gitlab",
    "bb": "bitbucket",
    "git": "git github",
    "pg": "postgres postgresql",
    "db": "database",
    "mysql": "mysql database",
    "mongo": "mongodb",
    "redis": "redis cache",
    "sql": "sql database",
    "k8s": "kubernetes",
    "aws": "amazon aws",
    "gcp": "google cloud",
    "az": "azure microsoft",
    "cf": "cloudflare",
    "js": "javascript nodejs",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "rs": "rust",
    "email": "email smtp gmail",
    "msg": "message messaging",
    "llm": "language model ai",
    "ml": "machine learning",
    "cv": "computer vision",
    "fs": "filesystem file",
    "ci": "continuous integration",
    "cd": "continuous deployment",
    "s3": "amazon s3 storage",
}


def find_server_by_name_or_slug(
    conn: sqlite3.Connection, name_or_slug: str
) -> dict[str, Any] | None:
    """Find a server by name, slug, or fuzzy match."""
    query = name_or_slug.strip()
    if not query:
        return None

    cursor = conn.execute(
        """SELECT * FROM servers
           WHERE id = ? OR slug = ? OR name = ? OR name LIKE ?
           LIMIT 1""",
        (query, query, query, f"%/{query}"),
    )
    row = cursor.fetchone()
    if row:
        return dict(row)

    pattern = f"%{query}%"
    cursor = conn.execute(
        """SELECT * FROM servers
           WHERE LOWER(name) LIKE ? COLLATE NOCASE
              OR LOWER(slug) LIKE ? COLLATE NOCASE
           ORDER BY use_count DESC
           LIMIT 50""",
        (pattern.lower(), pattern.lower()),
    )
    rows = cursor.fetchall()

    if not rows:
        sanitized = _sanitize_fts_query(query)
        if sanitized:
            cursor = conn.execute(
                """SELECT s.* FROM servers_fts fts
                   JOIN servers s ON s.rowid = fts.rowid
                   WHERE servers_fts MATCH ?
                   ORDER BY rank
                   LIMIT 1""",
                (sanitized,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    q_lower = query.lower()
    scored = []

    for r in rows:
        name_lower = r["name"].lower()
        slug_lower = r["slug"].lower()
        score = 1000

        for field in [name_lower, slug_lower]:
            if not field:
                continue
            pos = field.find(q_lower)
            if pos == -1:
                continue

            last_segment = field.split("/")[-1] if "/" in field else field
            seg_pos = last_segment.find(q_lower)

            if last_segment == q_lower:
                score = min(score, 0)
            elif seg_pos == 0:
                score = min(score, 10)
            elif pos > 0 and field[pos - 1] in "-_/":
                score = min(score, 20 + pos)
            else:
                score = min(score, 50 + pos)

        scored.append((r, score))

    scored.sort(key=lambda x: (x[1], -x[0]["use_count"], len(x[0]["name"])))
    return dict(scored[0][0]) if scored else None


def search_servers(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    filters: dict[str, str] | None = None,
) -> list[SearchResult]:
    """Search for MCP servers using FTS5 full-text search."""
    filters = filters or {}

    expanded_query, has_alias = _expand_aliases(query)
    sanitized = _sanitize_fts_query(expanded_query, has_alias)

    if not sanitized:
        return _get_popular_servers(conn, limit, filters)

    name_match_terms = [
        w for w in re.sub(r"[^\w\s-]", " ", expanded_query).split() if len(w) > 1
    ]
    name_match_clauses = " + ".join(
        f"CASE WHEN LOWER(s.name) LIKE :nm{i} THEN 5.0 ELSE 0 END"
        for i, _ in enumerate(name_match_terms)
    )

    sql = f"""SELECT s.*,
                  (rank * -1) as fts_relevance,
                  ({name_match_clauses or "0"}) +
                  (rank * -1) * 0.3 +
                  (CASE WHEN s.use_count > 0 THEN log(s.use_count + 1) ELSE 0 END) * 0.2 +
                  (CASE WHEN s.sources LIKE '%official%' THEN 3.0
                   WHEN s.verified = 1 THEN 1.5
                   ELSE 0 END) * 0.15 as combined_score
           FROM servers_fts fts
           JOIN servers s ON s.rowid = fts.rowid
           WHERE servers_fts MATCH :query"""

    params: dict[str, Any] = {"query": sanitized, "limit": limit}

    if filters.get("transportType") and filters["transportType"] != "any":
        sql += " AND s.transport_type = :transportType"
        params["transportType"] = filters["transportType"]

    if filters.get("registryType") and filters["registryType"] != "any":
        sql += " AND s.registry_type = :registryType"
        params["registryType"] = filters["registryType"]

    if filters.get("registrySource") and filters["registrySource"] != "any":
        sql += " AND s.sources LIKE :registrySource"
        params["registrySource"] = f"%{filters['registrySource']}%"

    for i, term in enumerate(name_match_terms):
        params[f"nm{i}"] = f"%{term.lower()}%"

    sql += " ORDER BY combined_score DESC LIMIT :limit"

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    return [_format_search_result(dict(row), idx) for idx, row in enumerate(rows)]


def _get_popular_servers(
    conn: sqlite3.Connection, limit: int, filters: dict[str, str] | None = None
) -> list[SearchResult]:
    """Get most popular servers for empty query."""
    sql = "SELECT * FROM servers WHERE status = 'active'"
    params: dict[str, Any] = {"limit": limit}

    if filters and filters.get("registrySource") and filters["registrySource"] != "any":
        sql += " AND sources LIKE :registrySource"
        params["registrySource"] = f"%{filters['registrySource']}%"

    sql += """ ORDER BY
        CASE WHEN sources LIKE '%official%' THEN 0 ELSE 1 END,
        CASE WHEN verified = 1 THEN 0 ELSE 1 END,
        use_count DESC,
        updated_at DESC NULLS LAST
        LIMIT :limit"""

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    return [_format_search_result(dict(row), idx) for idx, row in enumerate(rows)]


def _expand_aliases(query: str) -> tuple[str, bool]:
    """Expand a query using the alias dictionary."""
    words = query.lower().strip().split()
    has_alias = False
    expanded = []

    for w in words:
        if w in SEARCH_ALIASES:
            has_alias = True
            expanded.append(SEARCH_ALIASES[w])
        else:
            expanded.append(w)

    return " ".join(expanded), has_alias


def _sanitize_fts_query(query: str, use_or: bool = False) -> str:
    """Sanitize a query string for FTS5."""
    words = re.sub(r"[^\w\s-]", " ", query).split()
    words = [w for w in words if w]

    if not words:
        return ""

    quoted = [f'"{w}"' for w in words]
    return " OR ".join(quoted) if use_or else " ".join(quoted)


def _format_search_result(row: dict[str, Any], idx: int) -> SearchResult:
    """Format a database row into a SearchResult."""
    try:
        sources = json.loads(row.get("sources", "[]")) if row.get("sources") else []
    except (json.JSONDecodeError, TypeError):
        sources = []

    warning_flags = _get_warning_flags(row, sources)
    confidence_breakdown = _get_confidence_breakdown(row, sources, warning_flags)
    tools_exposed = _extract_tools(row)

    return SearchResult(
        name=row["name"],
        description=row["description"],
        version=row["version"],
        registry_type=row["registry_type"],
        package_identifier=row["package_identifier"],
        transport_type=row["transport_type"],
        repository_url=row["repository_url"],
        has_remote=bool(row.get("has_remote")),
        rank=idx + 1,
        sources=sources,
        use_count=row.get("use_count", 0),
        verified=bool(row.get("verified")),
        icon_url=row["icon_url"],
        updated_at=row["updated_at"],
        published_at=row["published_at"],
        source_count=len(sources),
        confidence_score=confidence_breakdown.score,
        confidence_breakdown=confidence_breakdown,
        recommendation_reason=_get_recommendation_reason(row, sources),
        warning_flags=warning_flags,
        trust_signals=_get_trust_signals(row, sources),
        freshness_days=_get_freshness_days(row),
        freshness_label=_get_freshness_label(_get_freshness_days(row)),
        install_complexity=_get_install_complexity(row, [], tools_exposed),
        secret_count=0,
        capability_count=len(tools_exposed),
    )


def get_server_details(
    conn: sqlite3.Connection, name_or_slug: str
) -> ServerDetail | None:
    """Get detailed information about a specific server."""
    row = find_server_by_name_or_slug(conn, name_or_slug)
    if not row:
        return None

    try:
        env_vars = json.loads(row.get("env_vars", "[]")) if row.get("env_vars") else []
        env_vars = [
            RegistryEnvVar(
                name=v.get("name", ""),
                description=v.get("description"),
                format=v.get("format"),
                is_secret=v.get("isSecret", False),
            )
            for v in env_vars
        ]
    except (json.JSONDecodeError, TypeError):
        env_vars = []

    try:
        categories = (
            json.loads(row.get("categories", "[]")) if row.get("categories") else []
        )
    except (json.JSONDecodeError, TypeError):
        categories = []

    if not categories:
        categories = categorize_server(row["name"], row["description"])

    try:
        sources = json.loads(row.get("sources", "[]")) if row.get("sources") else []
    except (json.JSONDecodeError, TypeError):
        sources = []

    warning_flags = _get_warning_flags(row, sources)
    confidence_breakdown = _get_confidence_breakdown(row, sources, warning_flags)
    tools_exposed = _extract_tools(row)

    return ServerDetail(
        name=row["name"],
        description=row["description"],
        version=row["version"],
        registry_type=row["registry_type"],
        package_identifier=row["package_identifier"],
        transport_type=row["transport_type"],
        repository_url=row["repository_url"],
        repository_source=row["repository_source"],
        published_at=row["published_at"],
        updated_at=row["updated_at"],
        status=row.get("status", "active"),
        has_remote=bool(row.get("has_remote")),
        remote_url=row["remote_url"],
        categories=categories,
        environment_variables=env_vars,
        sources=sources,
        use_count=row.get("use_count", 0),
        verified=bool(row.get("verified")),
        icon_url=row["icon_url"],
        source_count=len(sources),
        confidence_score=confidence_breakdown.score,
        confidence_breakdown=confidence_breakdown,
        recommendation_reason=_get_recommendation_reason(row, sources),
        warning_flags=warning_flags,
        trust_signals=_get_trust_signals(row, sources, env_vars),
        freshness_days=_get_freshness_days(row),
        freshness_label=_get_freshness_label(_get_freshness_days(row)),
        install_complexity=_get_install_complexity(row, env_vars, tools_exposed),
        secret_count=sum(1 for v in env_vars if v.is_secret),
        capability_count=len(tools_exposed),
        tools_exposed=tools_exposed,
    )


def _extract_tools(row: dict[str, Any]) -> list[ToolSummary]:
    """Extract tools from raw data."""
    try:
        raw = json.loads(row.get("raw_data", "{}")) if row.get("raw_data") else {}
    except json.JSONDecodeError:
        return []

    tools: dict[str, ToolSummary] = {}

    for source_key, source_data in raw.items():
        if not isinstance(source_data, dict):
            continue

        if "tools" in source_data and isinstance(source_data["tools"], list):
            for tool in source_data["tools"]:
                if not isinstance(tool, dict):
                    continue
                name = tool.get("name") or tool.get("id")
                if name and name not in tools:
                    tools[name] = ToolSummary(
                        name=name,
                        description=tool.get("description"),
                        kind="tool",
                    )

        if "capabilities" in source_data and isinstance(
            source_data["capabilities"], list
        ):
            for cap in source_data["capabilities"]:
                if not isinstance(cap, dict):
                    continue
                name = cap.get("name") or cap.get("id")
                if name and name not in tools:
                    tools[name] = ToolSummary(
                        name=name,
                        description=cap.get("description"),
                        kind=cap.get("type", "unknown"),
                    )

    return list(tools.values())


def _get_warning_flags(row: dict[str, Any], sources: list[str]) -> list[str]:
    """Get warning flags."""
    warnings = []

    if len(sources) <= 1:
        warnings.append("single-source-only")
    if not row.get("updated_at"):
        warnings.append("missing-update-date")
    if not row.get("repository_url"):
        warnings.append("missing-repository-url")
    if not row.get("package_identifier") and not row.get("has_remote"):
        warnings.append("install-method-unclear")
    status = row.get("status")
    if status and status != "active":
        warnings.append(f"status:{status}")

    if row.get("deprecated_npm"):
        warnings.append("deprecated-npm")
    if row.get("archived_repo"):
        warnings.append("archived-repo")

    updated_at = row.get("updated_at")
    if updated_at:
        try:
            from datetime import datetime

            updated_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_days = (datetime.now(UTC) - updated_time).days
            if age_days > 540:
                warnings.append("stale-over-18-months")
            elif age_days > 365:
                warnings.append("stale-over-12-months")
        except (ValueError, TypeError):
            pass

    return warnings


def _get_confidence_breakdown(
    row: dict[str, Any], sources: list[str], warning_flags: list[str]
) -> ConfidenceBreakdown:
    """Get confidence score breakdown."""
    base = 0.4
    official = 0.2 if "official" in sources else 0
    verified = 0.15 if row.get("verified") else 0
    use_count = row.get("use_count", 0)
    popularity = 0.15 if use_count >= 100 else 0.1 if use_count > 0 else 0
    multi_source = 0.05 if len(sources) > 1 else 0

    penalties = 0
    if "stale-over-18-months" in warning_flags:
        penalties -= 0.15
    if "deprecated-npm" in warning_flags:
        penalties -= 0.2
    if "archived-repo" in warning_flags:
        penalties -= 0.1
    if "install-method-unclear" in warning_flags:
        penalties -= 0.1
    if "missing-repository-url" in warning_flags:
        penalties -= 0.05

    raw = base + official + verified + popularity + multi_source + penalties
    score = max(0, min(1, round(raw, 2)))

    drivers = []
    if official:
        drivers.append("+official")
    if verified:
        drivers.append("+verified")
    if popularity >= 0.15:
        drivers.append("+popularity:100+uses")
    elif popularity > 0:
        drivers.append("+popularity:any-use")
    if multi_source:
        drivers.append("+multi-source")
    if "deprecated-npm" in warning_flags:
        drivers.append("-deprecated-npm")
    if "archived-repo" in warning_flags:
        drivers.append("-archived-repo")
    if "stale-over-18-months" in warning_flags:
        drivers.append("-stale>18mo")
    if "install-method-unclear" in warning_flags:
        drivers.append("-install-unclear")
    if "missing-repository-url" in warning_flags:
        drivers.append("-no-repo-url")

    return ConfidenceBreakdown(
        score=score,
        base=base,
        official=official,
        verified=verified,
        popularity=popularity,
        multi_source=multi_source,
        penalties=penalties,
        drivers=drivers,
    )


def _get_trust_signals(
    row: dict[str, Any],
    sources: list[str],
    env_vars: list[RegistryEnvVar] | None = None,
) -> TrustSignals:
    """Get trust signals."""
    freshness_days = _get_freshness_days(row)
    return TrustSignals(
        has_official_source="official" in sources,
        is_verified=bool(row.get("verified")),
        has_repository=bool(row.get("repository_url")),
        has_remote=bool(row.get("has_remote")),
        multi_source=len(sources) > 1,
        has_recent_update=freshness_days is not None and freshness_days <= 180,
        requires_secrets=any(v.is_secret for v in (env_vars or []) if v.is_secret),
    )


def _get_freshness_days(row: dict[str, Any]) -> int | None:
    """Get freshness in days."""
    candidate = row.get("updated_at") or row.get("published_at")
    if not candidate:
        return None
    try:
        from datetime import datetime

        updated_time = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return max(0, (datetime.now(UTC) - updated_time).days)
    except (ValueError, TypeError):
        return None


def _get_freshness_label(freshness_days: int | None) -> str:
    """Get freshness label."""
    if freshness_days is None:
        return "unknown"
    if freshness_days <= 30:
        return "recent"
    if freshness_days <= 180:
        return "active"
    if freshness_days <= 365:
        return "aging"
    return "stale"


def _get_install_complexity(
    row: dict[str, Any],
    env_vars: list[RegistryEnvVar],
    tools_exposed: list[ToolSummary],
) -> str:
    """Get install complexity."""
    secret_count = sum(1 for v in env_vars if v.is_secret)
    if row.get("has_remote") and secret_count == 0:
        return "low"
    if secret_count >= 2:
        return "high"
    if not row.get("package_identifier") and not row.get("has_remote"):
        return "high"
    if row.get("registry_type") == "oci":
        return "medium"
    if len(tools_exposed) > 15 or secret_count == 1:
        return "medium"
    return "low"


def _get_recommendation_reason(row: dict[str, Any], sources: list[str]) -> str:
    """Get recommendation reason."""
    if "official" in sources and row.get("verified") and (row.get("use_count", 0) > 0):
        return "official registry presence, verified publisher metadata, and community usage"
    if "official" in sources:
        return "official registry presence and metadata completeness"
    if row.get("verified"):
        return "verified listing and strong discovery signals"
    if row.get("use_count", 0) > 0:
        return "community usage and text relevance"
    return "text relevance and available metadata"
