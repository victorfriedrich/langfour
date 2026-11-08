"""What each feature spent on AI, from the ai_spend table (see ai_gateway.py).

    python scripts/ai_spend.py              # last 7 days, by source
    python scripts/ai_spend.py --days 1 --by source,model
    python scripts/ai_spend.py --days 30 --by day,source

Reads Supabase with the service-role key from apps/api/.env. Makes no AI
request.
"""

from __future__ import annotations

import argparse
import collections
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

COLUMNS = ("day", "hour", "origin", "source", "provider", "model")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=float, default=7)
    p.add_argument("--by", default="source", help=f"comma-separated, from {', '.join(COLUMNS)}")
    a = p.parse_args()
    keys = [k.strip() for k in a.by.split(",") if k.strip()]
    if not keys or set(keys) - set(COLUMNS):
        p.error(f"--by takes {', '.join(COLUMNS)}")

    from supabase_client import supabase

    since = (datetime.now(UTC) - timedelta(days=a.days)).isoformat()
    rows, start = [], 0
    while True:
        page = (supabase.table("ai_spend").select("*").gte("hour", since)
                .order("hour").range(start, start + 999).execute().data)
        rows += page
        if len(page) < 1000:
            break
        start += 1000

    totals: dict[tuple, list[float]] = collections.defaultdict(lambda: [0, 0.0, 0, 0])
    for r in rows:
        r["day"] = r["hour"][:10]
        t = totals[tuple(r[k] for k in keys)]
        t[0] += r["calls"]
        t[1] += r["cost_usd"]
        t[2] += r["input_tokens"] + r["output_tokens"]
        t[3] += r["errors"]

    grand = sum(t[1] for t in totals.values()) or 1.0
    print(f"{' / '.join(keys):<60} {'calls':>10} {'tokens':>13} {'errors':>7} {'usd':>10} {'share':>6}")
    for key, (calls, usd, tokens, errors) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        print(f"{' / '.join(map(str, key)):<60} {calls:>10,} {tokens:>13,} {errors:>7,} "
              f"{usd:>10.4f} {usd / grand:>6.1%}")
    print(f"{'total':<60} {sum(t[0] for t in totals.values()):>10,} {'':>13} {'':>7} "
          f"{sum(t[1] for t in totals.values()):>10.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
