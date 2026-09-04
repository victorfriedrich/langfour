"""One in-memory stand-in for the video_queue table, shared by every test.

There used to be two hand-written fakes, and the looser one hid a real bug: it
accepted `select(..., head=True)`, which the pinned postgrest (0.16.x, via
supabase==2.7.4) does not have, so `ingest.py status` passed its tests and
raised TypeError against the pinned dependency.

So this fake mirrors the PINNED client, not the newest one. Its method
signatures are deliberately narrow: a call the real builder would reject must
raise here too. The semantics that matter are

  * update() returns the rows it matched -- the compare-and-set claim reads it
  * upsert(ignore_duplicates=True) returns only rows actually inserted
  * a bulk payload's rows must share one key set (PostgREST nulls the rest)
"""

import pytest


class FakeQuery:
    # postgrest 0.16: select(self, *columns, count=None). No `head`.
    def __init__(self, rows):
        self.rows, self.filters, self.orders = rows, [], []
        self.op = self.payload = self.limit_n = None
        self.count_mode = None
        self.ignore_duplicates = False

    def select(self, *_, count=None):
        self.op, self.count_mode = "select", count
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        assert on_conflict == "video_id"
        if isinstance(rows, list):
            assert len({frozenset(r) for r in rows}) == 1, "bulk rows must share one key set"
        self.op, self.payload, self.ignore_duplicates = "upsert", rows, ignore_duplicates
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def lt(self, k, v):
        self.filters.append(lambda r: r.get(k) is not None and r.get(k) < v)
        return self

    def order(self, k, desc=False):
        self.orders.append((k, desc))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def execute(self):
        from types import SimpleNamespace
        match = [r for r in self.rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            total = len(match)
            # Postgres sorts NULLs first under DESC; the claim query relies on
            # knowing that, so the fake must reproduce it rather than tidy it.
            for k, desc in reversed(self.orders):
                match.sort(key=lambda r: (r.get(k) is None, r.get(k) or 0), reverse=desc)
            match = match[:self.limit_n] if self.limit_n else match
            return SimpleNamespace(data=[dict(r) for r in match],
                                   count=total if self.count_mode else None)
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in match], count=None)
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        written = []
        for row in rows:
            existing = next((r for r in self.rows if r["video_id"] == row["video_id"]), None)
            if existing is None:
                self.rows.append({"status": "pending", "attempts": 0, "priority": 0,
                                  "source": "discovery", **row})
                written.append(row)
            elif not self.ignore_duplicates:
                existing.update(row)
                written.append(row)
        return SimpleNamespace(data=written, count=None)


class FakeSupabase:
    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]
        self.calls = []

    def table(self, name):
        self.calls.append(name)
        return FakeQuery(self.rows)

    def row(self, video_id):
        return next(r for r in self.rows if r["video_id"] == video_id)


def queued(video_id, **kw):
    """A pending row, with the columns the queue always has."""
    return {"video_id": video_id, "lang": "es", "status": "pending", "attempts": 0,
            "priority": 0, "score": 0.5, "source": "discovery", **kw}


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Redirect the transcript corpus at a temp dir. processed_file() reads the
    module global at call time, so patching PROCESSED_DIR is enough."""
    import paths
    monkeypatch.setattr(paths, "PROCESSED_DIR", tmp_path)
    (tmp_path / "es").mkdir()
    return tmp_path / "es"
