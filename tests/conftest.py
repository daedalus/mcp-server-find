"""Pytest configuration."""

import pytest


@pytest.fixture
def sample_server():
    """Sample server data for testing."""
    return {
        "id": "test-server",
        "slug": "test-server",
        "name": "test-server",
        "description": "A test MCP server",
        "version": "1.0.0",
        "registry_type": "npm",
        "package_identifier": "@test/server",
        "transport_type": "stdio",
        "repository_url": "https://github.com/test/server",
        "source": "official",
        "use_count": 100,
        "verified": 1,
        "sources": ["official"],
    }
