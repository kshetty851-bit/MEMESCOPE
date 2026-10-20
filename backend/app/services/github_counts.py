"""MEMESCOPE's own public repository, counted, for the homepage journey section.

Kept out of `app.labs.graduation`, where only `sources.py` may open a socket
(tests/test_isolation.py). One read per 10 minutes serves every visitor, and
the last good answer is kept when GitHub refuses.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

REPO = "kshetty851-bit/MEMESCOPE"
#: Kept in Redis, not process memory (2026-10-20): every web worker and every
#: redeploy used to refetch the whole history unauthenticated, ran GitHub's
#: 60-an-hour allowance dry part-way, threw the partial read away and started
#: again, so the day log froze on 27 Sep. Now one shared copy grows a few pages
#: at a time, keeps what it read, and only one worker refreshes at once.
COUNTS_KEY, COMMITS_KEY = "journey:gh:counts", "journey:gh:commits"
STATE_KEY, LOCK_KEY = "journey:gh:state", "journey:gh:lock"
COUNTS_EVERY, DAYS_EVERY = timedelta(minutes=10), timedelta(minutes=30)
PAGES_PER_REFRESH = 8
DUBAI = timedelta(hours=4)
_SKIP = re.compile(r"^(merge|revert|docs|chore|test|style)\b", re.IGNORECASE)
_HEADERS = {"Accept": "application/vnd.github+json"}


async def _redis():
    from app.core.redis import init_redis

    return await init_redis()


async def github_counts(now: datetime) -> dict[str, int | None]:
    """{"commits": commits on main, "merged_prs": merged pull requests}."""
    r = await _redis()
    cached = json.loads(await r.get(COUNTS_KEY) or "null")
    if cached and now - datetime.fromisoformat(cached["at"]) < COUNTS_EVERY:
        return cached["out"]
    out = dict(cached["out"]) if cached else {"commits": None, "merged_prs": None}
    if not await r.set(LOCK_KEY + ":counts", "1", nx=True, ex=60):
        return out
    try:
        async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as gh:
            commits = await gh.get(f"https://api.github.com/repos/{REPO}/commits",
                                   params={"sha": "main", "per_page": 1})
            last = re.search(r'[?&]page=(\d+)>; rel="last"', commits.headers.get("link", ""))
            if commits.status_code == 200 and last:
                out["commits"] = int(last.group(1))
            prs = await gh.get("https://api.github.com/search/issues",
                               params={"q": f"repo:{REPO} is:pr is:merged", "per_page": 1})
            if prs.status_code == 200:
                out["merged_prs"] = int(prs.json()["total_count"])
    except (httpx.HTTPError, ValueError, KeyError):
        logger.warning("journey_github_unreadable")
    await r.set(COUNTS_KEY, json.dumps({"at": now.isoformat(), "out": out}))
    return out


def _headline(message: str) -> str | None:
    """A commit's first line, if it says what was built (not a merge or docs)."""
    line = message.splitlines()[0].strip() if message else ""
    return None if not line or _SKIP.match(line) else line


async def github_days(now: datetime) -> list[dict[str, object]]:
    """[{date, commits, titles}] for every day with a commit, newest first.

    `commits` counts every commit that day; `titles` are the ones that say
    what was built, newest first. Refreshed at most every 30 minutes.
    """
    r = await _redis()
    state = json.loads(await r.get(STATE_KEY) or "null") or {"at": None, "backfill": 1}
    due = state["at"] is None or now - datetime.fromisoformat(state["at"]) >= DAYS_EVERY
    if due and await r.set(LOCK_KEY, "1", nx=True, ex=120):
        try:
            state = await _top_up(r, state)
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("journey_github_days_unreadable")
        state["at"] = now.isoformat()
        await r.set(STATE_KEY, json.dumps(state))
        await r.delete(LOCK_KEY)
    days: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for raw in (await r.hgetall(COMMITS_KEY)).values():
        at, title = json.loads(raw)
        days[(datetime.fromisoformat(at) + DUBAI).date().isoformat()].append((at, title))
    return [{"date": day, "commits": len(rows),
             "titles": [t for _, t in sorted(rows, reverse=True) if t is not None][:6]}
            for day, rows in sorted(days.items(), reverse=True)]


async def _top_up(r, state: dict) -> dict:
    """New commits from page 1 until a known one; then a few older pages until
    the start of history (`backfill` None once complete). Each page is saved as
    it is read, so a refusal part-way keeps everything before it."""
    budget = PAGES_PER_REFRESH
    async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as gh:
        async def page(n: int) -> list[dict]:
            got = await gh.get(f"https://api.github.com/repos/{REPO}/commits",
                               params={"sha": "main", "per_page": 100, "page": n})
            got.raise_for_status()
            batch = got.json()
            if batch:
                await r.hset(COMMITS_KEY, mapping={
                    c["sha"]: json.dumps([c["commit"]["author"]["date"].replace("Z", "+00:00"),
                                          _headline(c["commit"]["message"])]) for c in batch})
            return batch

        known = await r.hlen(COMMITS_KEY)
        n = 1
        while known and budget > 0:                 # the newest, until we reach what we have
            before = await r.hlen(COMMITS_KEY)
            batch = await page(n)
            budget -= 1
            if len(batch) < 100 or await r.hlen(COMMITS_KEY) - before < len(batch):
                break                               # this page held commits already saved
            n += 1
        while state.get("backfill") and budget > 0:  # older history, a few pages a time
            batch = await page(state["backfill"])
            budget -= 1
            state["backfill"] = None if len(batch) < 100 else state["backfill"] + 1
    return state
