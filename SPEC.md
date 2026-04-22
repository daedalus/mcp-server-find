# SPEC.md — mcp-server-find

## Purpose
Python implementation of mcp-server-find, an MCP server that helps AI agents discover, evaluate, and install other MCP servers. Aggregates data from Official MCP Registry, Glama, and Smithery into a fast, searchable index with FTS5 full-text search.

## Scope

### What IS in scope
- Sync MCP servers from Official MCP Registry (registry.modelcontextprotocol.io)
- Sync MCP servers from Glama (glama.ai)
- Sync MCP servers from Smithery (registry.smithery.ai)
- SQLite database with FTS5 full-text search
- Search, details, install config, and category browsing tools
- Confidence scoring and recommendation system
- Trust signals and warning flags
- Install configuration generation for multiple platforms

### What is NOT in scope
- Snapshot bootstrap (deferred to future)
- HTTP transport (stdio only)
- Build-time enrichment (deprecated npm, archived repo checks)

## Public API / Interface

### Core Functions
- `init_database(db_path?: str) -> sqlite3.Connection` - Initialize SQLite with FTS5
- `sync_official_registry(db) -> int` - Sync from Official MCP Registry
- `sync_glama_registry(db) -> int` - Sync from Glama
- `sync_smithery_registry(db) -> int` - Sync from Smithery
- `search_servers(db, query, limit?, filters?) -> list[SearchResult]` - Search MCP servers
- `get_server_details(db, name_or_slug) -> ServerDetail | None` - Get server details
- `get_install_config(db, name_or_slug, platform) -> InstallConfig` - Generate install config
- `list_categories(db) -> list[Category]` - List all categories
- `get_servers_by_category(db, category, limit?) -> list[dict]` - Get servers in category

### MCP Tools (FastMCP)
- `search_mcp_servers(query?, limit?, transportType?, registryType?, registrySource?)` - Search for MCP servers
- `get_server_details(name)` - Get detailed server information
- `get_install_config(name, platform)` - Generate install config for a platform
- `browse_categories(category?, limit?)` - Browse categories or list all

## Data Formats

### SearchResult
```python
{
    "name": str,
    "description": str,
    "version": str,
    "registry_type": str | None,
    "package_identifier": str | None,
    "transport_type": str | None,
    "repository_url": str | None,
    "has_remote": bool,
    "rank": int,
    "sources": list[str],
    "use_count": int,
    "verified": bool,
    "icon_url": str | None,
    "updated_at": str | None,
    "published_at": str | None,
    "source_count": int,
    "confidence_score": float,
    "confidence_breakdown": ConfidenceBreakdown,
    "recommendation_reason": str,
    "warning_flags": list[str],
    "trust_signals": TrustSignals,
    "freshness_days": int | None,
    "freshness_label": str,
    "install_complexity": str,
    "secret_count": int,
    "capability_count": int,
}
```

### ServerDetail
Same as SearchResult plus:
- `repository_source`: str | None
- `status`: str
- `remote_url`: str | None
- `categories`: list[str]
- `environment_variables`: list[RegistryEnvVar]
- `tools_exposed`: list[ToolSummary]

### InstallConfig
```python
{
    "client": str,
    "server_name": str,
    "config_file_path": str,
    "config": dict,
    "instructions": str,
    "post_install_note": str,
    "env_vars_needed": list[dict],
}
```

## Edge Cases
- Empty query returns popular servers
- No results returns helpful message with next actions
- Server not found returns search suggestion
- Ambiguous server name uses fuzzy matching
- Missing metadata uses sensible defaults
- Failed API sync logs error but continues
- Category not found returns available categories

## Performance & Constraints
- FTS5 with porter stemmer for search
- WAL mode for concurrent reads
- Cursor-based pagination for API syncs
- Rate limiting between API calls (100ms delay)
- Search aliases for common abbreviations (gh→github, pg→postgres, etc.)
