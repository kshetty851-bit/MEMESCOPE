"""MEMESCOPE's own public repository, counted, for the homepage journey section.

Kept out of `app.labs.graduation`, where only `sources.py` may open a socket
(tests/test_isolation.py). One read per 10 minutes serves every visitor, and
the last good answer is kept when GitHub refuses.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

REPO = "kshetty851-bit/MEMESCOPE"
_CACHE: tuple[datetime, dict[str, int | None]] = (
    datetime.min.replace(tzinfo=UTC), {"commits": None, "merged_prs": None})


async def github_counts(now: datetime) -> dict[str, int | None]:
    """{"commits": commits on main, "merged_prs": merged pull requests}."""
    global _CACHE
    if (now - _CACHE[0]).total_seconds() < 600:
        return _CACHE[1]
    out = dict(_CACHE[1])
    try:
        headers = {"Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=8, headers=headers) as gh:
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
    _CACHE = (now, out)
    return out


#: Every commit on main, by Dubai date: {date: [first lines, oldest first]}.
#: Filled once, then topped up with only what is newer, so a refresh is one
#: request however long the history gets.
_DAYS: dict[str, list[str]] = defaultdict(list)
_DAYS_SEEN: set[str] = set()
_DAYS_AT: datetime = datetime.min.replace(tzinfo=UTC)
_DAYS_SINCE: str | None = None
DUBAI = timedelta(hours=4)
_SKIP = re.compile(r"^(merge|revert|docs|chore|test|style)\b", re.IGNORECASE)


def _headline(message: str) -> str | None:
    """A commit's first line, if it says what was built (not a merge or docs)."""
    line = message.splitlines()[0].strip() if message else ""
    return None if not line or _SKIP.match(line) else line


async def github_days(now: datetime) -> list[dict[str, object]]:
    """[{date, commits, titles}] for every day with a commit, newest first.

    `commits` counts every commit that day; `titles` are the ones that say
    what was built, newest first. Refreshed at most every 30 minutes.
    """
    global _DAYS_AT, _DAYS_SINCE
    if (now - _DAYS_AT).total_seconds() >= 1800:
        try:
            await _top_up()
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("journey_github_days_unreadable")
        _DAYS_AT = now
    return [{"date": day, "commits": len(lines),
             "titles": [t for t in reversed(lines) if t is not None][:6]}
            for day, lines in sorted(_DAYS.items(), reverse=True)]


async def _top_up() -> None:
    global _DAYS_SINCE
    headers = {"Accept": "application/vnd.github+json"}
    params: dict[str, object] = {"sha": "main", "per_page": 100}
    if _DAYS_SINCE:
        params["since"] = _DAYS_SINCE
    fresh: list[dict] = []
    async with httpx.AsyncClient(timeout=10, headers=headers) as gh:
        for page in range(1, 30):
            got = await gh.get(f"https://api.github.com/repos/{REPO}/commits",
                               params={**params, "page": page})
            got.raise_for_status()
            batch = got.json()
            fresh.extend(batch)
            if len(batch) < 100:
                break
    for c in reversed(fresh):                       # oldest first
        if c["sha"] in _DAYS_SEEN:
            continue
        _DAYS_SEEN.add(c["sha"])
        at = datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00"))
        _DAYS[(at + DUBAI).date().isoformat()].append(_headline(c["commit"]["message"]))
        _DAYS_SINCE = c["commit"]["author"]["date"]
