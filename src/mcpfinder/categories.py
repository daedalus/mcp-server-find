"""Keyword-based categorization for MCP servers."""

import re
import sqlite3
from typing import Any

from mcpfinder.types import Category

STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "is",
    "it",
    "that",
    "this",
    "as",
    "are",
    "was",
    "be",
    "has",
    "had",
    "have",
    "do",
    "does",
    "did",
    "will",
    "can",
    "could",
    "would",
    "should",
    "may",
    "might",
    "shall",
    "not",
    "no",
    "mcp",
    "server",
    "tool",
    "model",
    "context",
    "protocol",
}

CATEGORY_DEFS = [
    {
        "name": "filesystem",
        "keywords": [
            "file",
            "filesystem",
            "directory",
            "folder",
            "path",
            "disk",
            "storage",
            "fs",
        ],
    },
    {
        "name": "database",
        "keywords": [
            "database",
            "sql",
            "sqlite",
            "postgres",
            "mysql",
            "mongo",
            "redis",
            "dynamodb",
            "supabase",
            "prisma",
            "db",
            "query",
        ],
    },
    {
        "name": "api",
        "keywords": [
            "api",
            "rest",
            "graphql",
            "endpoint",
            "webhook",
            "http",
            "request",
        ],
    },
    {
        "name": "ai",
        "keywords": [
            "ai",
            "llm",
            "embedding",
            "openai",
            "anthropic",
            "gemini",
            "machine-learning",
            "ml",
            "neural",
            "gpt",
            "claude",
        ],
    },
    {
        "name": "web",
        "keywords": [
            "web",
            "browser",
            "scrape",
            "crawl",
            "html",
            "url",
            "fetch",
            "puppeteer",
            "playwright",
            "selenium",
        ],
    },
    {
        "name": "git",
        "keywords": [
            "git",
            "github",
            "gitlab",
            "bitbucket",
            "repo",
            "commit",
            "branch",
            "version-control",
        ],
    },
    {
        "name": "cloud",
        "keywords": [
            "cloud",
            "aws",
            "azure",
            "gcp",
            "docker",
            "kubernetes",
            "k8s",
            "terraform",
            "deploy",
            "serverless",
            "lambda",
        ],
    },
    {
        "name": "search",
        "keywords": ["search", "brave", "bing", "elasticsearch", "algolia", "index"],
    },
    {
        "name": "monitoring",
        "keywords": [
            "monitor",
            "log",
            "metric",
            "alert",
            "observability",
            "trace",
            "datadog",
            "grafana",
            "prometheus",
            "sentry",
        ],
    },
    {
        "name": "security",
        "keywords": [
            "security",
            "auth",
            "encrypt",
            "vault",
            "secret",
            "token",
            "oauth",
            "permission",
            "ssl",
            "tls",
        ],
    },
    {
        "name": "communication",
        "keywords": [
            "email",
            "slack",
            "discord",
            "telegram",
            "notification",
            "message",
            "chat",
            "sms",
            "twilio",
        ],
    },
    {
        "name": "productivity",
        "keywords": [
            "notion",
            "todoist",
            "calendar",
            "task",
            "project",
            "jira",
            "trello",
            "asana",
            "linear",
            "schedule",
        ],
    },
    {
        "name": "dev-tools",
        "keywords": [
            "lint",
            "format",
            "test",
            "debug",
            "compile",
            "build",
            "ci",
            "npm",
            "package",
            "cli",
            "terminal",
        ],
    },
    {
        "name": "data",
        "keywords": [
            "csv",
            "json",
            "xml",
            "yaml",
            "parse",
            "transform",
            "etl",
            "spreadsheet",
            "excel",
            "pandas",
        ],
    },
    {
        "name": "media",
        "keywords": [
            "image",
            "video",
            "audio",
            "media",
            "photo",
            "pdf",
            "document",
            "convert",
            "ffmpeg",
        ],
    },
]


def extract_keywords(name: str, description: str) -> list[str]:
    """Extract keywords from name and description for search indexing."""
    text = f"{name} {description}".lower()
    words = re.sub(r"[^\w\s-]", " ", text).split()
    words = [w for w in words if len(w) > 2 and w not in STOP_WORDS]
    return list(set(words))


def categorize_server(name: str, description: str) -> list[str]:
    """Categorize a server based on its name and description keywords."""
    text = f"{name} {description}".lower()
    matched = []

    for cat in CATEGORY_DEFS:
        if any(kw in text for kw in cat["keywords"]):
            matched.append(cat["name"])

    return matched if matched else ["other"]


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    """List all categories with their server counts."""
    cursor = conn.execute(
        "SELECT name, description FROM servers WHERE status = 'active'"
    )
    rows = cursor.fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        cats = categorize_server(row["name"], row["description"])
        for cat in cats:
            counts[cat] = counts.get(cat, 0) + 1

    result = []
    for cat_def in CATEGORY_DEFS:
        count = counts.get(cat_def["name"], 0)
        if count > 0:
            result.append(
                Category(
                    name=cat_def["name"],
                    count=count,
                    keywords=cat_def["keywords"],
                )
            )

    result.sort(key=lambda x: x.count, reverse=True)
    return result


def get_servers_by_category(
    conn: sqlite3.Connection, category: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Get servers in a specific category."""
    cat_def = None
    for c in CATEGORY_DEFS:
        if c["name"] == category.lower():
            cat_def = c
            break

    if not cat_def:
        return []

    conditions = " OR ".join(
        "(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)" for _ in cat_def["keywords"]
    )

    params = []
    for kw in cat_def["keywords"]:
        params.extend([f"%{kw}%", f"%{kw}%"])
    params.append(limit)

    sql = f"""SELECT name, description, version FROM servers
               WHERE status = 'active' AND ({conditions})
               ORDER BY updated_at DESC NULLS LAST
               LIMIT ?"""

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    return [
        {"name": r["name"], "description": r["description"], "version": r["version"]}
        for r in rows
    ]
