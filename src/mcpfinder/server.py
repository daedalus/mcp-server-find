"""MCP Server using FastMCP."""

import asyncio
import json
import sqlite3

try:
    import fastmcp

    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False

from mcpfinder import (
    get_servers_by_category,
    is_sync_needed,
    list_categories,
    search_servers,
    sync_glama_registry,
    sync_official_registry,
    sync_smithery_registry,
)


def _format_use_count(count: int) -> str:
    """Format use count."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def _source_badges(sources: list[str], use_count: int, verified: bool) -> str:
    """Format source badges."""
    badges = []
    if "official" in sources:
        badges.append("Official")
    if "smithery" in sources:
        badge = "Smithery"
        if use_count > 0:
            badge += f" ({_format_use_count(use_count)} uses)"
        if verified:
            badge += " ✓"
        badges.append(badge)
    if "glama" in sources:
        badges.append("Glama")
    return " | ".join(badges)


def _build_env_map(env_vars: list[dict]) -> dict[str, str]:
    """Build environment variable map."""
    env = {}
    for v in env_vars:
        env[v["name"]] = (
            "<YOUR_VALUE>" if v.get("isSecret") else v.get("description", "<VALUE>")
        )
    return env


async def _ensure_sync(conn: sqlite3.Connection) -> None:
    """Ensure data is synced."""
    from mcpfinder.db import get_server_count

    count = get_server_count(conn)
    if count == 0 or is_sync_needed(conn):
        results = await asyncio.gather(
            sync_official_registry(conn),
            sync_glama_registry(conn),
            sync_smithery_registry(conn),
            return_exceptions=True,
        )
        counts = [r if isinstance(r, int) else 0 for r in results]
        import sys

        sys.stderr.write(
            f"[mcpfinder] Synced: Official={counts[0]}, Glama={counts[1]}, "
            f"Smithery={counts[2]} ({get_server_count(conn)} total)\n"
        )


def create_mcp_server() -> "fastmcp.FastMCP":
    """Create and configure the MCP server."""
    if not FASTMCP_AVAILABLE:
        raise ImportError("fastmcp is required. Install with: pip install fastmcp")

    mcp = fastmcp.FastMCP("mcpfinder")

    @mcp.tool()
    async def search_mcp_servers(
        query: str = "",
        limit: int = 10,
        transport_type: str = "any",
        registry_type: str = "any",
        registry_source: str = "any",
    ) -> str:
        """Search for MCP servers by keyword, technology, or use case.

        Call this first whenever the user needs a capability you do not already have.
        Use it when the user mentions an external service, a database, a filesystem,
        or asks 'can you connect to X?'.

        Examples:
        - query='postgres' for PostgreSQL database
        - query='slack' for Slack integration
        - query='filesystem' for file system access

        Args:
            query: Search query - keyword, use case, or technology
            limit: Maximum results to return (1-50, default: 10)
            transport_type: Filter by transport type (stdio, streamable-http, sse, any)
            registry_type: Filter by package registry type (npm, pypi, oci, any)
            registry_source: Filter by registry source (official, glama, smithery, any)

        Returns:
            Formatted search results with metadata
        """
        from mcpfinder.db import init_database

        conn = init_database()
        await _ensure_sync(conn)

        filters = {}
        if transport_type != "any":
            filters["transportType"] = transport_type
        if registry_type != "any":
            filters["registryType"] = registry_type
        if registry_source != "any":
            filters["registrySource"] = registry_source

        results = search_servers(conn, query, limit, filters)

        if not results:
            return json.dumps(
                {
                    "query": query,
                    "results": [],
                    "next_actions": [
                        "browse_categories()",
                        'search_mcp_servers(query="<broader term>")',
                    ],
                },
                indent=2,
            )

        formatted = []
        for r in results:
            badges = _source_badges(r.sources, r.use_count, r.verified)
            formatted.append(
                f"{r.rank}. **{r.name}** (v{r.version or 'n/a'})\n"
                f"   {r.description}\n"
                f"   Package: {r.package_identifier or 'N/A'} | "
                f"Transport: {r.transport_type or 'N/A'}"
                + (" | Remote available" if r.has_remote else "")
                + (f"\n   {badges}" if badges else "")
            )

        return json.dumps(
            {
                "query": query,
                "results": [r.to_dict() for r in results],
                "next_actions": [
                    f'get_server_details(name="{r.name}")' for r in results[:3]
                ],
            },
            indent=2,
        )

    @mcp.tool()
    async def get_server_details(name: str) -> str:
        """Get detailed information about an MCP server.

        Always call this before recommending or installing a server.
        Returns metadata for judging safety and fit.

        Args:
            name: Server name or slug (e.g., 'io.modelcontextprotocol/filesystem')

        Returns:
            Detailed server information including trust signals, warnings,
            environment variables, and tools
        """
        from mcpfinder.db import init_database

        conn = init_database()
        await _ensure_sync(conn)

        detail = get_server_details(conn, name)

        if not detail:
            return json.dumps(
                {
                    "name": name,
                    "found": False,
                    "next_actions": ['search_mcp_servers(query="<keyword>")'],
                },
                indent=2,
            )

        env_section = ""
        if detail.environment_variables:
            env_section = "\n\n**Environment Variables:**\n"
            for v in detail.environment_variables:
                env_section += (
                    f"- `{v.name}`: {v.description or 'No description'}"
                    f"{' (secret)' if v.is_secret else ''}\n"
                )

        tool_section = ""
        if detail.tools_exposed:
            tool_section = "\n\n**Tools Exposed:**\n"
            for tool in detail.tools_exposed[:15]:
                tool_section += (
                    f"- `{tool.name}`"
                    + (f": {tool.description}" if tool.description else "")
                    + "\n"
                )

        return json.dumps(
            {
                "found": True,
                "server": detail.to_dict(),
                "next_actions": [
                    f'get_install_config(name="{detail.name}", platform="claude-desktop")'
                ],
            },
            indent=2,
        )

    @mcp.tool()
    async def get_install_config(name: str, platform: str = "claude-desktop") -> str:
        """Generate install config for a target client.

        Use this after get_server_details to generate a ready-to-paste JSON config.

        Args:
            name: Server name or slug
            platform: Target platform (claude-desktop, cursor, claude-code, cline, windsurf)

        Returns:
            JSON config snippet with file paths and required env vars
        """
        from mcpfinder.db import init_database

        conn = init_database()
        await _ensure_sync(conn)

        detail = get_server_details(conn, name)

        if not detail:
            return json.dumps(
                {
                    "server": name,
                    "found": False,
                    "next_actions": ['search_mcp_servers(query="<keyword>")'],
                },
                indent=2,
            )

        from mcpfinder.install import PLATFORM_INFO

        platform_info = PLATFORM_INFO.get(platform, PLATFORM_INFO["claude-desktop"])

        server_key = detail.name.split("/")[-1] if "/" in detail.name else detail.name
        env = _build_env_map(
            [
                {"name": v.name, "isSecret": v.is_secret, "description": v.description}
                for v in detail.environment_variables
            ]
        )

        if detail.has_remote and detail.remote_url:
            server_config = {"url": detail.remote_url}
            if env:
                server_config["env"] = env
            install_type = "remote"
        elif detail.registry_type == "npm" and detail.package_identifier:
            server_config = {
                "command": "npx",
                "args": ["-y", detail.package_identifier],
            }
            if env:
                server_config["env"] = env
            install_type = "npm"
        elif detail.registry_type == "pypi" and detail.package_identifier:
            server_config = {"command": "uvx", "args": [detail.package_identifier]}
            if env:
                server_config["env"] = env
            install_type = "pypi"
        else:
            server_config = {}
            install_type = None

        if install_type:
            wrapper = {
                platform_info.get("top_level_key", "mcpServers"): {
                    server_key: server_config
                }
            }
        else:
            wrapper = {
                "note": "Auto-config not available",
                "repositoryUrl": detail.repository_url,
            }

        return json.dumps(
            {
                "found": True,
                "autoInstallable": install_type is not None,
                "server": detail.name,
                "platform": platform,
                "installType": install_type,
                "configFilePath": platform_info.get("config_path"),
                "config": wrapper,
                "envVarsNeeded": [
                    {
                        "name": v.name,
                        "description": v.description,
                        "isSecret": v.is_secret,
                    }
                    for v in detail.environment_variables
                ],
                "safeToAutoinstall": len(detail.environment_variables) == 0,
                "requiresUserSecrets": any(
                    v.is_secret for v in detail.environment_variables
                ),
                "warningFlags": detail.warning_flags,
                "nextActions": [],
            },
            indent=2,
        )

    @mcp.tool()
    async def browse_categories(category: str = "", limit: int = 20) -> str:
        """Browse MCP server categories.

        Call with no category to list all categories with counts.
        Call with a category to get top servers in that category.

        Args:
            category: Optional category name (omit to list all)
            limit: Maximum results when category provided (1-50, default: 20)

        Returns:
            Category list or servers in a category
        """
        from mcpfinder.db import init_database

        conn = init_database()
        await _ensure_sync(conn)

        if not category:
            categories = list_categories(conn)

            if not categories:
                return json.dumps(
                    {
                        "categories": [],
                        "next_actions": ['search_mcp_servers(query="filesystem")'],
                    },
                    indent=2,
                )

            return json.dumps(
                {
                    "categories": [
                        {"name": c.name, "count": c.count} for c in categories
                    ],
                    "next_actions": [
                        f'browse_categories(category="{c.name}")'
                        for c in categories[:3]
                    ],
                },
                indent=2,
            )

        servers = get_servers_by_category(conn, category.lower(), limit)

        if not servers:
            return json.dumps(
                {
                    "category": category,
                    "results": [],
                    "next_actions": ["browse_categories()"],
                },
                indent=2,
            )

        return json.dumps(
            {
                "category": category,
                "results": servers,
                "next_actions": [
                    f'get_server_details(name="{s["name"]}")' for s in servers[:3]
                ],
            },
            indent=2,
        )

    return mcp


def main() -> None:
    """Main entry point."""
    if not FASTMCP_AVAILABLE:
        raise ImportError("fastmcp is required. Install with: pip install fastmcp")

    mcp = create_mcp_server()
    mcp.run()


if __name__ == "__main__":
    main()
