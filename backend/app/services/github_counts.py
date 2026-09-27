"""MEMESCOPE's own public repository, counted, for the homepage journey section.

Kept out of `app.labs.graduation`, where only `sources.py` may open a socket
(tests/test_isolation.py). One read per 10 minutes serves every visitor, and
the last good answer is kept when GitHub refuses.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

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
