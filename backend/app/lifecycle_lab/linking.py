"""Deterministic meme↔token matching.

A link is a claim that a token *is about* a meme. Every rule here is an exact
equality after normalisation — never a substring, prefix or fuzzy match.
``$DOG`` is a substring of ``$DOGWIFHAT``; a substring rule would link every dog
coin to every dog meme, and a link, once made, admits that token's market data
into the meme's history. A false link is worse than a missing one: a missing
link is visible as an absence, a false one quietly contaminates every feature.

Confidence reflects how hard the evidence is to fake. A website or social
handle the token's own profile points at (0.8) beats a name collision (0.6),
which beats a ticker collision (0.5) — tickers are short and reused constantly.

``linked_at`` is the ``now`` passed in, and only aliases known by ``now``
count: a link cannot be justified by an alias added after it.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from app.lifecycle_lab.domain import (
    AliasKind,
    LinkMethod,
    Meme,
    MemeAlias,
    MemeTokenLink,
    TokenInfo,
)

CONFIDENCE: dict[LinkMethod, Decimal] = {
    LinkMethod.WEBSITE_MATCH: Decimal("0.8"),
    LinkMethod.SOCIAL_LINK_MATCH: Decimal("0.8"),
    LinkMethod.EXACT_NAME: Decimal("0.6"),
    LinkMethod.EXACT_SYMBOL: Decimal("0.5"),
    LinkMethod.ALIAS_MATCH: Decimal("0.4"),
}

#: First path segments on social hosts that are routes, not accounts
#: (``x.com/i/communities/...``, ``t.me/s/...``).
_RESERVED_SEGMENTS = frozenset(
    {"i", "intent", "home", "share", "search", "hashtag", "s", "joinchat", "status", "c"}
)


def normalise(text: str) -> str:
    """Casefold, trim, collapse internal whitespace, drop leading ``$``/``#``.

    ``"  $Dog  Wif HAT "`` → ``"dog wif hat"``. Only *leading* sigils go: a
    ticker's ``$`` is decoration, a ``$`` mid-name is part of the name.
    """
    collapsed = " ".join(text.split())
    return " ".join(collapsed.lstrip("$#").split()).casefold()


def _domain(value: str) -> str | None:
    text = value.strip().casefold()
    if not text:
        return None
    if "://" not in text:
        text = f"https://{text}"
    try:
        host = urlsplit(text).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _handle(value: str) -> str | None:
    """An account handle from ``@name``, ``name`` or a profile URL."""
    text = value.strip()
    if not text:
        return None
    if text.startswith("@"):
        return normalise(text[1:]) or None
    if "/" in text:
        if "://" not in text:
            text = f"https://{text}"
        try:
            path = urlsplit(text).path
        except ValueError:
            return None
        segments = [s for s in path.split("/") if s]
        if not segments:
            return None
        first = segments[0].lstrip("@").casefold()
        if first in _RESERVED_SEGMENTS:
            return None
        return first or None
    return normalise(text).lstrip("@") or None


def _profile_urls(profile: Mapping[str, Any] | None, key: str) -> list[str]:
    """URLs under ``profile[key]``: plain strings or ``{"url": ...}`` objects,
    the two shapes DexScreener's ``info`` block has used."""
    if not profile:
        return []
    entries = profile.get(key)
    if not isinstance(entries, list):
        return []
    urls: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            urls.append(entry)
        elif isinstance(entry, Mapping):
            for field in ("url", "handle"):
                candidate = entry.get(field)
                if isinstance(candidate, str):
                    urls.append(candidate)
    return urls


def _aliases_of(aliases: Iterable[MemeAlias], kinds: frozenset[AliasKind]) -> set[str]:
    return {normalise(a.alias) for a in aliases if a.kind in kinds} - {""}


def match_token(
    *,
    meme: Meme,
    aliases: Iterable[MemeAlias],
    token: TokenInfo,
    profile: Mapping[str, Any] | None,
    now: datetime,
) -> list[MemeTokenLink]:
    """Every rule that matches, one link per method, strongest first.

    Sorted by confidence descending then method value, so the caller can take
    ``[0]`` as the primary justification and still keep the rest as evidence.
    """
    known = [a for a in aliases if a.meme_id == meme.id and a.added_at <= now]
    name = normalise(token.name) if token.name else ""
    symbol = normalise(token.symbol) if token.symbol else ""

    methods: set[LinkMethod] = set()

    names = _aliases_of(known, frozenset({AliasKind.NAME})) | (
        {normalise(meme.display_name)} - {""}
    )
    if name and name in names:
        methods.add(LinkMethod.EXACT_NAME)

    symbols = _aliases_of(known, frozenset({AliasKind.SYMBOL}))
    if symbol and symbol in symbols:
        methods.add(LinkMethod.EXACT_SYMBOL)

    # A name equal to an alias of any kind other than NAME, or a symbol equal
    # to an alias of any kind other than SYMBOL ("dogwifhat" listed as a
    # phrase, a symbol that is the meme's hashtag).
    non_name = _aliases_of(known, frozenset(AliasKind) - {AliasKind.NAME})
    non_symbol = _aliases_of(known, frozenset(AliasKind) - {AliasKind.SYMBOL})
    if (name and name in non_name) or (symbol and symbol in non_symbol):
        methods.add(LinkMethod.ALIAS_MATCH)

    domains = {
        d for a in known if a.kind is AliasKind.DOMAIN if (d := _domain(a.alias)) is not None
    }
    sites = {
        d for url in _profile_urls(profile, "websites") if (d := _domain(url)) is not None
    }
    if domains & sites:
        methods.add(LinkMethod.WEBSITE_MATCH)

    handles = {
        h
        for a in known
        if a.kind is AliasKind.SOCIAL_HANDLE
        if (h := _handle(a.alias)) is not None
    }
    socials = {
        h for url in _profile_urls(profile, "socials") if (h := _handle(url)) is not None
    }
    if handles & socials:
        methods.add(LinkMethod.SOCIAL_LINK_MATCH)

    links = [
        MemeTokenLink(
            meme_id=meme.id,
            mint_address=token.mint_address,
            method=method,
            confidence=CONFIDENCE[method],
            linked_at=now,
        )
        for method in methods
    ]
    return sorted(links, key=lambda link: (-link.confidence, link.method.value))
