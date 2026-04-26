# mcp-server-find

MCP server discovery - find and install MCP servers from Official Registry, Glama, and Smithery.

[![PyPI](https://img.shields.io/pypi/v/mcp-server-find.svg)](https://pypi.org/project/mcp-server-find/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-server-find.svg)](https://pypi.org/project/mcp-server-find/)

mcp-name: io.github.daedalus/mcp-server-find

## Install

```bash
pip install mcp-server-find
```

## MCP Server

mcp-server-find is an MCP server that helps AI agents discover, evaluate, and install other MCP servers. It aggregates data from:

- Official MCP Registry
- Glama (glama.ai)
- Smithery (registry.smithery.ai)

### Claude Desktop

```json
{
  "mcpServers": {
    "mcp-server-find": {
      "command": "python",
      "args": ["-m", "mcp_server_find"]
    }
  }
}
```

### Usage

```python
from mcp_server_find import search_servers, get_server_details, get_install_config

# Initialize database
from mcp_server_find.db import init_database
conn = init_database()

# Search for MCP servers
results = search_servers(conn, "postgres", 10)

# Get server details
detail = get_server_details(conn, "io.modelcontextprotocol/filesystem")

# Generate install config
config = get_install_config(conn, "io.modelcontextprotocol/filesystem", "claude-desktop")
```

## MCP Tools

- `search_mcp_servers`: Search for MCP servers by keyword
- `get_server_details`: Get detailed server information
- `get_install_config`: Generate install config for a platform
- `browse_categories`: Browse MCP server categories

## API

### Core Functions

- `init_database(db_path?: str) -> sqlite3.Connection` - Initialize SQLite with FTS5
- `search_servers(conn, query, limit?, filters?) -> list[SearchResult]` - Search MCP servers
- `get_server_details(conn, name_or_slug) -> ServerDetail | None` - Get detailed server info
- `get_install_config(conn, name_or_slug, platform) -> InstallConfig` - Generate install config
- `list_categories(conn) -> list[Category]` - List all categories
- `get_servers_by_category(conn, category, limit?) -> list[dict]` - Get servers in category

## Development

```bash
git clone https://github.com/daedalus/mcp-server-find.git
cd mcp-server-find
pip install -e ".[test]"

# Run tests
pytest

# Format
ruff format src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/
```
