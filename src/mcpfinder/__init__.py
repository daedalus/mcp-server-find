"""mcpfinder - MCP server discovery for AI agents."""

__version__ = "0.1.0"
__all__ = [
    "init_database",
    "search_servers",
    "get_server_details",
    "get_install_config",
    "list_categories",
    "get_servers_by_category",
    "sync_official_registry",
    "sync_glama_registry",
    "sync_smithery_registry",
    "get_server_count",
    "is_sync_needed",
]

from mcpfinder.categories import get_servers_by_category, list_categories
from mcpfinder.db import get_server_count, init_database, is_sync_needed
from mcpfinder.install import get_install_config
from mcpfinder.search import get_server_details, search_servers
from mcpfinder.sync import (
    sync_glama_registry,
    sync_official_registry,
    sync_smithery_registry,
)
