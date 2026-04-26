"""mcp-server-find - MCP server discovery for AI agents."""

__version__ = "0.1.1"
__all__ = [
    "init_database",
    "get_data_dir",
    "get_last_sync_timestamp",
    "update_sync_log",
    "get_server_count",
    "is_sync_needed",
    "search_servers",
    "get_server_details",
    "find_server_by_name_or_slug",
    "get_install_config",
    "list_categories",
    "get_servers_by_category",
    "extract_keywords",
    "categorize_server",
    "sync_official_registry",
    "sync_glama_registry",
    "sync_smithery_registry",
    "find_existing_server",
    "find_official_from_smithery_qualified_name",
    "merge_server_data",
    "DEFAULT_SNAPSHOT_BASE",
    "bootstrap_from_snapshot",
    "fetch_snapshot_manifest",
    "enrich_smithery_repo_urls",
    "enrich_deprecation_flags",
]

from mcp_server_find.categories import (
    categorize_server,
    extract_keywords,
    get_servers_by_category,
    list_categories,
)
from mcp_server_find.db import (
    get_data_dir,
    get_last_sync_timestamp,
    get_server_count,
    init_database,
    is_sync_needed,
    update_sync_log,
)
from mcp_server_find.enrich import enrich_deprecation_flags, enrich_smithery_repo_urls
from mcp_server_find.install import get_install_config
from mcp_server_find.search import (
    find_server_by_name_or_slug,
    get_server_details,
    search_servers,
)
from mcp_server_find.snapshot import (
    DEFAULT_SNAPSHOT_BASE,
    bootstrap_from_snapshot,
    fetch_snapshot_manifest,
)
from mcp_server_find.sync import (
    find_existing_server,
    find_official_from_smithery_qualified_name,
    merge_server_data,
    sync_glama_registry,
    sync_official_registry,
    sync_smithery_registry,
)
