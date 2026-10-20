"""The newsroom TV: a spoken bulletin written from the page's own data.

Karthik, 2026-10-20: "a live TV female news reporter ... narrate the News
posted in our page ... should sound real voice". The words come only from the
bundle on the page (headlines, our pump.fun numbers, the market); the voice is
OpenAI text-to-speech. A bulletin is made when someone presses play and the
last one is older than `MAX_AGE`, at most `DAILY_CAP` a day, so the bill
follows viewers and has a ceiling (~1 minute of speech each, about 1.5 cents).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

META_KEY, AUDIO_KEY, LOCK_KEY = "newsroom:tv:meta", "newsroom:tv:audio:", "newsroom:tv:lock"
DAY_KEY = "newsroom:tv:day:"
MAX_AGE = timedelta(minutes=60)
DAILY_CAP = 24
MODEL, VOICE = "gpt-4o-mini-tts", "coral"
STYLE = ("You are a warm, confident television news anchor reading a short bulletin "
         "live in a studio. Clear, measured pace, natural pauses between stories, "
         "a light smile in the voice. Never rushed.")
DUBAI = timedelta(hours=4)
_TAIL = re.compile(r"\s*[|\-–—]\s*[^|\-–—]{2,40}$")   # "Title - Publisher"


def _money(v: float) -> str:
    return f"{v:,.0f} dollars" if v >= 100 else f"{v:,.2f} dollars"


def _move(v: float | None) -> str:
    if v is None or abs(v) < 0.1:
        return "flat on the day"
    return f"{'up' if v > 0 else 'down'} {abs(v):.1f} percent on the day"


def headlines(stories: list[dict[str, Any]], lead: dict[str, Any] | None,
              now: datetime, n: int = 4) -> list[dict[str, Any]]:
    """The lead, then the most widely reported fresh stories; no opinion pieces."""
    fresh = [s for s in stories if s.get("kind") != "commentary"
             and now - datetime.fromisoformat(s["last_at"]) < timedelta(hours=12)]
    fresh.sort(key=lambda s: (s.get("sources") or 1, s["last_at"]), reverse=True)
    out = [lead] if lead else []
    for s in fresh:
        if len(out) >= n:
            break
        if all(s["id"] != o["id"] for o in out):
            out.append(s)
    return out


def script(bundle: dict[str, Any], now: datetime | None = None) -> list[dict[str, str]]:
    """The bulletin as (label, text) segments, in reading order."""
    now = now or datetime.now(UTC)
    local = now + DUBAI
    part = "morning" if local.hour < 12 else "afternoon" if local.hour < 17 else "evening"
    segs = [{"label": "MemeScope News",
             "text": f"Good {part}, and welcome to MemeScope News. "
                     f"It's {local:%-I:%M %p} in Dubai. Here's what's moving."}]
    o = bundle.get("ours") or {}
    if o.get("graduations_24h"):
        t = f"On pump dot fun, {o['graduations_24h']:,} coins graduated in the last day."
        if o.get("rug_rate_24h") is not None:
            t += f" {o['rug_rate_24h']:.0f} percent of them lost most of their value within the hour."
        best = (o.get("survivors") or [None])[0]
        if best and best.get("change_1h_pct"):
            t += (f" The standout survivor: {best.get('name') or best.get('symbol')}, "
                  f"up {best['change_1h_pct']:.0f} percent.")
        segs.append({"label": "Today on pump.fun", "text": t})
    for i, s in enumerate(headlines(bundle.get("stories") or [], bundle.get("lead"), now)):
        title = _TAIL.sub("", s["title"]).strip().rstrip(".")
        pubs = s.get("publishers") or [s.get("source")]
        by = f"reports {pubs[0]}" if len(pubs) == 1 else f"reported by {len(pubs)} outlets"
        lead_in = "Our top story: " if i == 0 else ("Also today: " if i == 1 else "")
        segs.append({"label": title, "text": f"{lead_in}{title}, {by}."})
    m = bundle.get("market") or {}
    coins = {c["symbol"]: c for c in m.get("coins") or []}
    bits = [f"{name} at {_money(coins[sym]['price'])}, {_move(coins[sym].get('ch24h'))}"
            for sym, name in (("BTC", "Bitcoin"), ("ETH", "Ether")) if sym in coins]
    fg = bundle.get("fear_greed")
    if bits or fg:
        t = "In the markets, " + " and ".join(bits) + "." if bits else ""
        if fg:
            t += f" The fear and greed index reads {fg['value']}, {fg['label'].lower()}."
        segs.append({"label": "Markets", "text": t.strip()})
    segs.append({"label": "MemeScope News",
                 "text": "That's the news for now. I'm an AI presenter, and nothing here "
                         "is financial advice. Stay sharp, and we'll see you next hour."})
    return segs


async def _speak(api_key: str, text: str) -> bytes:
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": MODEL, "voice": VOICE, "input": text,
                  "instructions": STYLE, "response_format": "mp3"})
        r.raise_for_status()
        return r.content


async def bulletin(redis, bundle: dict[str, Any], api_key: str,
                   now: datetime | None = None) -> dict[str, Any] | None:
    """The newest bulletin, making a new one first if the last is stale.

    Returns None when there is none yet and none can be made (no key, the
    daily cap, or another request already making it)."""
    now = now or datetime.now(UTC)
    meta = json.loads(await redis.get(META_KEY) or "null")
    fresh = meta and now - datetime.fromisoformat(meta["made_at"]) < MAX_AGE
    if fresh or not api_key or not bundle.get("stories"):
        return meta
    day = DAY_KEY + f"{now:%Y%m%d}"
    if int(await redis.get(day) or 0) >= DAILY_CAP:
        return meta
    if not await redis.set(LOCK_KEY, "1", nx=True, ex=120):
        return meta                     # someone else is making it right now
    try:
        segs = script(bundle, now)
        text = " ".join(s["text"] for s in segs)
        audio = await _speak(api_key, text)
        bid = hashlib.sha256(audio).hexdigest()[:16]
        await redis.set(AUDIO_KEY + bid, base64.b64encode(audio).decode(), ex=6 * 3600)
        await redis.incr(day)
        await redis.expire(day, 2 * 86400)
        meta = {"id": bid, "made_at": now.isoformat(), "segments": segs,
                "chars": len(text), "voice": VOICE}
        await redis.set(META_KEY, json.dumps(meta))
        logger.info("newsroom_tv_bulletin", id=bid, chars=len(text), bytes=len(audio))
        return meta
    except httpx.HTTPError as exc:
        logger.warning("newsroom_tv_failed", error=type(exc).__name__)
        return meta
    finally:
        await redis.delete(LOCK_KEY)


async def audio(redis, bid: str) -> bytes | None:
    raw = await redis.get(AUDIO_KEY + bid) if re.fullmatch(r"[0-9a-f]{16}", bid) else None
    return base64.b64decode(raw) if raw else None
