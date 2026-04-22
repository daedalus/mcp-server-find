"""Tests for search functionality."""

import pytest

from mcp_server_find.categories import (
    categorize_server,
    extract_keywords,
    get_servers_by_category,
    list_categories,
)
from mcp_server_find.db import init_database
from mcp_server_find.search import (
    find_server_by_name_or_slug,
    get_server_details,
    search_servers,
)


@pytest.fixture
def conn():
    """Create in-memory database for testing."""
    conn = init_database(":memory:")

    conn.executescript("""
        INSERT INTO servers (id, slug, name, description, version, source, use_count, verified, sources)
        VALUES
            ('test-1', 'test-server', 'test-server', 'A test server', '1.0.0', 'official', 100, 1, '["official"]'),
            ('test-2', 'postgres-server', 'postgres-server', 'PostgreSQL database server', '2.0.0', 'official', 500, 1, '["official", "smithery"]'),
            ('test-3', 'filesystem', 'filesystem', 'File system access', '1.0.0', 'official', 200, 0, '["official"]'),
            ('test-4', 'slack', 'slack', 'Slack integration', '1.0.0', 'smithery', 50, 0, '["smithery"]');
    """)
    conn.commit()

    conn.execute(
        """INSERT INTO servers_fts(rowid, name, description, keywords)
           VALUES (1, 'test-server', 'A test server', 'test'),
                  (2, 'postgres-server', 'PostgreSQL database server', 'postgres database sql'),
                  (3, 'filesystem', 'File system access', 'filesystem file'),
                  (4, 'slack', 'Slack integration', 'slack')"""
    )
    conn.commit()

    return conn


def test_search_empty_query(conn):
    """Test search with empty query returns popular servers."""
    results = search_servers(conn, "", 10)
    assert len(results) > 0


def test_search_postgres(conn):
    """Test search for postgres."""
    results = search_servers(conn, "postgres", 10)
    assert len(results) > 0
    assert any("postgres" in r.name.lower() for r in results)


def test_search_filesystem(conn):
    """Test search for filesystem."""
    results = search_servers(conn, "filesystem", 10)
    assert len(results) > 0


def test_find_server_exact_match(conn):
    """Test exact server lookup."""
    row = find_server_by_name_or_slug(conn, "test-server")
    assert row is not None
    assert row["name"] == "test-server"


def test_find_server_by_slug(conn):
    """Test server lookup by slug."""
    row = find_server_by_name_or_slug(conn, "test-server")
    assert row is not None


def test_get_server_details(conn):
    """Test get server details."""
    detail = get_server_details(conn, "test-server")
    assert detail is not None
    assert detail.name == "test-server"
    assert detail.use_count == 100
    assert detail.verified is True


def test_extract_keywords():
    """Test keyword extraction."""
    keywords = extract_keywords("test-server", "A test server")
    assert "test" in keywords


def test_categorize_server():
    """Test server categorization."""
    cats = categorize_server("postgres-server", "PostgreSQL database server")
    assert "database" in cats


def test_list_categories(conn):
    """Test list categories."""
    categories = list_categories(conn)
    assert len(categories) > 0


def test_get_servers_by_category(conn):
    """Test get servers by category."""
    servers = get_servers_by_category(conn, "database", 10)
    assert len(servers) >= 1
