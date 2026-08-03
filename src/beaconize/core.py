from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from .models.response_info import (
    BeaconInfoResults,
    BeaconOrganization,
    BeaconInformationalResponseMeta as InfoResponseMeta,
    Model as BeaconInfoResponse,
)
from .models.response_bool import (
    BeaconReceivedRequestSummary,
    BeaconResponseMeta,
    BeaconBooleanResponseSection,
    Model as BeaconBooleanResponse,
)
from .models.response_count import (
    BeaconCountResponseSection,
    BeaconReceivedRequestSummary as CountRequestSummary,
    BeaconResponseMeta as CountResponseMeta,
    CountPrecision,
    Model as BeaconCountResponse,
)
from .models.service_info import (
    Ga4GhServiceInfoApiSpecification,
    Organization as ServiceOrganization,
    ServiceType,
)
from .models.configuration import (
    Model as BeaconConfigurationResponse,
    BeaconConfigurationSchema,
    BeaconInformationalResponseMeta as ConfigResponseMeta,
    EntryTypes,
    MaturityAttributes,
    SecurityAttributes,
    ProductionStatus,
    EntryTypeDefinition,
    ReferenceToAnSchema,
)
from .models.EntryTypesResponse import (
    Model as BeaconEntryTypesResponse,
    BeaconInformationalResponseMeta as EntryTypesResponseMeta,
    EntryTypesSchema,
    EntryTypeDefinition as ETEntryTypeDefinition,
    ReferenceToAnSchema as ETReferenceToAnSchema,
)
from .models.MapResponse import (
    Model as BeaconMapResponse,
    BeaconInformationalResponseMeta as MapResponseMeta,
    BeaconMapSchema,
    Endpoint as MapEndpoint,
)
from .models.FilteringTermsResponse import (
    Model as BeaconFilteringTermsResponse,
    BeaconInformationalResponseMeta as FilteringTermsResponseMeta,
    BeaconFilteringTermsResults,
)
import datetime
import os
import re
import secrets
from importlib.metadata import version
from pathlib import Path
import cyvcf2
import logging
from .config import ServiceConfig, FilterConfig, AuthConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

__version__ = version("beaconize")

BEACON_API_VERSION = "v2.0.0"

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Common assembly aliases -> canonical name (case-insensitive).
_ASSEMBLY_SYNONYMS = {
    "grch38": "GRCh38", "hg38": "GRCh38", "b38": "GRCh38", "hs38": "GRCh38", "hs38d1": "GRCh38",
    "grch37": "GRCh37", "hg19": "GRCh37", "b37": "GRCh37", "hs37": "GRCh37", "hs37d5": "GRCh37",
    "grch36": "GRCh36", "ncbi36": "GRCh36", "hg18": "GRCh36", "b36": "GRCh36",
    "t2t": "T2T-CHM13", "chm13": "T2T-CHM13", "t2t-chm13": "T2T-CHM13", "hs1": "T2T-CHM13",
}


class Beacon(FastAPI):

    def _create_database(self):
        vcf = cyvcf2.VCF(self.filespec)
        self.seqnames = list(vcf.seqnames)
        self.samples = list(vcf.samples)
        m = re.search(r'##contig=<[^>]*\bassembly=([^,>\s]+)', vcf.raw_header)
        self.assembly_id: str | None = m.group(1) if m else None
        vcf.close()

    @staticmethod
    def _normalize_assembly(name: str | None) -> str | None:
        """Map an assembly alias (b37, hg19, hs37d5, ...) to its canonical name."""
        if not name:
            return None
        return _ASSEMBLY_SYNONYMS.get(name.strip().lower(), name)

    @staticmethod
    def _variant_type(ref: str, alt: str) -> str:
        if alt.startswith("<") and alt.endswith(">"):
            return alt[1:-1]
        if len(ref) == 1 and len(alt) == 1:
            return "SNV"
        if len(alt) > len(ref):
            return "INS"
        if len(alt) < len(ref):
            return "DEL"
        return "MNV"

    @staticmethod
    def _matches_position(b_start: int, b_end: int, starts: list[int], ends: list[int]) -> bool:
        # [b_start, b_end) is the variant's half-open interbase span, taken from
        # cyvcf2: POS-1 and POS-1+len(REF) for a spelled-out variant, or INFO/END
        # for a symbolic structural allele (<DEL>, <CN0>, ...) whose REF holds
        # only the anchor base.

        # Range query: single start + single end -> match any variant overlapping the window
        if len(starts) == 1 and len(ends) == 1:
            return b_start < ends[0] and b_end > starts[0]

        # Each bound independently: 1 value -> exact match, 2 values -> within [min, max]
        if len(starts) == 1 and b_start != starts[0]:
            return False
        if len(starts) == 2 and not (starts[0] <= b_start <= starts[1]):
            return False
        if len(ends) == 1 and b_end != ends[0]:
            return False
        if len(ends) == 2 and not (ends[0] <= b_end <= ends[1]):
            return False
        return True

    def _passes_row_filter(self, variant) -> bool:
        """Return False if the variant is excluded by the configured QUAL/FILTER policy."""
        if self.min_qual is not None:
            qual = variant.QUAL
            if qual is None or qual < self.min_qual:
                return False
        if self.pass_only:
            f = variant.FILTER
            if f is not None and f != "PASS":
                return False
        return True

    @staticmethod
    def _region_spec(reference_name: str | None, starts: list[int], ends: list[int]) -> str | None:
        """Build a 1-based chrom:start-end region that is a superset of what can match
        (_matches_position still filters precisely), or None to scan the whole
        file (no chromosome, or no start bound)."""
        if not reference_name or not starts:
            return None
        lo = min(starts) + 1  # interbase start -> 1-based POS
        hi = max(starts + ends) + 1
        if lo > hi:
            return None
        return f"{reference_name}:{lo}-{hi}"

    def _has_index(self) -> bool:
        """True when a tabix/CSI index is next to the VCF."""
        return any(os.path.exists(self.filespec + ext) for ext in (".tbi", ".csi"))

    def _variant_iter(self, vcf, reference_name: str | None, starts: list[int], ends: list[int]):
        """Iterate candidate variants: a tabix region when one can be derived and
        the VCF is indexed, otherwise a full sequential scan."""
        region = self._region_spec(reference_name, starts, ends)
        if region is None or not self._has_index():
            return vcf
        try:
            return vcf(region)
        except Exception:
            # Unindexed/plain-text VCF or malformed region -> fallback to a full scan.
            return vcf

    def _query_database(
        self,
        reference_name: str | None,
        starts: list[int],
        ends: list[int],
        reference_bases: str | None,
        alternate_bases: str | None,
        variant_type: str | None,
        assembly_id: str | None,
    ) -> int:
        """Return the number of matching variants (0 if none).

        For boolean granularity the scan stops at the first match, returning 1.
        """
        if (assembly_id and self.assembly_id
                and self._normalize_assembly(assembly_id) != self._normalize_assembly(self.assembly_id)):
            return 0
        count = 0
        vcf = cyvcf2.VCF(self.filespec)
        try:
            for variant in self._variant_iter(vcf, reference_name, starts, ends):
                if not self._passes_row_filter(variant):
                    continue
                if reference_name and variant.CHROM != reference_name:
                    continue
                if (starts or ends) and not self._matches_position(
                    variant.start, variant.end, starts, ends
                ):
                    continue
                if reference_bases and variant.REF != reference_bases:
                    continue
                alts = variant.ALT
                if alternate_bases:
                    if alternate_bases not in alts:
                        continue
                    alts = [alternate_bases]
                if variant_type:
                    if not any(self._variant_type(variant.REF, a) == variant_type for a in alts):
                        continue
                count += 1
                if self.granularity == "boolean":
                    return count
        finally:
            vcf.close()
        return count

    def _setup_api_keys(self, auth: AuthConfig) -> None:
        """Generate API keys and print them in the console (optionally into a file)."""
        self._api_keys: dict[str, int] = {}
        self.api_key_quota = auth.api_key_quota
        if auth.api_keys_count <= 0:
            return
        keys = [secrets.token_urlsafe(32) for _ in range(auth.api_keys_count)]
        for k in keys:
            self._api_keys[k] = 0
        quota_label = str(auth.api_key_quota) if auth.api_key_quota is not None else "unlimited"
        lines = [
            "=" * 56,
            "  Beaconize - generated API keys",
            f"  Quota: {quota_label} calls to /g_variants per key",
            "-" * 56,
        ] + [f"  {k}" for k in keys] + ["=" * 56]
        for line in lines:
            logger.info(line)
        if auth.api_keys_file:
            with open(auth.api_keys_file, "w") as fh:
                fh.write("\n".join(keys) + "\n")
            logger.info("API keys written to %s", auth.api_keys_file)

    def _auth_dep(self, track_quota: bool = False):
        """Return a FastAPI dependency that validates the X-API-Key header."""
        async def _check(api_key: str | None = Security(_api_key_header)):
            if not self._api_keys:
                return  # no protection
            if not api_key or api_key not in self._api_keys:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing API key",
                )
            if track_quota and self.api_key_quota is not None:
                if self._api_keys[api_key] >= self.api_key_quota:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Quota exhausted for this API key",
                    )
                self._api_keys[api_key] += 1
        return _check

    def __init__(
        self,
        filespec: str | Path,
        config: ServiceConfig | None = None,
        filter_config: FilterConfig | None = None,
        auth_config: AuthConfig | None = None,
    ):
        cfg = config or ServiceConfig()
        flt = filter_config or FilterConfig()
        auth = auth_config or AuthConfig()
        super().__init__(title=cfg.name)
        self.filespec = str(filespec)
        self.granularity = cfg.granularity
        self.min_qual = flt.min_qual
        self.pass_only = flt.pass_only
        self._setup_api_keys(auth)
        self._create_database()

        _org_slug = cfg.organization_name.lower().replace(" ", "-")
        _beacon_id = cfg.beacon_id or f"org.{_org_slug}.beacon"
        _description = cfg.description or "Ephemeral Beacon v2 API served from a VCF file"
        _now = datetime.datetime.now(datetime.timezone.utc)

        org = BeaconOrganization(
            id=_org_slug,
            name=cfg.organization_name,
            description=cfg.organization_description,
            welcomeUrl=cfg.organization_url,
            contactUrl=cfg.contact_url,
        )
        info_results = BeaconInfoResults(
            apiVersion=BEACON_API_VERSION,
            environment="prod",
            id=_beacon_id,
            name=cfg.name,
            description=_description,
            organization=org,
            version=__version__,
            createDateTime=_now.isoformat(),
            updateDateTime=_now.isoformat(),
        )
        self.info = BeaconInfoResponse(
            meta=InfoResponseMeta(
                apiVersion=BEACON_API_VERSION,
                beaconId=_beacon_id,
                returnedSchemas=[],
            ),
            response=info_results,
        )

        service_org = ServiceOrganization(name=cfg.organization_name, url=cfg.organization_url)
        self.service_info = Ga4GhServiceInfoApiSpecification(
            id=_beacon_id,
            name=cfg.name,
            type=ServiceType(artifact="beacon", group="org.ga4gh", version="2.0.0"),
            description=_description,
            organization=service_org,
            contactUrl=cfg.contact_url or cfg.organization_url,
            documentationUrl="https://github.com/ballesterosbr/beaconize",
            createdAt=_now,
            version=__version__,
            environment="prod",
        )

        config_schema = BeaconConfigurationSchema(
            **{"$schema": "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/framework/json/responses/beaconConfigurationResponse.json"},
            entryTypes=EntryTypes(
                root={
                    "genomicVariant": EntryTypeDefinition(
                        id="genomicVariant",
                        name="Genomic Variant",
                        description="Boolean genomic variant queries from VCF data",
                        defaultSchema=ReferenceToAnSchema(
                            id="genomicVariant",
                            name="Genomic Variant",
                            referenceToSchemaDefinition="https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/models/json/beacon-v2-default-model/genomicVariations/defaultSchema.json",
                        ),
                        partOfSpecification="Beacon v2.0",
                    ),
                    "biosample": EntryTypeDefinition(
                        id="biosample",
                        name="Biosample",
                        description="Boolean: false (no biosample data in VCF)",
                        defaultSchema=ReferenceToAnSchema(
                            id="biosample",
                            name="Biosample",
                            referenceToSchemaDefinition="https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/models/json/beacon-v2-default-model/biosamples/defaultSchema.json",
                        ),
                        partOfSpecification="Beacon v2.0",
                    ),
                }
            ),
            maturityAttributes=MaturityAttributes(productionStatus=ProductionStatus.PROD),
            securityAttributes=SecurityAttributes(
                defaultGranularity=cfg.granularity,
                securityLevels=["CONTROLLED"] if self._api_keys else ["PUBLIC"],
            ),
        )
        self.configuration = BeaconConfigurationResponse(
            meta=ConfigResponseMeta(
                apiVersion=BEACON_API_VERSION,
                beaconId=_beacon_id,
                returnedSchemas=[],
            ),
            response=config_schema,
        )

        self.entry_types = BeaconEntryTypesResponse(
            meta=EntryTypesResponseMeta(
                apiVersion=BEACON_API_VERSION,
                beaconId=_beacon_id,
                returnedSchemas=[],
            ),
            response=EntryTypesSchema(
                entryTypes={
                    "genomicVariant": ETEntryTypeDefinition(
                        id="genomicVariant",
                        name="Genomic Variant",
                        description="Boolean genomic variant queries from VCF data",
                        defaultSchema=ETReferenceToAnSchema(
                            id="genomicVariant",
                            name="Genomic Variant",
                            referenceToSchemaDefinition="https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/models/json/beacon-v2-default-model/genomicVariations/defaultSchema.json",
                        ),
                        partOfSpecification="Beacon v2.0",
                    ),
                    "biosample": ETEntryTypeDefinition(
                        id="biosample",
                        name="Biosample",
                        description="Boolean: false (no biosample data in VCF)",
                        defaultSchema=ETReferenceToAnSchema(
                            id="biosample",
                            name="Biosample",
                            referenceToSchemaDefinition="https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/models/json/beacon-v2-default-model/biosamples/defaultSchema.json",
                        ),
                        partOfSpecification="Beacon v2.0",
                    ),
                }
            ),
        )

        self.filtering_terms = BeaconFilteringTermsResponse(
            meta=FilteringTermsResponseMeta(
                apiVersion=BEACON_API_VERSION,
                beaconId=_beacon_id,
                returnedSchemas=[],
            ),
            response=BeaconFilteringTermsResults(filteringTerms=[], resources=[]),
        )

        def _bool_response(exists: bool) -> BeaconBooleanResponse:
            return BeaconBooleanResponse(
                meta=BeaconResponseMeta(
                    apiVersion=BEACON_API_VERSION,
                    beaconId=_beacon_id,
                    receivedRequestSummary=BeaconReceivedRequestSummary(
                        apiVersion=BEACON_API_VERSION,
                        filters=[],
                        requestParameters={},
                        includeResultsetResponses="NONE",
                        pagination={},
                        requestedGranularity="boolean",
                        requestedSchemas=[],
                    ),
                    returnedGranularity="boolean",
                    returnedSchemas=[],
                ),
                responseSummary=BeaconBooleanResponseSection(exists=exists),
            )

        self.biosamples = _bool_response(exists=len(self.samples) > 0)

        _auth = self._auth_dep()
        _auth_quota = self._auth_dep(track_quota=True)

        @self.get("/info", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def info() -> BeaconInfoResponse:
            return self.info

        @self.get("/service-info", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def service_info() -> Ga4GhServiceInfoApiSpecification:
            return self.service_info

        @self.get("/configuration", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def configuration() -> BeaconConfigurationResponse:
            return self.configuration

        @self.get("/entry_types", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def entry_types() -> BeaconEntryTypesResponse:
            return self.entry_types

        @self.get("/filtering_terms", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def filtering_terms() -> BeaconFilteringTermsResponse:
            return self.filtering_terms

        @self.get("/map", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def map(request: Request) -> BeaconMapResponse:
            base = cfg.base_url or str(request.base_url).rstrip("/")
            return BeaconMapResponse(
                meta=MapResponseMeta(
                    apiVersion=BEACON_API_VERSION,
                    beaconId=_beacon_id,
                    returnedSchemas=[],
                ),
                response=BeaconMapSchema(
                    **{"$schema": "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/framework/json/configuration/beaconMapSchema.json"},
                    endpointSets={
                        "genomicVariant": MapEndpoint(
                            entryType="genomicVariant",
                            rootUrl=f"{base}/g_variants",
                        ),
                        "biosample": MapEndpoint(
                            entryType="biosample",
                            rootUrl=f"{base}/biosamples",
                        ),
                    },
                ),
            )

        @self.get("/biosamples", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def biosamples() -> BeaconBooleanResponse:
            return self.biosamples

        @self.post("/biosamples", dependencies=[Depends(_auth)], response_model_exclude_none=True)
        async def biosamples_post() -> BeaconBooleanResponse:
            # No filters in the body. Same answer as GET.
            return self.biosamples

        def _include_resultset(value: str | None) -> str:
            # Echoed back to pick the schema the response is validated against.
            # No per-dataset resultSets here. Absent or unknown -> NONE.
            return value if value in {"ALL", "HIT", "MISS", "NONE"} else "NONE"

        def _genomic_response(
            referenceName: str | None,
            start: list[int] | None,
            end: list[int] | None,
            referenceBases: str | None,
            alternateBases: str | None,
            variantType: str | None,
            assemblyId: str | None,
            includeResultsetResponses: str,
        ):
            count = self._query_database(
                reference_name=referenceName,
                starts=start or [],
                ends=end or [],
                reference_bases=referenceBases,
                alternate_bases=alternateBases,
                variant_type=variantType,
                assembly_id=assemblyId,
            )
            request_parameters = {
                k: v
                for k, v in {
                    "referenceName": referenceName,
                    "start": start,
                    "end": end,
                    "referenceBases": referenceBases,
                    "alternateBases": alternateBases,
                    "variantType": variantType,
                    "assemblyId": assemblyId,
                }.items()
                if v is not None
            }
            if self.granularity == "count":
                response = BeaconCountResponse(
                    meta=CountResponseMeta(
                        apiVersion=BEACON_API_VERSION,
                        beaconId=_beacon_id,
                        receivedRequestSummary=CountRequestSummary(
                            apiVersion=BEACON_API_VERSION,
                            filters=[],
                            requestParameters=request_parameters,
                            includeResultsetResponses=includeResultsetResponses,
                            pagination={},
                            requestedGranularity="count",
                            requestedSchemas=[],
                        ),
                        returnedGranularity="count",
                        returnedSchemas=[],
                    ),
                    responseSummary=BeaconCountResponseSection(
                        exists=count > 0,
                        numTotalResults=count,
                        countPrecision=CountPrecision.exact,
                    ),
                )
            else:
                response = BeaconBooleanResponse(
                    meta=BeaconResponseMeta(
                        apiVersion=BEACON_API_VERSION,
                        beaconId=_beacon_id,
                        receivedRequestSummary=BeaconReceivedRequestSummary(
                            apiVersion=BEACON_API_VERSION,
                            filters=[],
                            requestParameters=request_parameters,
                            includeResultsetResponses=includeResultsetResponses,
                            pagination={},
                            requestedGranularity="boolean",
                            requestedSchemas=[],
                        ),
                        returnedGranularity="boolean",
                        returnedSchemas=[],
                    ),
                    responseSummary=BeaconBooleanResponseSection(exists=count > 0),
                )
            # exclude_none: the schemas require unset fields absent, not null.
            return JSONResponse(response.model_dump(mode="json", exclude_none=True))

        @self.get("/genomicVariants", dependencies=[Depends(_auth_quota)])
        @self.get("/g_variants", dependencies=[Depends(_auth_quota)])
        async def genomic_variants(
            referenceName: str | None = Query(None, description="Chromosome name (CHROM)"),
            start: list[int] | None = Query(None, description="0-based interbase start. One value for exact, two [min,max] for bracket query"),
            end: list[int] | None = Query(None, description="0-based interbase end. One value for exact, two [min,max] for bracket query"),
            referenceBases: str | None = Query(None, description="Reference bases (REF)"),
            alternateBases: str | None = Query(None, description="Alternate bases (ALT)"),
            variantType: str | None = Query(None, description="Variant type: SNV, INS, DEL, MNV, or symbolic (DUP, CNV, ...)"),
            assemblyId: str | None = Query(None, description="Reference genome assembly identifier"),
            includeResultsetResponses: str | None = Query(None, description="Which resultset responses to include: ALL, HIT, MISS or NONE"),
        ):
            return _genomic_response(
                referenceName=referenceName,
                start=start,
                end=end,
                referenceBases=referenceBases,
                alternateBases=alternateBases,
                variantType=variantType,
                assemblyId=assemblyId,
                includeResultsetResponses=_include_resultset(includeResultsetResponses),
            )

        @self.post("/genomicVariants", dependencies=[Depends(_auth_quota)])
        @self.post("/g_variants", dependencies=[Depends(_auth_quota)])
        async def genomic_variants_post(request: Request):
            # Same parameters, read from the body's query block.
            # An empty body queries everything.
            try:
                body = await request.json()
            except Exception:
                body = {}
            query = (body or {}).get("query") or {}
            params = query.get("requestParameters") or {}

            def _as_list(value):
                if value is None:
                    return None
                return value if isinstance(value, list) else [value]

            return _genomic_response(
                referenceName=params.get("referenceName"),
                start=_as_list(params.get("start")),
                end=_as_list(params.get("end")),
                referenceBases=params.get("referenceBases"),
                alternateBases=params.get("alternateBases"),
                variantType=params.get("variantType"),
                assemblyId=params.get("assemblyId"),
                includeResultsetResponses=_include_resultset(query.get("includeResultsetResponses")),
            )
