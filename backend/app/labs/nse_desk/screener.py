"""Read one company's screener.in page into a fixed card (Karthik, 2026-10-10:
"build NSE Lab with one agent ... go to screener.in and provide me details").

screener.in's terms allow "personal, non-commercial transitory viewing only",
so this is read on demand for the admin alone, never stored, never cached and
never shown to anyone else; every card links back to the page it came from.
Its robots.txt blocks search URLs (`/*?q=`), so a company NAME is matched
against NSE's own list of listed companies, never screener.in's search.
Stdlib parsing: the page's sections are plain tables.
"""

from __future__ import annotations

import csv
import html as htmllib
import io
import re
import time
from html.parser import HTMLParser
from typing import Any

import httpx

BASE = "https://www.screener.in"
NSE_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MEMESCOPE personal desk)"}


class _Tables(HTMLParser):
    """Every <table> in a fragment as rows of cell texts."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _section(html: str, sid: str) -> str:
    m = re.search(rf'<section[^>]*id="{sid}"[^>]*>(.*?)</section>', html, re.S)
    return m.group(1) if m else ""


def _tables(fragment: str) -> list[list[list[str]]]:
    p = _Tables()
    p.feed(fragment)
    return p.tables


def _row(table: list[list[str]], label: str) -> list[str] | None:
    for r in table:
        if r and r[0].lower().rstrip(" +").startswith(label.lower()):
            return r
    return None


def _last(table: list[list[str]], label: str, n: int) -> dict[str, list[str]] | None:
    """The last `n` columns of one labelled row, with their header dates."""
    if not table:
        return None
    row = _row(table, label)
    if row is None:
        return None
    return {"periods": table[0][1:][-n:], "values": row[1:][-n:]}


def parse(html: str) -> dict[str, Any]:
    """The card: name, top ratios, growth, last results, debt, promoters, pros/cons."""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    top = re.search(r'id="top-ratios"(.*?)</ul>', html, re.S)
    ratios = [{"name": _text(n), "value": _text(v)} for n, v in re.findall(
        r'<span class="name">(.*?)</span>\s*<span class="nowrap value">(.*?)</span>\s*</li>',
        top.group(0) if top else "", re.S)]
    growth = []
    ranges = re.findall(r'<table class="ranges-table">.*?</table>', html, re.S)
    for t in _tables("".join(ranges)):
        if t:
            growth.append({"title": t[0][0], "rows": [r for r in t[1:] if len(r) == 2]})
    quarters = (_tables(_section(html, "quarters")) or [[]])[0]
    pl = (_tables(_section(html, "profit-loss")) or [[]])[0]
    bs = (_tables(_section(html, "balance-sheet")) or [[]])[0]
    shp = (_tables(_section(html, "shareholding")) or [[]])[0]
    lists = {k: [_text(li) for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.S)]
             for k in ("pros", "cons")
             if (m := re.search(rf'class="{k}"[^>]*>.*?<ul>(.*?)</ul>', html, re.S))}
    about = re.search(r'<div class="sub show-more-box about"[^>]*>(.*?)</div>', html, re.S)
    return {
        "name": _text(h1.group(1)) if h1 else None,
        "about": _text(about.group(1))[:600] if about else None,
        "ratios": ratios,
        "growth": growth,
        "quarters": {k: _last(quarters, k, 4) for k in ("Sales", "Net Profit")},
        "yearly": {k: _last(pl, k, 3) for k in ("Sales", "Net Profit")},
        "borrowings": _last(bs, "Borrowings", 3),
        "promoters": _last(shp, "Promoters", 4),
        "pros": lists.get("pros", []),
        "cons": lists.get("cons", []),
    }


def has_numbers(card: dict[str, Any]) -> bool:
    """Whether the top ratios carry any figures at all."""
    return any(re.search(r"\d", r["value"]) for r in card["ratios"])


_NSE: tuple[float, list[tuple[str, str]]] | None = None


async def _nse_list(client: httpx.AsyncClient) -> list[tuple[str, str]]:
    """(symbol, company name) for every NSE-listed equity; read once a day."""
    global _NSE
    if _NSE is not None and time.time() - _NSE[0] < 86_400:
        return _NSE[1]
    r = await client.get(NSE_LIST, headers=HEADERS, timeout=20)
    r.raise_for_status()
    rows = [(row["SYMBOL"].strip(), row["NAME OF COMPANY"].strip())
            for row in csv.DictReader(io.StringIO(r.text)) if row.get("SYMBOL")]
    _NSE = (time.time(), rows)
    return rows


def match(query: str, listed: list[tuple[str, str]]) -> str | None:
    """A symbol for `query`: an exact symbol, else the shortest company name
    containing every word of it."""
    q = query.strip().upper()
    if any(s == q for s, _ in listed):
        return q
    words = [w for w in re.split(r"\W+", q) if w and w not in ("LTD", "LIMITED", "THE")]
    hits = [(len(n), s) for s, n in listed if words and all(w in n.upper() for w in words)]
    return min(hits)[1] if hits else None


async def company(query: str) -> dict[str, Any] | None:
    """One company's card, or None if no page was found."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            listed = await _nse_list(client)
        except httpx.HTTPError:
            listed = []
        q = query.strip().upper()
        looks_like_symbol = re.fullmatch(r"[A-Z0-9&\-]{1,20}", q)
        symbol = match(query, listed) or (q if looks_like_symbol else None)
        if not symbol:
            return None
        for path, consolidated in ((f"/company/{symbol}/consolidated/", True),
                                   (f"/company/{symbol}/", False)):
            r = await client.get(BASE + path, headers=HEADERS, timeout=20)
            if r.status_code == 200 and 'id="top-ratios"' in r.text:
                card = parse(r.text)
                # A company with no subsidiaries has an empty consolidated
                # page (labels, no numbers): fall through to standalone.
                if not has_numbers(card):
                    continue
                return {**card, "symbol": symbol, "url": BASE + path,
                        "consolidated": consolidated}
    return None
