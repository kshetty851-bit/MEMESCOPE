"""DexScreener token profiles and deterministic candidate discovery.

Not an attention source. It supplies *identity* facts that the linker uses
(websites, social links, pool creation time) as one SNAPSHOT observation per
linked mint, and a name/symbol search for meme-to-token candidates.

Endpoints (no key; up to 30 comma-separated mints per call):
  * ``GET /latest/dex/tokens/{mints}``
  * ``GET /latest/dex/search?q={text}``

Profile selection, deterministic: among Solana pairs whose base token is the
mint, ``pair_address`` / ``dex_id`` come from the pair with the greatest USD
liquidity (ties: lowest pair address); ``pair_created_at`` is the OLDEST pair's
creation time (the token's first pool); websites/socials come from the first
pair, in that liquidity order, that carries ``info``. A mint DexScreener does
not return is ``UNAVAILABLE not_listed`` - not an empty profile.

Observations are stamped ``now`` for source/observed/retrieved: DexScreener has
no history, so the profile is only ever known as of the moment we asked.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.lifecycle_lab.adapters.base import (
    AdapterError,
    AdapterResult,
    ClockFn,
    MinIntervalLimiter,
    SleepFn,
    Subject,
    aggregate_status,
    disabled_result,
    http_get,
    parse_json,
    raise_for_status,
    request_url,
)
from app.lifecycle_lab.domain import (
    DataClass,
    Metric,
    Observation,
    Source,
    SourceStatus,
    TokenInfo,
    ValueKind,
)

BASE = "https://api.dexscreener.com/latest/dex"
BATCH = 30
CHAIN = "solana"
#: DexScreener allows far more; this keeps a research job a polite guest.
MIN_INTERVAL_SECONDS = 0.5


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _created(pair: dict[str, Any]) -> datetime | None:
    raw = pair.get("pairCreatedAt")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _liquidity(pair: dict[str, Any]) -> Decimal:
    liq = pair.get("liquidity")
    return (_dec(liq.get("usd")) if isinstance(liq, dict) else None) or Decimal(0)


def _pairs(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise AdapterError("unparseable")
    pairs = body.get("pairs")
    if pairs is None:
        return []
    if not isinstance(pairs, list):
        raise AdapterError("unparseable")
    return [p for p in pairs if isinstance(p, dict) and p.get("chainId") == CHAIN]


def _base_address(pair: dict[str, Any]) -> str | None:
    base = pair.get("baseToken")
    addr = base.get("address") if isinstance(base, dict) else None
    return addr if isinstance(addr, str) and addr else None


def build_profile(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Profile facts from every Solana pair of one mint. Deterministic."""
    ranked = sorted(pairs, key=lambda p: (-_liquidity(p), str(p.get("pairAddress") or "")))
    top = ranked[0]
    created = [c for c in (_created(p) for p in pairs) if c is not None]
    websites: list[str] = []
    socials: list[dict[str, str]] = []
    for pair in ranked:
        info = pair.get("info")
        if not isinstance(info, dict):
            continue
        for site in info.get("websites") or []:
            url = site.get("url") if isinstance(site, dict) else site
            if isinstance(url, str) and url:
                websites.append(url)
        for soc in info.get("socials") or []:
            if isinstance(soc, dict) and isinstance(soc.get("url"), str):
                socials.append({"type": str(soc.get("type") or ""), "url": soc["url"]})
        break
    return {
        "websites": websites,
        "socials": socials,
        "pair_created_at": min(created).isoformat() if created else None,
        "pair_address": top.get("pairAddress"),
        "dex_id": top.get("dexId"),
        "liquidity_usd": str(_liquidity(top)) if _liquidity(top) else None,
    }


class DexScreenerAdapter:
    source: Source = Source.DEXSCREENER
    data_class: DataClass = DataClass.FORWARD

    def __init__(
        self,
        settings: Any,
        client: httpx.AsyncClient,
        *,
        sleep: SleepFn | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = MinIntervalLimiter(MIN_INTERVAL_SECONDS, sleep=sleep, clock=clock)

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not self._settings.MLL_DEXSCREENER_ENABLED:
            return False, "disabled_by_config"
        return True, None

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        mints = list(dict.fromkeys(m for s in subjects for m in s.mints))
        per: dict[str, tuple[SourceStatus, str | None]] = {}
        observations: list[Observation] = []
        profiles: dict[str, dict[str, Any]] = {}
        blocked: str | None = None
        for i in range(0, len(mints), BATCH):
            chunk = mints[i : i + BATCH]
            if blocked is not None:
                per.update(dict.fromkeys(chunk, (SourceStatus.ERROR, blocked)))
                continue
            try:
                await self._limiter.wait()
                response = await http_get(self._client, f"{BASE}/tokens/{','.join(chunk)}")
                raise_for_status(response)
                pairs = _pairs(parse_json(response))
            except AdapterError as exc:
                per.update(dict.fromkeys(chunk, (SourceStatus.ERROR, exc.reason)))
                if exc.reason == "rate_limited":
                    blocked = exc.reason
                continue
            url = request_url(response)
            by_mint: dict[str, list[dict[str, Any]]] = {}
            for pair in pairs:
                addr = _base_address(pair)
                if addr is not None:
                    by_mint.setdefault(addr, []).append(pair)
            for mint in chunk:
                mint_pairs = by_mint.get(mint)
                if not mint_pairs:
                    per[mint] = (SourceStatus.UNAVAILABLE, "not_listed")
                    continue
                profile = build_profile(mint_pairs)
                profiles[mint] = profile
                per[mint] = (SourceStatus.AVAILABLE, None)
                observations.append(
                    Observation(
                        source=Source.DEXSCREENER,
                        metric=Metric.PROFILE,
                        value_kind=ValueKind.SNAPSHOT,
                        data_class=DataClass.FORWARD,
                        source_timestamp=now,
                        observed_at=now,
                        retrieved_at=now,
                        raw_value=Decimal(1),
                        mint_address=mint,
                        query=mint,
                        source_url=url,
                        confidence=Decimal("1"),
                        raw_payload={
                            k: profile[k]
                            for k in (
                                "websites",
                                "socials",
                                "pair_created_at",
                                "pair_address",
                                "dex_id",
                            )
                        },
                    )
                )
        status, reason = aggregate_status(per)
        return AdapterResult(
            self.source, status, reason, tuple(observations), per, (), profiles
        )

    async def search_candidates(
        self, alias: str, *, now: datetime
    ) -> list[tuple[TokenInfo, dict[str, Any]]]:
        """Solana tokens whose pairs match ``alias``, sorted by mint.

        Raises ``AdapterError`` on failure so the caller records a run rather
        than concluding "no candidates".
        """
        ok, why = self.enabled()
        if not ok:
            raise AdapterError(why or "disabled_by_config")
        await self._limiter.wait()
        response = await http_get(self._client, f"{BASE}/search", params={"q": alias})
        raise_for_status(response)
        by_mint: dict[str, list[dict[str, Any]]] = {}
        for pair in _pairs(parse_json(response)):
            addr = _base_address(pair)
            if addr is not None:
                by_mint.setdefault(addr, []).append(pair)
        out: list[tuple[TokenInfo, dict[str, Any]]] = []
        for mint in sorted(by_mint):
            pairs = by_mint[mint]
            profile = build_profile(pairs)
            base = pairs[0].get("baseToken") or {}
            created = [c for c in (_created(p) for p in pairs) if c is not None]
            info = TokenInfo(
                mint_address=mint,
                name=base.get("name") if isinstance(base.get("name"), str) else None,
                symbol=base.get("symbol") if isinstance(base.get("symbol"), str) else None,
                created_at=min(created) if created else None,
                discovered_at=now,
            )
            out.append((info, profile))
        return out
