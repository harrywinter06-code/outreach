"""Seed postcodes table from public sources.

Production: download ONS Postcode Directory + IMD 2019 CSVs from gov.uk,
load via pandas/duckdb, join on LSOA, insert into SQLite in batches.

This script seeds a curated 200-postcode dev sample via postcodes.io for
local testing only. Replace with bulk-CSV ingester before launch.
"""
import sys

import httpx

from yield_system.db import connect
from yield_system.experiments.postcode import ensure_table, normalize_postcode

SAMPLE_POSTCODES = [
    "SW1A 1AA", "EC1A 1BB", "W1A 0AX", "NW1 6XE", "E1 6AN",
    "M1 1AA", "B1 1AA", "L1 1AA", "LS1 1AA", "S1 1AA",
    "G1 1AA", "EH1 1AA", "CF10 1AA", "BT1 1AA", "BS1 1AA",
    "NE1 1AA", "OX1 1AA", "CB1 1AA", "BN1 1AA", "PO1 1AA",
]


def seed_sample() -> int:
    ensure_table()
    inserted = 0
    with httpx.Client(timeout=10.0) as client:
        for raw in SAMPLE_POSTCODES:
            normalized = normalize_postcode(raw)
            if not normalized:
                continue
            r = client.get(f"https://api.postcodes.io/postcodes/{raw}")
            if r.status_code != 200:
                continue
            d = r.json()["result"]
            with connect() as c:
                cur = c.execute(
                    "INSERT OR IGNORE INTO postcodes VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized,
                        float(d["latitude"] or 0),
                        float(d["longitude"] or 0),
                        d.get("codes", {}).get("lsoa", "UNKNOWN"),
                        d.get("codes", {}).get("msoa", "UNKNOWN"),
                        d.get("admin_district", "UNKNOWN"),
                        d.get("region") or d.get("country", "UNKNOWN"),
                        5, 3, 25.0,
                    ),
                )
                inserted += cur.rowcount
    return inserted


if __name__ == "__main__":
    added = seed_sample()
    print(f"seeded {added} postcodes")
    sys.exit(0 if added > 0 else 1)
