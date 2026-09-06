#!/usr/bin/env python3
"""Dump whole Supabase tables to CSV. Read-only.

    python3 scripts/backup_tables.py words wordforms

Writes ./csv/<table>.csv relative to the working directory, one file per
table, paging through in 10k-row batches.
"""
import csv
import os
import sys
import time

from dotenv import load_dotenv
from postgrest.exceptions import APIError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()
from supabase_client import supabase, SUPABASE_URL as url, SUPABASE_KEY as key  # noqa: E402

if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in your .env file.")
    sys.exit(1)

PAGE_SIZE = 10000

def export_table_to_csv(table_name: str):
    print(f"Exporting table '{table_name}'...")
    offset = 0
    all_rows = []

    while True:
        try:
            # This will raise APIError if the HTTP status is not 2XX
            response = (
                supabase
                .from_(table_name)
                .select("*")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
        except APIError as e:
            # e.args[0] is the error payload returned by PostgREST
            print(f"  ERROR exporting {table_name}: {e.args[0].get('message')}")
            return

        rows = response.data or []  # .data is always the parsed JSON on success :contentReference[oaicite:0]{index=0}
        if not rows:
            break  # no more data

        all_rows.extend(rows)
        offset += PAGE_SIZE

        if len(rows) < PAGE_SIZE:
            break  # finished paging

        time.sleep(0.2)

    if not all_rows:
        print(f"  WARNING: No data found in table '{table_name}'.")
        return

    csv_path = os.path.join("csv", f"{table_name}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"  SAVED {len(all_rows)} rows to {csv_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/backup_tables.py <table1> [<table2> ...]")
        sys.exit(1)
    os.makedirs("csv", exist_ok=True)
    for tbl in sys.argv[1:]:
        export_table_to_csv(tbl)
