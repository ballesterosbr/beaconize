"""Example client for a running beaconize instance.

One query of every kind, matching and non-matching. Start the beacon first:

    uv run fastapi run beacon.py
    uv run python client_example.py

On a protected beacon, pass a key to test access control responses:

    uv run python client_example.py --key <API_KEY>

Queries target the VCF 4.2 example bundled with the package, four variants on
chromosome 20. Descriptions state the correct answer.

Default target is http://127.0.0.1:8000. --url reaches a beacon on another port or
host:

    uv run python client_example.py --url http://beacon.example.org:8000
"""

import argparse
import httpx

CHROM = "20"

# VCF POS 14370 -> interbase start 14369. Same rule below.
EXACT_SNV = {"referenceName": CHROM, "start": 14369, "referenceBases": "G", "alternateBases": "A"}


def query(client: httpx.Client, description: str, params, headers=None) -> None:
    r = client.get("/g_variants", params=params, headers=headers or {})
    print(f"  [{r.status_code}] {description}")
    if r.status_code == 401:
        print("         -> unauthorized, the API key is missing or invalid")
    elif r.status_code == 429:
        print("         -> quota exhausted, this API key has no calls left")
    else:
        summary = r.json().get("responseSummary", {})
        line = f"exists={summary.get('exists')}"
        if summary.get("numTotalResults") is not None:
            line += f", numTotalResults={summary['numTotalResults']}"
        print(f"         -> {line}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="beacon base URL")
    parser.add_argument("--key", default=None, help="X-API-Key header value")
    args = parser.parse_args()

    headers = {"X-API-Key": args.key} if args.key else {}

    with httpx.Client(base_url=args.url, headers=headers, timeout=30) as client:
        print(f"Querying {args.url}/g_variants\n")

        # --- Sequence, one exact allele ---
        query(client, "Sequence, SNV G>A at interbase 14369 (VCF POS 14370), exists", EXACT_SNV)

        query(client, "Sequence, same position with the wrong REF, does not exist",
              {"referenceName": CHROM, "start": 14369, "referenceBases": "T"})

        # A>G,T at VCF POS 1110696. Any ALT of the record matches.
        query(client, "Sequence, the second allele (T) of a multiallelic site, exists",
              {"referenceName": CHROM, "start": 1110695, "alternateBases": "T"})

        # --- Range, anything overlapping a window ---
        query(client, "Range, the window holding the last three variants, exists",
              {"referenceName": CHROM, "start": 1110000, "end": 1240000})

        query(client, "Range, an empty window further along the chromosome, does not exist",
              {"referenceName": CHROM, "start": 2000000, "end": 2100000})

        query(client, "Range restricted by type, any deletion on the chromosome, exists",
              {"referenceName": CHROM, "variantType": "DEL"})

        # --- Bracket, two values per bound ---
        # Each breakpoint lands in its own window. GTC>G at POS 1234567 spans
        # interbase [1234566, 1234569). A symbolic record spans POS to INFO/END.
        # The second window has to reach that far.
        query(client, "Bracket, both breakpoints inside 1,234,000-1,235,000, exists",
              [("referenceName", CHROM), ("start", 1234000), ("start", 1235000),
               ("end", 1234000), ("end", 1235000)])

        # --- Assembly guard ---
        query(client, "Assembly, hg18 is an alias of B36, exists",
              {"assemblyId": "hg18"})

        query(client, "Assembly, GRCh38 does not match the file, does not exist",
              {"assemblyId": "GRCh38"})

        # --- Access control, protected beacon only ---
        if not args.key:
            print("No --key given, skipping the access-control queries.")
            print("Start a beacon with AuthConfig and pass one of its keys to see them.")
            return

        print("--- access control ---\n")

        query(client, "An invalid API key is refused with 401", EXACT_SNV,
              headers={"X-API-Key": "not-a-valid-key"})

        print("  spending this key's quota until the beacon refuses the call ...")
        for extra in range(1, 501):
            r = client.get("/g_variants", params=EXACT_SNV)
            if r.status_code == 429:
                print(f"  [429] quota exhausted after {extra} further calls, the key is spent")
                print("        (restart the beacon to issue fresh keys and reset every quota)")
                break
        else:
            print("  quota not reached in 500 calls, this beacon runs without one")


if __name__ == "__main__":
    main()
