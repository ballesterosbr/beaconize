from dataclasses import dataclass
from typing import Literal

@dataclass
class ServiceConfig:
    """Service metadata describing the Beacon instance and its organization."""
    name: str = "beaconize"
    beacon_id: str | None = None
    description: str | None = None
    organization_name: str = "Beaconize"
    organization_url: str = "https://github.com/ballesterosbr/beaconize"
    organization_description: str | None = None
    contact_url: str | None = None
    base_url: str | None = None
    granularity: Literal["boolean", "count"] = "boolean"


@dataclass
class FilterConfig:
    """Controls which VCF rows are visible through the API.

    Both filters are applied independently and combined with AND logic.
    """
    min_qual: float | None = None     # exclude variants below this QUAL, or with none
    pass_only: bool = False           # if True, expose only FILTER=PASS variants


@dataclass
class AuthConfig:
    """API key protection settings."""
    api_keys_count: int = 0           # 0 disables key protection
    api_key_quota: int | None = None  # max /g_variants calls per key. None = unlimited
    api_keys_file: str | None = None  # write generated keys to this path (optional)
