# beaconize

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**beaconize** turns a VCF file into a running [Beacon v2](https://github.com/ga4gh-beacon/beacon-v2) REST API in one line.

There is no database and no ingestion step. The beacon reads the VCF file directly on every request, so any VCF works as it is. A bgzip + tabix index makes positional queries fast, but it is optional.

It uses [FastAPI](https://fastapi.tiangolo.com/) as the web framework and Pydantic models generated directly from the official GA4GH Beacon v2 JSON schemas.

**Intended use case.** An organization that has completed a variant analysis and wants selected partners to check, before any regulatory or data-access process begins, whether its dataset holds variants relevant to a possible collaboration. Each partner gets an API key and asks whether a variant is present, without any raw data leaving the holder. If the answers show a relevant overlap, the formal process can proceed. When the collaboration is settled, the beacon is shut down and leaves no store of variants or credentials behind.

> **Not a production Beacon network node.** Each instance serves one VCF file. There is no persistent database, no federation, and no multi-tenant key management, and it targets the low-volume, few-partner case rather than high query concurrency. For a production node of a Beacon network, use a full reference implementation.

---

## Installation

Requires **Python ≥ 3.11** and [uv](https://docs.astral.sh/uv/). Clone the repository and sync the environment:

```bash
git clone https://github.com/ballesterosbr/beaconize
cd beaconize
uv sync
```

This creates a `.venv` with all dependencies. Prefix commands with `uv run` (as below), or activate the environment with `source .venv/bin/activate`.

---

## Try it in one minute

The package ships a small example VCF, the canonical sample of the VCF 4.2 specification, so you can raise a beacon without any data of your own.

Create a new Python file, `beacon.py`, with an import and a call. The whole beacon is the `app` object:

```python
# beacon.py
from beaconize import example_beacon

app = example_beacon()
```

Serve that file:

```bash
uv run fastapi run beacon.py
```

`fastapi run` imports the module you name and serves its `app`, so the file can be called anything.

The beacon is now answering on `http://localhost:8000`. The example holds four variants on chromosome 20, so these queries return real answers:

```bash
# Is this exact allele present? (VCF POS=14370 is interbase start=14369)
curl "http://localhost:8000/g_variants?referenceName=20&start=14369&referenceBases=G&alternateBases=A"
# ... "responseSummary": {"exists": true}

# Any variant in this window?
curl "http://localhost:8000/g_variants?referenceName=20&start=1110000&end=1240000"
# ... "responseSummary": {"exists": true}

# The assembly guard, the example declares B36 in its header
curl "http://localhost:8000/g_variants?assemblyId=GRCh38"
# ... "responseSummary": {"exists": false}

# Beacon metadata
curl "http://localhost:8000/info"
```

Every response carries the Beacon v2 envelope, a `meta` block echoing the request and a `responseSummary` with the answer. At `count` granularity the summary also reports `numTotalResults`.

Interactive documentation for every endpoint is served at `http://localhost:8000/docs`.

### The same thing from Python

[`client_example.py`](client_example.py) issues one query of every kind against a running beacon, matching and non-matching, and prints what came back. The `beacon.py` above is unprotected, so it takes no key:

```bash
uv run python client_example.py
```

Only when the beacon was started with `AuthConfig`, as in the controlled-access example further down, pass one of its keys. The client then also exercises the access-control responses, a `401` for an invalid key and
a `429` once the key's quota is spent:

```bash
uv run python client_example.py --key "$(head -1 api_keys.txt)"
```

Both forms assume the beacon is on `http://127.0.0.1:8000`. Use `--url` to point the client elsewhere.

---

## Serving your own VCF

Write the same kind of file, but calling `from_vcf` with the path to your VCF. Everything else is optional:

```python
# beacon.py
from beaconize import from_vcf, ServiceConfig

app = from_vcf("variants.vcf", config=ServiceConfig(
    name="My Beacon",
    organization_name="My Org",
    contact_url="mailto:beacon@example.org",
))
```

Serve it the same way, with `uv run fastapi run beacon.py`.

A controlled-access beacon, again the same file, reporting counts instead of a plain yes or no, exposing only `PASS` rows and requiring an API key:

```python
# beacon.py
from beaconize import from_vcf, ServiceConfig, FilterConfig, AuthConfig

app = from_vcf("variants.vcf.gz",
    config=ServiceConfig(
        name="My Beacon",
        organization_name="My Org",
        contact_url="mailto:beacon@example.org",
        granularity="count",
    ),
    filter_config=FilterConfig(pass_only=True),
    auth_config=AuthConfig(api_keys_count=10, api_key_quota=100, api_keys_file="api_keys.txt"),
)
```

Generated API keys are printed to the console at startup and written to `api_keys.txt`. Clients send them in the `X-API-Key` header:

```bash
KEY=$(head -1 api_keys.txt)
curl -H "X-API-Key: $KEY" "http://localhost:8000/g_variants?referenceName=20&start=14369"
```

---

## A whole chromosome, end to end

This example serves human chromosome 2 of the 1000 Genomes Project phase 3 release, 7,081,600 variants over 2,504 samples on GRCh37, and issues one query of each coordinate type against it. These are the same queries the accompanying article reports.

Two files are needed, both openly available from the
[1000 Genomes phase 3 data release](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/):

```
ALL.chr2.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz
ALL.chr2.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz.tbi
```

The second one is the tabix index the release already ships. Nothing has to be configured for it, the beacon looks for a file with the name of the VCF plus `.tbi` or `.csi` next to it, and uses it if it is there. Point `from_vcf` at the VCF alone and serve it at count granularity:

```python
# beacon.py
from beaconize import from_vcf, ServiceConfig

app = from_vcf(
    "ALL.chr2.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz",
    config=ServiceConfig(name="1000G chr2", granularity="count"),
)
```

```bash
uv run fastapi run beacon.py
```

Start-up reads the VCF header only, so it does not grow with the size of the file. Then, one query of each coordinate type:

```bash
# Sequence, one exact allele
curl "http://localhost:8000/g_variants?referenceName=2&assemblyId=GRCh37\
&start=75940816&referenceBases=C&alternateBases=T"
# ... "numTotalResults": 1

# Range, everything overlapping a 50 kb window
curl "http://localhost:8000/g_variants?referenceName=2&assemblyId=GRCh37\
&start=144097024&end=144147024"
# ... "numTotalResults": 1414

# Bracket, two values per bound, for a structural variant with fuzzy breakpoints
curl "http://localhost:8000/g_variants?referenceName=2&assemblyId=GRCh37\
&start=31231873&start=31231979&end=31231911&end=31231943"
# ... "numTotalResults": 1
```

---

## Configuration

`from_vcf` accepts three independent, optional config objects.

### ServiceConfig — service identity and response behaviour

Nothing is left blank when a field is omitted, and no default reveals anything about the file being served, neither its name nor how many sequences or samples it holds. `beacon_id` is built from the organization name and `base_url` from the incoming request, while the rest carry a literal default. A field that ends up with no value at all is dropped from the response rather than reported as `null`, which is what the Beacon v2 schemas expect.

| Field | Accepted values | Default | Description |
|---|---|---|---|
| `name` | text | `"beaconize"` | Beacon display name |
| `beacon_id` | text | `org.<organization_name>.beacon` | Identifier that tells this beacon apart from others in a network. A reversed domain string by convention |
| `description` | text | `Ephemeral Beacon v2 API served from a VCF file` | Human-readable description |
| `organization_name` | text | `"Beaconize"` | Organization name |
| `organization_url` | URL | beaconize GitHub URL | Organization website |
| `organization_description` | text | `None` | Organization description |
| `contact_url` | URL or `mailto:` | unset | Who to contact about this beacon. Left unset, `/service-info` reports `organization_url` in its place and `/info` omits the field |
| `base_url` | URL | derived from request | Override canonical URL (useful behind a proxy) |
| `granularity` | `"boolean"` or `"count"` | `"boolean"` | `"boolean"` answers exists only, `"count"` adds the number of matches |

### FilterConfig — VCF row visibility

Both filters are applied to every row and combined with AND logic.

| Field | Accepted values | Default | Description |
|---|---|---|---|
| `min_qual` | a number, or `None` for no threshold | `None` | Hide variants whose QUAL is below this value, and also those carrying no QUAL at all |
| `pass_only` | `True` or `False` | `False` | With `True`, expose only variants whose FILTER field is `PASS` |

### AuthConfig — API key protection

| Field | Accepted values | Default | Description |
|---|---|---|---|
| `api_keys_count` | a whole number, `0` disables key protection | `0` | How many API keys to generate at startup |
| `api_key_quota` | a whole number, or `None` for unlimited | `None` | Maximum calls to `/g_variants` per key |
| `api_keys_file` | a path, or `None` to only print them | `None` | Where to write the generated keys, one per line |

When `api_keys_count > 0`, every endpoint requires a valid `X-API-Key` header. Keys are random 32-byte URL-safe tokens generated in memory at startup, printed to the console, and optionally written to a file. They are ephemeral, a server restart produces a fresh set.

The quota applies only to the genomic endpoint, counting both `/g_variants` and its legacy alias. Every
other endpoint stays reachable for the lifetime of the key.

| HTTP status | Meaning |
|---|---|
| `401 Unauthorized` | Missing or invalid API key |
| `429 Too Many Requests` | The key's `/g_variants` quota is exhausted |

---

## Endpoints

### Informational

| Endpoint | Description |
|---|---|
| `GET /info` | General Beacon metadata |
| `GET /service-info` | GA4GH service registry metadata |
| `GET /configuration` | Supported entry types, granularity, and security |
| `GET /entry_types` | Entry type definitions |
| `GET /map` | Available endpoints (sitemap) |
| `GET /filtering_terms` | Ontology filters, always an empty list, since a VCF carries no ontology terms |

### Genomic variants

```
GET /g_variants
POST /g_variants
```

All parameters are optional and are combined with AND logic. `POST` takes the same parameters inside the `query.requestParameters` object of the JSON body.

| Parameter | VCF field | Notes |
|---|---|---|
| `referenceName` | CHROM | e.g. `20` |
| `start` | POS | 0-based interbase (see **Query types** below) |
| `end` | POS + len(REF), or INFO/END for a symbolic allele | 0-based interbase (see **Query types** below) |
| `referenceBases` | REF | e.g. `G` |
| `alternateBases` | ALT | matches any ALT allele |
| `variantType` | derived | `SNV`, `INS`, `DEL`, `MNV`, or symbolic (`DUP`, `CNV`, …) |
| `assemblyId` | `##contig assembly=` header | e.g. `GRCh38`, compared against the header. See the note below |
| `includeResultsetResponses` | not a filter | `ALL`, `HIT`, `MISS` or `NONE`, echoed back in the response `meta`. Anything else is reported as `NONE` |

**Query types** — the three coordinate-based Beacon v2 query types:

- **Sequence** — single `start` (+ optional `referenceBases`/`alternateBases`): the exact allele at a position.
- **Range** — single `start` + single `end`: any variant that **overlaps** the window `[start, end)`.
- **Bracket** — two values for `start` and `end` (`start=A&start=B`): structural variants with fuzzy breakpoints.

`geneId`, HGVS (`genomicAlleleShortForm`) and `aminoacidChange` queries are **not** supported, they require external annotation (gene→coordinates, variant normalization) that a VCF-only backend does not have.

**Coordinate note.** VCF uses 1-based positions; Beacon v2 uses 0-based interbase.
A SNP at VCF `POS=14370` is queried as `start=14369` (or `end=14370`).

**The assembly check.** A query that names an assembly is compared against the one the VCF header declares.
If the two disagree, the answer is `false` and no variant is read at all. If the header declares no assembly, there is nothing to compare and any value is accepted.

Both names are normalized before being compared, so `GRCh37`, `b37`, `hg19` and `hs37d5` all match a file whose header declares any of them. The GRCh36, GRCh37, GRCh38 and T2T-CHM13 build families are covered. A name outside those families is compared as it is written.

**Indexing (optional but recommended).** Any VCF works as it is. A bgzip + tabix index (`.tbi` or `.csi`) makes positional queries fast, since the beacon seeks straight to the region. Without an index it falls back to a full sequential scan, with the **same results, just slower**.

> `/g_variants` is the canonical Beacon v2 path; `/genomicVariants` is kept as a legacy alias.

### Biosamples

```
GET /biosamples
POST /biosamples
```

A fixed boolean response reporting whether the VCF carries genotype columns. A VCF has no biosample metadata, so this is not a queryable entry type.

Beacon v2 does not require every entry type to be implemented, only those declared in `/configuration` and `/entry_types`. beaconize omits `/datasets`, `/cohorts`, `/analyses` and `/runs` on purpose, because of what a VCF file actually is. A VCF is the output of one analysis run, not a dataset and not a cohort. It encodes biosamples as columns but carries no metadata about them. A given file may well come from a dataset or reflect a cohort, yet that depends on the study design rather than on anything the file states, so beaconize exposes the variant calls as they are and assumes nothing further.

---

## Regenerating Pydantic models

The models in `src/beaconize/models/` are generated automatically from the official Beacon v2 JSON schemas.
**Do not edit them by hand.**

To regenerate after a spec update:

```bash
bash generate.sh
```

The script fetches schemas from the [ga4gh-beacon/beacon-v2](https://github.com/ga4gh-beacon/beacon-v2) repository and writes Pydantic v2 models using `datamodel-codegen`.

---

## Measurement data

`results/` holds the data behind the experiments reported in the accompanying article, the query times of the scalability experiment, the memory footprint measurements, and the comparison against the Beacon v2 reference implementation. See [results/README.md](results/README.md) for what each file contains.

---

## License

MIT — see [LICENSE](LICENSE).
