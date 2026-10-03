"""Meme↔token matching is exact, deterministic and time-gated.

A false link admits a stranger's market data into a meme's history, which is
worse than a missing link: the missing one shows as an absence, the false one
contaminates every feature silently. So the matcher's refusals matter as much
as its matches.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.domain import AliasKind, LinkMethod, Meme, MemeAlias, TokenInfo
from app.lifecycle_lab.linking import match_token, normalise

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
EARLIER = NOW - timedelta(days=1)
MEME = Meme(id="m1", slug="dogwifhat", display_name="dogwifhat", tracking_started_at=EARLIER)


def alias(text: str, kind: AliasKind, added_at: datetime = EARLIER) -> MemeAlias:
    return MemeAlias("m1", text, kind, added_at)


def token(name: str | None, symbol: str | None) -> TokenInfo:
    return TokenInfo("Mint1", name, symbol, None, None)


def methods(links) -> list[LinkMethod]:
    return [lk.method for lk in links]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  $Dog  Wif HAT ", "dog wif hat"),
        ("#WIF", "wif"),
        ("$$wif", "wif"),
        ("ǅOG", "ǆog"),  # casefold, not lower
        ("a$b", "a$b"),
        ("", ""),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_exact_name_matches_display_name_or_name_alias() -> None:
    links = match_token(
        meme=MEME, aliases=[], token=token("DogWifHat", None), profile=None, now=NOW
    )
    assert methods(links) == [LinkMethod.EXACT_NAME]
    assert links[0].confidence == Decimal("0.6")
    assert links[0].linked_at == NOW

    named = match_token(
        meme=MEME,
        aliases=[alias("Dog Wif Hat", AliasKind.NAME)],
        token=token("dog  wif hat", None),
        profile=None,
        now=NOW,
    )
    assert methods(named) == [LinkMethod.EXACT_NAME]


def test_exact_symbol_and_cross_kind_alias_match() -> None:
    aliases = [alias("$WIF", AliasKind.SYMBOL), alias("#hatdog", AliasKind.HASHTAG)]
    links = match_token(
        meme=MEME, aliases=aliases, token=token("hatdog", "wif"), profile=None, now=NOW
    )
    assert methods(links) == [LinkMethod.EXACT_SYMBOL, LinkMethod.ALIAS_MATCH]
    assert [lk.confidence for lk in links] == [Decimal("0.5"), Decimal("0.4")]


def test_substrings_never_match() -> None:
    """``$DOG`` is a substring of ``$DOGWIFHAT``; matching it would link every
    dog coin to every dog meme."""
    aliases = [alias("DOG", AliasKind.SYMBOL), alias("dog", AliasKind.NAME)]
    links = match_token(
        meme=MEME,
        aliases=aliases,
        token=token("dogwifhat2", "DOGWIFHAT"),
        profile=None,
        now=NOW,
    )
    assert links == []


def test_website_and_social_matches_from_profile() -> None:
    aliases = [
        alias("dogwifcoin.com", AliasKind.DOMAIN),
        alias("@DogWifCoin", AliasKind.SOCIAL_HANDLE),
    ]
    profile = {
        "websites": [{"label": "Website", "url": "https://www.DOGWIFCOIN.com/about"}],
        "socials": [{"type": "twitter", "url": "https://x.com/dogwifcoin"}],
    }
    links = match_token(
        meme=MEME, aliases=aliases, token=token("other", "OTH"), profile=profile, now=NOW
    )
    assert methods(links) == [LinkMethod.SOCIAL_LINK_MATCH, LinkMethod.WEBSITE_MATCH]
    assert all(lk.confidence == Decimal("0.8") for lk in links)


def test_subdomains_and_route_segments_do_not_match() -> None:
    aliases = [alias("dogwifcoin.com", AliasKind.DOMAIN), alias("i", AliasKind.SOCIAL_HANDLE)]
    profile = {
        "websites": ["https://app.dogwifcoin.com.evil.io"],
        "socials": [{"type": "twitter", "url": "https://x.com/i/communities/123"}],
    }
    assert (
        match_token(
            meme=MEME, aliases=aliases, token=token(None, None), profile=profile, now=NOW
        )
        == []
    )


def test_alias_added_after_now_does_not_justify_a_link() -> None:
    """A link cannot be justified by an alias nobody had recorded yet."""
    late = alias("WIF", AliasKind.SYMBOL, added_at=NOW + timedelta(seconds=1))
    assert (
        match_token(meme=MEME, aliases=[late], token=token(None, "WIF"), profile=None, now=NOW)
        == []
    )


def test_other_memes_aliases_are_ignored() -> None:
    foreign = MemeAlias("m2", "WIF", AliasKind.SYMBOL, EARLIER)
    assert (
        match_token(
            meme=MEME, aliases=[foreign], token=token(None, "WIF"), profile=None, now=NOW
        )
        == []
    )


def test_result_is_independent_of_alias_order() -> None:
    aliases = [
        alias("WIF", AliasKind.SYMBOL),
        alias("dogwifhat", AliasKind.PHRASE),
        alias("dogwifcoin.com", AliasKind.DOMAIN),
        alias("@dogwifcoin", AliasKind.SOCIAL_HANDLE),
    ]
    profile = {"websites": ["dogwifcoin.com"], "socials": [{"url": "t.me/dogwifcoin"}]}
    tok = token("dogwifhat", "WIF")
    first = match_token(meme=MEME, aliases=aliases, token=tok, profile=profile, now=NOW)
    assert len(first) == 5
    rng = random.Random(3)
    for _ in range(5):
        rng.shuffle(aliases)
        assert (
            match_token(meme=MEME, aliases=aliases, token=tok, profile=profile, now=NOW)
            == first
        )


def test_malformed_profile_is_ignored_not_fatal() -> None:
    profile = {"websites": "not-a-list", "socials": [42, {"url": None}]}
    assert (
        match_token(meme=MEME, aliases=[], token=token(None, None), profile=profile, now=NOW)
        == []
    )
