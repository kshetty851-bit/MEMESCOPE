"""The homepage's day-by-day log: commits grouped by Dubai date, topped up."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services import github_counts as g


def _commit(sha: str, at: str, message: str) -> dict:
    return {"sha": sha, "commit": {"author": {"date": at}, "message": message}}


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(g, "_DAYS", defaultdict(list))
    monkeypatch.setattr(g, "_DAYS_SEEN", set())
    monkeypatch.setattr(g, "_DAYS_SINCE", None)
    monkeypatch.setattr(g, "_DAYS_AT", datetime.min.replace(tzinfo=UTC))
    pages: list[list[dict]] = []
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=pages.pop(0) if pages else [])

    real = httpx.AsyncClient
    monkeypatch.setattr(g.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return pages, seen_params


async def test_days_group_by_dubai_date_and_keep_what_was_built(fresh):
    pages, params = fresh
    pages.append([   # the API answers newest first
        # 21:00 UTC is 01:00 on the 28th in Dubai.
        _commit("c", "2026-09-27T21:00:00Z", "Homepage: a new section (#155)"),
        _commit("b", "2026-09-27T10:00:00Z", "Merge branch 'x'"),
        _commit("a", "2026-09-27T09:00:00Z", "User wallets: fee (#154)\n\nbody"),
    ])
    now = datetime(2026, 9, 28, tzinfo=UTC)
    days = await g.github_days(now)
    assert days == [
        {"date": "2026-09-28", "commits": 1, "titles": ["Homepage: a new section (#155)"]},
        {"date": "2026-09-27", "commits": 2, "titles": ["User wallets: fee (#154)"]},
    ]
    # Half an hour later, only what is newer is asked for, and nothing is counted twice.
    pages.append([_commit("d", "2026-09-28T01:00:00Z", "Karthik's Lab: grid (#156)"),
                  _commit("c", "2026-09-27T21:00:00Z", "Homepage: a new section (#155)")])
    days = await g.github_days(now + timedelta(minutes=31))
    assert params[-1]["since"] == "2026-09-27T21:00:00Z"
    assert days[0] == {"date": "2026-09-28", "commits": 2, "titles": [
        "Karthik's Lab: grid (#156)", "Homepage: a new section (#155)"]}
