from pathlib import Path
from importlib.resources import files
from .core import Beacon
from .config import ServiceConfig, FilterConfig, AuthConfig


def from_vcf(
    filespec: str | Path,
    config: ServiceConfig | None = None,
    filter_config: FilterConfig | None = None,
    auth_config: AuthConfig | None = None,
) -> Beacon:
    """Create a Beacon v2 REST API from a VCF file.

    Args:
        filespec: Path to the VCF file.
        config: Service-level metadata (name, organization, contact, etc.).
            If omitted, defaults are used.
        filter_config: VCF row filter policy (quality threshold, PASS-only).
            If omitted, no rows filtered.
        auth_config: API key protection settings (number of keys, quota, key file).
            If omitted, the API is unprotected.

    Returns:
        A Beacon instance ready to be served, e.g. with fastapi run.
    """
    return Beacon(filespec, config=config, filter_config=filter_config, auth_config=auth_config)


def example_beacon() -> Beacon:
    """Return a Beacon instance loaded with the bundled VCF 4.2 example file.

    The file is the canonical example from the VCF 4.2 specification. Shipped
    as part of the beaconize package. Intended for testing, demos, and
    interactive exploration without an external VCF.
    """
    vcf_path = str(files("beaconize").joinpath("example.vcf"))
    return from_vcf(vcf_path)
