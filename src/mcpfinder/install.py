"""Generate installation commands for MCP servers."""

import json
import sqlite3
from typing import Any

from mcpfinder.search import find_server_by_name_or_slug
from mcpfinder.types import InstallConfig, RegistryEnvVar

PLATFORM_INFO = {
    "claude-desktop": {
        "config_path": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "config_path_win": "%APPDATA%\\Claude\\claude_desktop_config.json",
        "display_name": "Claude Desktop",
        "post_install": "Restart Claude Desktop to activate the new server.",
    },
    "cursor": {
        "config_path": ".cursor/mcp.json (project) or ~/.cursor/mcp.json (global)",
        "display_name": "Cursor",
        "post_install": "Cursor auto-detects config changes — no restart needed.",
    },
    "claude-code": {
        "config_path": ".mcp.json (project) or ~/.claude.json (global)",
        "display_name": "Claude Code",
        "post_install": "Claude Code will detect the new server automatically on next tool use.",
    },
    "cline": {
        "config_path": ".vscode/mcp.json or VS Code settings (Cline MCP config)",
        "display_name": "Cline / Roo Code",
        "post_install": "Reload the VS Code window or restart Cline to activate.",
    },
    "windsurf": {
        "config_path": "~/.windsurf/mcp.json",
        "display_name": "Windsurf",
        "post_install": "Restart Windsurf to activate the new server.",
    },
    "vscode": {
        "config_path": ".vscode/mcp.json",
        "display_name": "VS Code",
        "post_install": "Reload the VS Code window to activate.",
    },
    "generic": {
        "config_path": "your MCP client config file",
        "display_name": "MCP Client",
        "post_install": "Refer to your client's docs for how to reload MCP config.",
    },
}


def get_install_config(
    conn: sqlite3.Connection,
    name_or_slug: str,
    platform: str = "claude-desktop",
) -> InstallConfig | None:
    """Generate install configuration for a specific MCP server and client."""
    row = find_server_by_name_or_slug(conn, name_or_slug)
    if not row:
        return None

    try:
        env_vars_data = (
            json.loads(row.get("env_vars", "[]")) if row.get("env_vars") else []
        )
        env_vars = [
            RegistryEnvVar(
                name=v.get("name", ""),
                description=v.get("description"),
                format=v.get("format"),
                is_secret=v.get("isSecret", False),
            )
            for v in env_vars_data
        ]
    except (json.JSONDecodeError, TypeError):
        env_vars = []

    server_key = row["slug"] or row["name"].split("/")[-1] or row["name"]

    if row.get("registry_type") == "npm" and row.get("package_identifier"):
        return _generate_npm_config(
            server_key, row["package_identifier"], env_vars, platform
        )

    if row.get("registry_type") == "pypi" and row.get("package_identifier"):
        return _generate_pypi_config(
            server_key, row["package_identifier"], env_vars, platform
        )

    if row.get("registry_type") == "oci" and row.get("package_identifier"):
        return _generate_docker_config(
            server_key, row["package_identifier"], env_vars, platform
        )

    if row.get("has_remote") and row.get("remote_url"):
        return _generate_remote_config(
            server_key, row["remote_url"], env_vars, platform
        )

    platform_info = PLATFORM_INFO.get(platform, PLATFORM_INFO["generic"])
    return InstallConfig(
        client=platform,
        server_name=server_key,
        config_file_path=platform_info["config_path"],
        config={
            "note": "Unable to generate auto-config. Check the repository for installation instructions.",
            "repositoryUrl": row["repository_url"],
            "registryType": row["registry_type"],
            "packageIdentifier": row["package_identifier"],
        },
        instructions=f"Could not auto-generate config. Check the repository: {row.get('repository_url') or 'N/A'}",
        post_install_note="",
        env_vars_needed=env_vars,
    )


def _build_instructions(
    mcp_config: dict[str, Any],
    client: str,
    prefix: str | None = None,
) -> tuple[str, str, str]:
    """Build instructions for install config."""
    platform = PLATFORM_INFO.get(client, PLATFORM_INFO["generic"])
    json_str = json.dumps(mcp_config, indent=2)
    prefix_str = f"{prefix}\n\n" if prefix else ""

    instructions = (
        f"{prefix_str}Add to your {platform['display_name']} config "
        f"({platform['config_path']}):\n\n```json\n{json_str}\n```"
    )

    config_path = platform["config_path"]
    if "config_path_win" in platform:
        instructions += f"\n\nOn Windows: {platform['config_path_win']}"

    return instructions, config_path, platform["post_install"]


def _generate_npm_config(
    server_key: str,
    package_id: str,
    env_vars: list[RegistryEnvVar],
    platform: str,
) -> InstallConfig:
    """Generate npm-based install config."""
    env: dict[str, str] = {}
    for v in env_vars:
        env[v.name] = "<YOUR_VALUE>" if v.is_secret else (v.description or "<VALUE>")

    config: dict[str, Any] = {"command": "npx", "args": ["-y", package_id]}
    if env:
        config["env"] = env

    mcp_config = {"mcpServers": {server_key: config}}
    instructions, config_path, post_install = _build_instructions(
        mcp_config, platform, "Install via npx (recommended)."
    )

    return InstallConfig(
        client=platform,
        server_name=server_key,
        config_file_path=config_path,
        config=mcp_config,
        instructions=instructions,
        post_install_note=post_install,
        env_vars_needed=env_vars,
    )


def _generate_pypi_config(
    server_key: str,
    package_id: str,
    env_vars: list[RegistryEnvVar],
    platform: str,
) -> InstallConfig:
    """Generate pypi-based install config."""
    env: dict[str, str] = {}
    for v in env_vars:
        env[v.name] = "<YOUR_VALUE>" if v.is_secret else (v.description or "<VALUE>")

    config: dict[str, Any] = {"command": "uvx", "args": [package_id]}
    if env:
        config["env"] = env

    mcp_config = {"mcpServers": {server_key: config}}
    instructions, config_path, post_install = _build_instructions(
        mcp_config, platform, "Install via uvx (recommended) or pip."
    )

    return InstallConfig(
        client=platform,
        server_name=server_key,
        config_file_path=config_path,
        config=mcp_config,
        instructions=instructions,
        post_install_note=post_install,
        env_vars_needed=env_vars,
    )


def _generate_docker_config(
    server_key: str,
    package_id: str,
    env_vars: list[RegistryEnvVar],
    platform: str,
) -> InstallConfig:
    """Generate docker-based install config."""
    args = ["run", "-i"]
    for v in env_vars:
        args.extend(["-e", f"{v.name}=<YOUR_VALUE>"])
    args.append(package_id)

    config: dict[str, Any] = {"command": "docker", "args": args}

    mcp_config = {"mcpServers": {server_key: config}}
    instructions, config_path, post_install = _build_instructions(
        mcp_config, platform, "Run via Docker container."
    )

    return InstallConfig(
        client=platform,
        server_name=server_key,
        config_file_path=config_path,
        config=mcp_config,
        instructions=instructions,
        post_install_note=post_install,
        env_vars_needed=env_vars,
    )


def _generate_remote_config(
    server_key: str,
    remote_url: str,
    env_vars: list[RegistryEnvVar],
    platform: str,
) -> InstallConfig:
    """Generate remote server install config."""
    config: dict[str, Any] = {"url": remote_url}

    mcp_config = {"mcpServers": {server_key: config}}
    instructions, config_path, post_install = _build_instructions(
        mcp_config,
        platform,
        "This is a hosted/remote MCP server — no local installation needed.",
    )

    return InstallConfig(
        client=platform,
        server_name=server_key,
        config_file_path=config_path,
        config=mcp_config,
        instructions=instructions,
        post_install_note=post_install,
        env_vars_needed=env_vars,
    )
