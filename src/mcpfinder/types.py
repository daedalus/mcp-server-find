"""Core types for MCPfinder."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegistryEnvVar:
    """Environment variable definition."""

    name: str
    description: str | None = None
    format: str | None = None
    is_secret: bool = False


@dataclass
class ToolSummary:
    """Summary of a tool exposed by an MCP server."""

    name: str
    description: str | None = None
    kind: str = "tool"


@dataclass
class TrustSignals:
    """Trust signals for an MCP server."""

    has_official_source: bool
    is_verified: bool
    has_repository: bool
    has_remote: bool
    multi_source: bool
    has_recent_update: bool
    requires_secrets: bool


@dataclass
class ConfidenceBreakdown:
    """Breakdown of confidence score calculation."""

    score: float
    base: float
    official: float
    verified: float
    popularity: float
    multi_source: float
    penalties: float
    drivers: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """Search result returned to MCP clients."""

    name: str
    description: str
    version: str
    registry_type: str | None
    package_identifier: str | None
    transport_type: str | None
    repository_url: str | None
    has_remote: bool
    rank: int
    sources: list[str]
    use_count: int
    verified: bool
    icon_url: str | None
    updated_at: str | None
    published_at: str | None
    source_count: int
    confidence_score: float
    confidence_breakdown: ConfidenceBreakdown
    recommendation_reason: str
    warning_flags: list[str]
    trust_signals: TrustSignals
    freshness_days: int | None
    freshness_label: str
    install_complexity: str
    secret_count: int
    capability_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "registryType": self.registry_type,
            "packageIdentifier": self.package_identifier,
            "transportType": self.transport_type,
            "repositoryUrl": self.repository_url,
            "hasRemote": self.has_remote,
            "rank": self.rank,
            "sources": self.sources,
            "useCount": self.use_count,
            "verified": self.verified,
            "iconUrl": self.icon_url,
            "updatedAt": self.updated_at,
            "publishedAt": self.published_at,
            "sourceCount": self.source_count,
            "confidenceScore": self.confidence_score,
            "confidenceBreakdown": {
                "score": self.confidence_breakdown.score,
                "components": {
                    "base": self.confidence_breakdown.base,
                    "official": self.confidence_breakdown.official,
                    "verified": self.confidence_breakdown.verified,
                    "popularity": self.confidence_breakdown.popularity,
                    "multiSource": self.confidence_breakdown.multi_source,
                    "penalties": self.confidence_breakdown.penalties,
                },
                "drivers": self.confidence_breakdown.drivers,
            },
            "recommendationReason": self.recommendation_reason,
            "warningFlags": self.warning_flags,
            "trustSignals": {
                "hasOfficialSource": self.trust_signals.has_official_source,
                "isVerified": self.trust_signals.is_verified,
                "hasRepository": self.trust_signals.has_repository,
                "hasRemote": self.trust_signals.has_remote,
                "multiSource": self.trust_signals.multi_source,
                "hasRecentUpdate": self.trust_signals.has_recent_update,
                "requiresSecrets": self.trust_signals.requires_secrets,
            },
            "freshnessDays": self.freshness_days,
            "freshnessLabel": self.freshness_label,
            "installComplexity": self.install_complexity,
            "secretCount": self.secret_count,
            "capabilityCount": self.capability_count,
        }


@dataclass
class ServerDetail:
    """Detailed server information."""

    name: str
    description: str
    version: str
    registry_type: str | None
    package_identifier: str | None
    transport_type: str | None
    repository_url: str | None
    repository_source: str | None
    published_at: str | None
    updated_at: str | None
    status: str
    has_remote: bool
    remote_url: str | None
    categories: list[str]
    environment_variables: list[RegistryEnvVar]
    sources: list[str]
    use_count: int
    verified: bool
    icon_url: str | None
    source_count: int
    confidence_score: float
    confidence_breakdown: ConfidenceBreakdown
    recommendation_reason: str
    warning_flags: list[str]
    trust_signals: TrustSignals
    freshness_days: int | None
    freshness_label: str
    install_complexity: str
    secret_count: int
    capability_count: int
    tools_exposed: list[ToolSummary]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "registryType": self.registry_type,
            "packageIdentifier": self.package_identifier,
            "transportType": self.transport_type,
            "repositoryUrl": self.repository_url,
            "repositorySource": self.repository_source,
            "publishedAt": self.published_at,
            "updatedAt": self.updated_at,
            "status": self.status,
            "hasRemote": self.has_remote,
            "remoteUrl": self.remote_url,
            "categories": self.categories,
            "environmentVariables": [
                {
                    "name": ev.name,
                    "description": ev.description,
                    "format": ev.format,
                    "isSecret": ev.is_secret,
                }
                for ev in self.environment_variables
            ],
            "sources": self.sources,
            "useCount": self.use_count,
            "verified": self.verified,
            "iconUrl": self.icon_url,
            "sourceCount": self.source_count,
            "confidenceScore": self.confidence_score,
            "confidenceBreakdown": {
                "score": self.confidence_breakdown.score,
                "components": {
                    "base": self.confidence_breakdown.base,
                    "official": self.confidence_breakdown.official,
                    "verified": self.confidence_breakdown.verified,
                    "popularity": self.confidence_breakdown.popularity,
                    "multiSource": self.confidence_breakdown.multi_source,
                    "penalties": self.confidence_breakdown.penalties,
                },
                "drivers": self.confidence_breakdown.drivers,
            },
            "recommendationReason": self.recommendation_reason,
            "warningFlags": self.warning_flags,
            "trustSignals": {
                "hasOfficialSource": self.trust_signals.has_official_source,
                "isVerified": self.trust_signals.is_verified,
                "hasRepository": self.trust_signals.has_repository,
                "hasRemote": self.trust_signals.has_remote,
                "multiSource": self.trust_signals.multi_source,
                "hasRecentUpdate": self.trust_signals.has_recent_update,
                "requiresSecrets": self.trust_signals.requires_secrets,
            },
            "freshnessDays": self.freshness_days,
            "freshnessLabel": self.freshness_label,
            "installComplexity": self.install_complexity,
            "secretCount": self.secret_count,
            "capabilityCount": self.capability_count,
            "toolsExposed": [
                {"name": t.name, "description": t.description, "kind": t.kind}
                for t in self.tools_exposed
            ],
        }


@dataclass
class Category:
    """Category with server count."""

    name: str
    count: int
    keywords: list[str]


@dataclass
class InstallConfig:
    """Installation configuration for a platform."""

    client: str
    server_name: str
    config_file_path: str
    config: dict[str, Any]
    instructions: str
    post_install_note: str
    env_vars_needed: list[RegistryEnvVar]


# Registry API types
@dataclass
class RegistryServerEntry:
    """Raw server entry from Official MCP Registry."""

    name: str
    description: str | None
    version: str
    repository_url: str | None
    repository_source: str | None
    packages: list[dict[str, Any]] = field(default_factory=list)
    remotes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GlamaServer:
    """Server from Glama registry."""

    id: str
    name: str
    namespace: str | None
    slug: str
    description: str | None
    repository_url: str | None
    tools: list[Any] = field(default_factory=list)
    url: str | None = None
    environment_variables_json_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmitheryServer:
    """Server from Smithery registry."""

    qualified_name: str
    display_name: str
    description: str | None
    use_count: int
    verified: bool
    remote: bool
    is_deployed: bool
    icon_url: str | None
    homepage: str | None
    created_at: str | None
