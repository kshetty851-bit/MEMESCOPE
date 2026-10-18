"""Build the newspaper bundle: every source in parallel, last good value kept.

A source that fails keeps its previous data, marked with when it last answered,
so the page can say "stale since 14:02" instead of going blank or pretending.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger
from app.newsroom import briefing, news, sources

logger = get_logger(__name__)
KEY, ITEMS_KEY = "newsroom:v1", "newsroom:items"
KEEP = timedelta(hours=72)
SECTIONS = ("market", "narratives", "fear_greed", "hacks", "bitcoin_network", "memes")


def _item_json(i: news.Item) -> dict[str, Any]:
    return {
        "id": i.id,
        "source": i.source,
        "url": i.url,
        "title": i.title,
        "summary": i.summary,
        "published_at": i.published_at.isoformat(),
        "image": i.image,
        "topics": i.topics,
        "regions": i.regions,
        "kind": i.kind,
    }


def _item_obj(d: dict[str, Any]) -> news.Item:
    return news.Item(**{**d, "published_at": datetime.fromisoformat(d["published_at"])})


async def _feed(client: httpx.AsyncClient, name: str, url: str) -> list[news.Item]:
    r = await client.get(url, headers=sources.UA, timeout=20, follow_redirects=True)
    r.raise_for_status()
    return news.parse(name, r.content)


def stories_from(items: list[news.Item], now: datetime) -> list[dict[str, Any]]:
    out = []
    for group in news.cluster(items):
        latest = group[-1]
        pubs = sorted({i.source for i in group})
        kinds = {i.kind for i in group}
        out.append(
            {
                "id": latest.id,
                "title": latest.title,
                "summary": latest.summary,
                "url": latest.url,
                "source": latest.source,
                "image": next((i.image for i in reversed(group) if i.image), None),
                "first_at": group[0].published_at.isoformat(),
                "last_at": latest.published_at.isoformat(),
                "sources": len(pubs),
                "publishers": pubs,
                "topics": sorted({t for i in group for t in i.topics}),
                "regions": sorted({r for i in group for r in i.regions}),
                # Legacy "confirmed" means multi-outlet coverage, not verification.
                # Developing coverage stays developing regardless of outlet count.
                "kind": (
                    "commentary"
                    if kinds == {"commentary"}
                    else "developing"
                    if "developing" in kinds
                    else "confirmed"
                    if len(pubs) >= 2
                    else "report"
                ),
                "timeline": [
                    {
                        "source": i.source,
                        "title": i.title,
                        "url": i.url,
                        "at": i.published_at.isoformat(),
                    }
                    for i in group
                ],
            }
        )
    return out


def lead(stories: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    recent = [
        s
        for s in stories
        if now - datetime.fromisoformat(s["last_at"]) < timedelta(hours=12)
        and s["kind"] != "commentary"
    ]
    return max(recent or stories[:1], key=lambda s: (s["sources"], s["last_at"]), default=None)


def map_points(stories: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for s in stories:
        if now - datetime.fromisoformat(s["last_at"]) > timedelta(hours=48):
            continue
        for code in s["regions"]:
            meta = next((r for r in news.REGIONS if r[0] == code), None)
            if not meta:
                continue
            p = by.setdefault(
                code,
                {
                    "code": code,
                    "name": meta[1],
                    "lat": meta[2],
                    "lon": meta[3],
                    "count": 0,
                    "stories": [],
                },
            )
            p["count"] += 1
            if len(p["stories"]) < 4:
                p["stories"].append(
                    {
                        "id": s["id"],
                        "title": s["title"],
                        "url": s["url"],
                        "source": s["source"],
                        "at": s["last_at"],
                    }
                )
    return sorted(by.values(), key=lambda p: p["count"], reverse=True)


async def build(session_factory, redis) -> dict[str, Any]:
    now = datetime.now(UTC)
    prev = json.loads(await redis.get(KEY) or "{}")
    status: dict[str, Any] = prev.get("status", {})
    bundle: dict[str, Any] = {k: prev.get(k) for k in SECTIONS}

    async with httpx.AsyncClient() as client:
        feeds = await asyncio.gather(
            *(_feed(client, n, u) for n, u in news.FEEDS), return_exceptions=True
        )
        readers = {
            "market": sources.market,
            "narratives": sources.narratives,
            "fear_greed": sources.fear_greed,
            "hacks": sources.hacks,
            "bitcoin_network": sources.bitcoin_network,
            "memes": sources.boosted_memes,
        }
        got = await asyncio.gather(
            *(f(client) for f in readers.values()), return_exceptions=True
        )

    for (name, _url), res in zip(news.FEEDS, feeds, strict=True):
        s = status.setdefault(name, {"kind": "news"})
        if isinstance(res, Exception):
            s.update(ok=False, error=type(res).__name__)
        else:
            s.update(ok=True, error=None, last_ok=now.isoformat(), items=len(res))
    for name, res in zip(readers, got, strict=True):
        s = status.setdefault(name, {"kind": "data"})
        if isinstance(res, Exception):
            s.update(ok=False, error=type(res).__name__)
            logger.info("newsroom_source_failed", source=name, error=type(res).__name__)
        else:
            bundle[name] = res
            s.update(ok=True, error=None, last_ok=now.isoformat())

    old = {d["id"]: d for d in json.loads(await redis.get(ITEMS_KEY) or "[]")}
    for res in feeds:
        if not isinstance(res, Exception):
            for i in res:
                old[i.id] = _item_json(i)
    kept = [
        d
        for d in old.values()
        if now - datetime.fromisoformat(d["published_at"]) < KEEP
        and datetime.fromisoformat(d["published_at"]) <= now + timedelta(minutes=5)
    ]
    kept.sort(key=lambda d: d["published_at"], reverse=True)
    kept = kept[:900]
    await redis.set(ITEMS_KEY, json.dumps(kept))

    stories = stories_from([_item_obj(d) for d in kept], now)
    async with session_factory() as session:
        try:
            from app.newsroom import ours

            bundle["ours"] = await ours.pulse(session, now)
            status["memescope"] = {"kind": "data", "ok": True, "last_ok": now.isoformat()}
        except Exception as exc:  # our own data is optional on the page
            bundle["ours"] = prev.get("ours")
            status["memescope"] = {
                **status.get("memescope", {}),
                "ok": False,
                "error": type(exc).__name__,
            }

    bundle.update(
        {
            "generated_at": now.isoformat(),
            "status": status,
            "stories": stories[:160],
            "lead": lead(stories, now),
            "map": map_points(stories, now),
            "unavailable": [
                {
                    "section": "Token unlocks, network upgrades, governance votes, conferences",
                    "why": "No free, reliable calendar source is connected yet.",
                },
                {"section": "Liquidations", "why": "Needs a paid derivatives data feed."},
                {
                    "section": "Exchange flows and whale transfers",
                    "why": "Needs a paid on-chain alert feed.",
                },
            ],
        }
    )
    bundle["briefing"] = briefing.write(bundle)
    await redis.set(KEY, json.dumps(bundle, default=str))
    return {
        "stories": len(stories),
        "failed": [k for k, v in status.items() if not v.get("ok")],
    }
