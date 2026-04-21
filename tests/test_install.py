"""Tests for install config generation."""

import sqlite3

import pytest

from mcpfinder.db import init_database
from mcpfinder.install import get_install_config


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Create in-memory database for testing."""
    conn = init_database(":memory:")

    conn.executescript("""
        INSERT INTO servers (id, slug, name, description, version, source, use_count, verified, sources, registry_type, package_identifier, transport_type, remote_url, has_remote, env_vars)
        VALUES
            ('npm-test', 'npm-test', 'npm-test', 'NPM test server', '1.0.0', 'official', 100, 1, '["official"]', 'npm', '@test/npm-test', 'stdio', NULL, 0, '[]'),
            ('pypi-test', 'pypi-test', 'pypi-test', 'PyPI test server', '1.0.0', 'official', 50, 0, '["official"]', 'pypi', 'pypi-test', 'stdio', NULL, 0, '[]'),
            ('remote-test', 'remote-test', 'remote-test', 'Remote test server', '1.0.0', 'smithery', 25, 0, '["smithery"]', NULL, NULL, NULL, 'https://example.com/mcp', 1, '[]'),
            ('no-pkg', 'no-pkg', 'no-pkg', 'No package server', '1.0.0', 'official', 10, 0, '["official"]', NULL, NULL, NULL, NULL, 0, '[]');
    """)
    conn.commit()

    return conn


def test_get_install_config_npm(conn):
    """Test npm install config generation."""
    config = get_install_config(conn, "npm-test", "claude-desktop")
    assert config is not None
    assert config.server_name == "npm-test"
    server_config = config.config.get("mcpServers", {}).get("npm-test", {})
    assert server_config.get("command") == "npx"
    assert "@test/npm-test" in server_config.get("args", [])


def test_get_install_config_pypi(conn):
    """Test pypi install config generation."""
    config = get_install_config(conn, "pypi-test", "claude-desktop")
    assert config is not None
    assert config.server_name == "pypi-test"
    server_config = config.config.get("mcpServers", {}).get("pypi-test", {})
    assert server_config.get("command") == "uvx"


def test_get_install_config_remote(conn):
    """Test remote server config generation."""
    config = get_install_config(conn, "remote-test", "claude-desktop")
    assert config is not None
    server_config = config.config.get("mcpServers", {}).get("remote-test", {})
    assert server_config.get("url") == "https://example.com/mcp"


def test_get_install_config_unknown(conn):
    """Test unknown server config generation."""
    config = get_install_config(conn, "no-pkg", "claude-desktop")
    assert config is not None
    assert "note" in config.config


def test_get_install_config_not_found(conn):
    """Test config for non-existent server."""
    config = get_install_config(conn, "nonexistent", "claude-desktop")
    assert config is None
