"""World crypto news from publishers' own RSS feeds: parsed, tagged, grouped.

Free feeds only (PRODUCT.md). Every item keeps its publisher, link and time;
summaries are cut to a teaser and always link out. Grouping puts the same story
from several publishers into one timeline instead of repeating headlines.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

FEEDS: tuple[tuple[str, str], ...] = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/feed"),
    ("The Defiant", "https://thedefiant.io/api/feed"),
    ("CryptoPotato", "https://cryptopotato.com/feed/"),
    ("Bitcoin.com News", "https://news.bitcoin.com/feed/"),
)

TOPICS: dict[str, str] = {
    "bitcoin": r"\bbitcoin\b|\bBTC\b|\bsatoshi|\bminers?\b|\bhalving\b|\bordinals?\b",
    "ethereum": r"\bethereum\b|\bETH\b|\bvitalik\b|\blayer[- ]?2\b|\brollups?\b|\bbase chain\b",
    "defi": r"\bdefi\b|\bdex\b|\blending\b|\byield\b|\bliquidity\b|\baave\b|\buniswap\b|\bstak(?:e|ing)\b",
    "exchanges": r"\bexchange\b|\bbinance\b|\bcoinbase\b|\bkraken\b|\bokx\b|\bbybit\b|\bupbit\b|\bbitget\b",
    "regulation": r"\bSEC\b|\bCFTC\b|\bregulat|\blaw\b|\bbill\b|\bsenate\b|\bcongress\b|\bcourt\b|\blawsuit\b|\bMiCA\b|\blicen[cs]e\b|\bban\b|\btax\b",
    "adoption": r"\badopt|\bETFs?\b|\btreasur(?:y|ies)\b|\binstitution|\bbank\b|\bpayments?\b|\breserve\b",
    "nfts": r"\bNFTs?\b|\bcollectibles?\b|\bopensea\b",
    "gaming": r"\bgaming\b|\bgame\b|\bmetaverse\b|\bplay[- ]to[- ]earn\b",
    "security": r"\bhack|\bexploit|\bdrain|\bstolen\b|\bphish|\bscam|\bbreach|\bvulnerab|\boutage\b|\bfraud",
    "memecoins": r"\bmeme ?coins?\b|\bpump\.fun\b|\bdoge\b|\bshib|\bpepe\b|\bbonk\b|\bmemes?\b",
    "stablecoins": r"\bstablecoins?\b|\bUSDT\b|\bUSDC\b|\btether\b|\bcircle\b",
    "solana": r"\bsolana\b|\bSOL\b",
    "macro": r"\bFed\b|\binflation\b|\brates?\b|\bCPI\b|\btariffs?\b|\brecession\b|\bdollar\b|\bstocks?\b",
}
_TOPIC_RE = {k: re.compile(v, re.I) for k, v in TOPICS.items()}
# Tickers that are also ordinary words or fragments stay case-sensitive.
_TOPIC_RE["solana"] = re.compile(r"(?i:\bsolana\b)|\bSOL\b")
# Regulation mixes acronyms (case-sensitive) and words; match both forms.
_TOPIC_RE["regulation"] = re.compile(
    TOPICS["regulation"].replace(r"\bSEC\b|\bCFTC\b|", ""), re.I
)
_REG_ACRONYM = re.compile(r"\bSEC\b|\bCFTC\b|\bMiCA\b")

#: (code, name, lat, lon, pattern). Patterns favour regulators, cities and leaders.
REGIONS: tuple[tuple[str, str, float, float, str], ...] = (
    (
        "US",
        "United States",
        38.9,
        -77.0,
        r"\bU\.?S\.?\b|\bUnited States\b|\bAmerica\b|\bSEC\b|\bCFTC\b|\bWashington\b|\bTrump\b|\bCongress\b|\bSenate\b|\bNew York\b|\bTexas\b|\bFed\b",
    ),
    (
        "GB",
        "United Kingdom",
        51.5,
        -0.1,
        r"\bU\.?K\.?\b|\bBritain\b|\bBritish\b|\bLondon\b|\bFCA\b|\bEngland\b",
    ),
    (
        "EU",
        "European Union",
        50.8,
        4.4,
        r"\bEU\b|\bEurope(?:an)?\b|\bMiCA\b|\bECB\b|\bBrussels\b",
    ),
    ("DE", "Germany", 52.5, 13.4, r"\bGerman(?:y)?\b|\bBaFin\b|\bBerlin\b"),
    ("FR", "France", 48.9, 2.3, r"\bFrance\b|\bFrench\b|\bParis\b"),
    ("CH", "Switzerland", 47.4, 8.5, r"\bSwiss\b|\bSwitzerland\b|\bZug\b|\bFINMA\b"),
    ("CN", "China", 39.9, 116.4, r"\bChina\b|\bChinese\b|\bBeijing\b|\bPBOC\b|\bShanghai\b"),
    ("HK", "Hong Kong", 22.3, 114.2, r"\bHong Kong\b|\bSFC\b"),
    ("JP", "Japan", 35.7, 139.7, r"\bJapan(?:ese)?\b|\bTokyo\b"),
    ("KR", "South Korea", 37.6, 127.0, r"\bKorea(?:n)?\b|\bSeoul\b|\bUpbit\b|\bBithumb\b"),
    ("SG", "Singapore", 1.35, 103.8, r"\bSingapore\b|\bMAS\b"),
    ("IN", "India", 28.6, 77.2, r"\bIndia(?:n)?\b|\bRBI\b|\bMumbai\b"),
    ("AE", "UAE", 25.2, 55.3, r"\bUAE\b|\bDubai\b|\bAbu Dhabi\b|\bVARA\b|\bEmirates\b"),
    ("RU", "Russia", 55.8, 37.6, r"\bRussia(?:n)?\b|\bMoscow\b|\bKremlin\b"),
    ("UA", "Ukraine", 50.5, 30.5, r"\bUkrain(?:e|ian)\b|\bKyiv\b"),
    ("TR", "Turkey", 41.0, 29.0, r"\bTurkey\b|\bTürkiye\b|\bTurkish\b|\bIstanbul\b"),
    ("BR", "Brazil", -15.8, -47.9, r"\bBrazil(?:ian)?\b|\bSão Paulo\b|\bSao Paulo\b"),
    ("AR", "Argentina", -34.6, -58.4, r"\bArgentin(?:a|e|ian)\b|\bMilei\b|\bBuenos Aires\b"),
    ("SV", "El Salvador", 13.7, -89.2, r"\bEl Salvador\b|\bBukele\b|\bSalvador(?:an)?\b"),
    ("MX", "Mexico", 19.4, -99.1, r"\bMexic(?:o|an)\b"),
    ("CA", "Canada", 45.4, -75.7, r"\bCanad(?:a|ian)\b|\bToronto\b|\bOntario\b"),
    ("AU", "Australia", -33.9, 151.2, r"\bAustralia(?:n)?\b|\bASIC\b|\bSydney\b"),
    ("NG", "Nigeria", 9.1, 7.5, r"\bNigeria(?:n)?\b|\bLagos\b"),
    ("ZA", "South Africa", -25.7, 28.2, r"\bSouth Africa(?:n)?\b"),
    ("KE", "Kenya", -1.3, 36.8, r"\bKenya(?:n)?\b|\bNairobi\b"),
    ("TH", "Thailand", 13.8, 100.5, r"\bThai(?:land)?\b|\bBangkok\b"),
    ("VN", "Vietnam", 21.0, 105.8, r"\bVietnam(?:ese)?\b"),
    ("PH", "Philippines", 14.6, 121.0, r"\bPhilippines?\b|\bFilipino\b"),
    ("ID", "Indonesia", -6.2, 106.8, r"\bIndonesia(?:n)?\b|\bJakarta\b"),
    ("PK", "Pakistan", 33.7, 73.1, r"\bPakistan(?:i)?\b"),
    ("KZ", "Kazakhstan", 51.2, 71.4, r"\bKazakh(?:stan)?\b"),
    ("IL", "Israel", 31.8, 35.2, r"\bIsrael(?:i)?\b"),
    ("TW", "Taiwan", 25.0, 121.6, r"\bTaiwan(?:ese)?\b"),
    ("BT", "Bhutan", 27.5, 89.6, r"\bBhutan\b"),
)
_REGION_RE = [(c, n, la, lo, re.compile(p)) for c, n, la, lo, p in REGIONS]

_DEVELOPING = re.compile(
    r"\b(breaking|developing|reportedly|report says|sources say|rumou?r|unconfirmed)\b", re.I
)
_COMMENTARY = re.compile(
    r"/(opinion|op-ed|analysis|editorial|column|guides?|learn|explainers?)/|\b(opinion|op-ed|analysis)\b",
    re.I,
)
_STOP = set(
    ["a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "with", "by", "at", "from", "as", "is", "are", "was", "were", "be", "been", "this", "that", "its", "it's", "new", "news", "says", "say", "after", "over", "into", "how", "why", "what", "will", "can", "could", "may", "more", "than", "up", "down", "amid"]
)
_TAGS = re.compile(r"<[^>]+>")


@dataclass
class Item:
    id: str
    source: str
    url: str
    title: str
    summary: str
    published_at: datetime
    image: str | None = None
    topics: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    kind: str = "report"  # report | developing | commentary


def _text(el: ET.Element | None) -> str:
    return "" if el is None or el.text is None else el.text


def _clean(raw: str, limit: int) -> str:
    text = html.unescape(_TAGS.sub(" ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _when(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def classify(item: Item) -> Item:
    text = f"{item.title} {item.summary}"
    item.topics = [t for t, rx in _TOPIC_RE.items() if rx.search(text)]
    if "regulation" not in item.topics and _REG_ACRONYM.search(text):
        item.topics.append("regulation")
    item.regions = [c for c, _n, _la, _lo, rx in _REGION_RE if rx.search(text)]
    if _COMMENTARY.search(item.url) or _COMMENTARY.search(item.title):
        item.kind = "commentary"
    elif _DEVELOPING.search(item.title):
        item.kind = "developing"
    return item


def parse(source: str, body: bytes) -> list[Item]:
    """RSS 2.0 or Atom, tolerant of publishers' quirks. Bad entries are skipped."""
    # Publishers' XML is untrusted: no DTDs or entities (billion-laughs), and a size cap.
    if len(body) > 3_000_000 or b"<!ENTITY" in body or b"<!DOCTYPE" in body[:2000]:
        raise ValueError("feed refused: oversized or declares entities")
    root = ET.fromstring(body)  # noqa: S314 - guarded above; expat also caps expansion
    ns = {"media": "http://search.yahoo.com/mrss/", "atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
    out: list[Item] = []
    for e in entries:
        title = _clean(_text(e.find("title")) or _text(e.find("atom:title", ns)), 220)
        link_el = e.find("link")
        url = _text(link_el).strip() if link_el is not None and link_el.text else ""
        if not url:
            atom_link = e.find("atom:link", ns)
            url = atom_link.get("href", "") if atom_link is not None else ""
        when = _when(
            _text(e.find("pubDate"))
            or _text(e.find("atom:published", ns))
            or _text(e.find("atom:updated", ns))
        )
        if not title or not url.startswith("http") or when is None:
            continue
        summary = _clean(
            _text(e.find("description")) or _text(e.find("atom:summary", ns)), 260
        )
        image = None
        for path in ("media:content", "media:thumbnail"):
            m = e.find(path, ns)
            if m is not None and m.get("url", "").startswith("https://"):
                image = m.get("url")
                break
        if image is None:
            enc = e.find("enclosure")
            if (
                enc is not None
                and enc.get("type", "").startswith("image")
                and enc.get("url", "").startswith("https://")
            ):
                image = enc.get("url")
        out.append(
            classify(
                Item(
                    id=f"{source}:{url}",
                    source=source,
                    url=url,
                    title=title,
                    summary=summary,
                    published_at=when,
                    image=image,
                )
            )
        )
    return out


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$]{3,}", title.lower()) if w not in _STOP}


def cluster(items: list[Item], threshold: float = 0.34) -> list[list[Item]]:
    """Same story, several publishers: grouped when their headlines share enough
    distinctive words. Oldest first inside a group, newest group first."""
    items = sorted(items, key=lambda i: i.published_at)
    groups: list[tuple[set[str], list[Item]]] = []
    for it in items:
        w = _words(it.title)
        best, score = None, 0.0
        for gw, g in groups[-250:]:
            if not w or not gw:
                continue
            s = len(w & gw) / len(w | gw)
            if (
                s > score
                and (it.published_at - g[-1].published_at).total_seconds() < 36 * 3600
            ):
                best, score = (gw, g), s
        if best is not None and (score >= threshold or len(w & best[0]) >= 4):
            best[0].update(w)
            best[1].append(it)
        else:
            groups.append((set(w), [it]))
    return sorted((g for _, g in groups), key=lambda g: g[-1].published_at, reverse=True)
