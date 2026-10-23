"""The homepage's day-by-day log: commits grouped by Dubai date, kept in Redis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services import github_counts as g


def _commit(sha: str, at: str, message: str) -> dict:
    return {"sha": sha, "commit": {"author": {"date": at}, "message": message}}


class Redis:
    def __init__(self):
        self.kv: dict = {}
        self.h: dict = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def delete(self, k):
        self.kv.pop(k, None)

    async def hset(self, k, mapping):
        self.h.setdefault(k, {}).update(mapping)

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))

    async def hlen(self, k):
        return len(self.h.get(k, {}))


@pytest.fixture
def fresh(monkeypatch):
    r = Redis()

    async def redis():
        return r

    monkeypatch.setattr(g, "_redis", redis)
    pages: dict[int, list[dict] | int] = {}
    asked: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["page"])
        asked.append(n)
        got = pages.get(n, [])
        return httpx.Response(got, json={}) if isinstance(got, int) else httpx.Response(200, json=got)

    real = httpx.AsyncClient
    monkeypatch.setattr(g.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return pages, asked, r


async def test_days_group_by_dubai_date_and_keep_what_was_built(fresh):
    pages, asked, _ = fresh
    pages[1] = [   # the API answers newest first
        # 21:00 UTC is 01:00 on the 28th in Dubai.
        _commit("c", "2026-09-27T21:00:00Z", "Homepage: a new section (#155)"),
        _commit("b", "2026-09-27T10:00:00Z", "Merge branch 'x'"),
        _commit("a", "2026-09-27T09:00:00Z", "User wallets: fee (#154)\n\nbody"),
    ]
    now = datetime(2026, 9, 28, tzinfo=UTC)
    days = await g.github_days(now)
    assert days == [
        {"date": "2026-09-28", "commits": 1, "titles": ["Homepage: a new section (#155)"]},
        {"date": "2026-09-27", "commits": 2, "titles": ["User wallets: fee (#154)"]},
    ]
    # Half an hour later only page 1 is read again, and nothing is counted twice.
    pages[1] = [_commit("d", "2026-09-28T01:00:00Z", "Karthik's Lab: grid (#156)"), *pages[1]]
    asked.clear()
    days = await g.github_days(now + timedelta(minutes=31))
    assert asked == [1]
    assert days[0] == {"date": "2026-09-28", "commits": 2, "titles": [
        "Karthik's Lab: grid (#156)", "Homepage: a new section (#155)"]}


async def test_a_refusal_part_way_keeps_what_was_read(fresh):
    pages, asked, r = fresh
    full = [_commit(f"s{i}", f"2026-09-{1 + i // 100:02d}T10:00:00Z", f"Work {i}") for i in range(250)]
    pages[1], pages[2], pages[3] = full[:100], 403, full[200:]
    now = datetime(2026, 10, 1, tzinfo=UTC)
    await g.github_days(now)
    assert len(r.h[g.COMMITS_KEY]) == 100                 # page 1 kept despite the 403 on page 2
    pages[2] = full[100:200]
    days = await g.github_days(now + timedelta(minutes=31))
    assert sum(d["commits"] for d in days) == 250        # the backfill picked up where it stopped
    assert g.json.loads(r.kv[g.STATE_KEY])["backfill"] is None


async def test_two_commits_at_one_instant_one_untitled_do_not_crash(fresh):
    # 22 Oct: a titled and an untitled commit at the same second broke the sort
    # (str vs None) and took the homepage's journey figures down with it.
    _, _, r = fresh
    at = "2026-10-22T10:00:00+00:00"
    r.kv[g.STATE_KEY] = g.json.dumps({"at": datetime.now(UTC).isoformat(), "backfill": None})
    r.h[g.COMMITS_KEY] = {"a": g.json.dumps([at, "Fix the board"]), "b": g.json.dumps([at, None])}
    days = await g.github_days(datetime.now(UTC))
    assert days[0]["commits"] == 2 and days[0]["titles"] == ["Fix the board"]
