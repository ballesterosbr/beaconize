# Measurement data

This directory holds the data behind the experiments. Every file is a plain CSV with a header row. No individual level genotype data is included, only timings, memory readings and per-query counts.

All experiments run on the 1000 Genomes Project phase 3 genotype VCFs for chromosomes 22 and 2, on the GRCh37 assembly, files `ALL.chr{22,2}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz`. Those files are openly available from the [1000 Genomes phase 3 data release](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/) and are not copied here, since chromosome 2 alone is 1.2 GB. Chromosome 22 holds 1,103,547 variants and chromosome 2 holds 7,081,600, both over 2,504 samples.

## Query scalability

`benchmark_results_chr22.csv` and `benchmark_results_chr2.csv` hold the beaconize timings, measured in process. `benchmark_results_ri_chr22.csv` and `benchmark_results_ri_chr2.csv` hold the comparison against the reference implementation, where both systems are served over HTTP so that the measurement covers the same transport. All four share the same columns.

| Column | Meaning |
|---|---|
| `chromosome` | `22` or `2` |
| `experiment` | `scaling_N` (fixed 10 kb window, growing file) or `scaling_window` (full file, growing window) |
| `n_variants` | Number of variants in the file being queried |
| `window_bp` | Width of the query window in base pairs |
| `method` | See below |
| `rep` | Repeat index of this configuration |
| `seconds` | Wall-clock time of the single query |
| `window_hits` | Variants the query matched |

Each row is one repeat, so the medians and interquartile ranges reported in the article are computed from these rows rather than stored.

Values of `method`:

| Value | File | Meaning |
|---|---|---|
| `tabix` | beaconize files | Query resolved through the tabix index |
| `scan` | beaconize files | Same query against an unindexed copy of the file, forcing a full sequential scan |
| `bz_http` | RI files | beaconize served over HTTP by uvicorn |
| `ri` | RI files | The Beacon v2 reference implementation, loaded with the same chromosome through its own ETL process |

## Memory footprint

`benchmark_memory.csv` holds the peak resident set size of the serving process, measured in a fresh subprocess for every point, since peak RSS is a per-process high-water mark.

| Column | Meaning |
|---|---|
| `chromosome` | `22` or `2` |
| `n_variants` | Variants in the file, or `construct` for the baseline row |
| `file_bytes` | Size of the VCF file on disk |
| `method` | `construct` (the process has only read the VCF header) or `full_scan` (one parameter-less count query that streams every record) |
| `peak_rss_kib` | Peak resident set size in KiB |
| `hits` | Variants matched by the scan, empty for the baseline rows |

## Comparison with the reference implementation

`concordance_chr2.csv` holds the 3,000 queries issued against both systems on chromosome 2, and the count each one returned. There are 1,000 queries of each coordinate query type.

| Column | Meaning |
|---|---|
| `kind` | `sequence`, `range` or `bracket` |
| `scale` | Window width for a range query, tolerance around each breakpoint for a bracket query, empty for a sequence query |
| `start`, `end` | Query coordinates, 0-based interbase. A bracket query carries two values per bound |
| `referenceBases`, `alternateBases` | Alleles, for sequence queries |
| `variantType` | Empty throughout, the reference implementation rejects this parameter on sequence queries |
| `beaconize_count` | Count returned by beaconize |
| `ri_count` | Count returned by the reference implementation |
| `concordant` | `1` when both counts are identical, `0` otherwise |
| `category` | Why the two differ, see below |
| `touches_ri_missing` | `1` when the query can reach a record the reference implementation never ingested |

Values of `category`:

| Value | Rows | Meaning |
|---|---|---|
| `concordant` | 2,081 | Both systems returned the same count |
| `dropped_cnv` | 861 | The query reaches a symbolic structural record that the reference implementation's ingestion skips, reporting it as not supported yet |
| `range_boundary` | 48 | A variant lies exactly on a window edge, which beaconize excludes under the half-open interbase convention and the reference implementation includes |
| `dropped_cnv+range_boundary` | 7 | Both mechanisms act on the same query |
| `multiallelic_secondary` | 3 | The query asks for a secondary alternate allele of a multiallelic site, of which the ingestion keeps only the first |

Every query carried `assemblyId=GRCh37`, which the reference implementation requires. The reference implementation was deployed separately, loaded with the same chromosome through its own ETL process, and queried over HTTP.
