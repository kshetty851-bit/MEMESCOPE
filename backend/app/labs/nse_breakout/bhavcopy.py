"""UDiFF bhavcopy CSV -> daily bars. Pure; no I/O, no clock.

The exchange publishes one ZIP per trading day containing EVERY instrument it
lists — equities, SME, government securities, gold bonds, suspended names. The
whole job of this module is to take that file apart safely and hand back only
the rows that are an ordinary equity trading day.

Column names come from the real file, not from documentation:

    TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,
    XpryDt,...,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPr,...

Parsed by NAME rather than position, because a positional parser breaks
silently the first time the exchange inserts a column, and the failure looks
like bad prices rather than a bad parse.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.labs.nse_breakout import config


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    name: str | None
    isin: str | None
    series: str
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal | None


class BhavcopyError(ValueError):
    """The file is not a bhavcopy we recognise — a 404 page, an error body, or
    a format change. Raised rather than returning nothing, because "no rows"
    and "not the file we asked for" must not look the same."""


def unzip(payload: bytes) -> str:
    """The ZIP's single CSV, as text.

    A 404 from the archive is an HTML page with a 200-shaped body in some
    cases, so the magic number is checked before `zipfile` is given a chance
    to raise something less legible.
    """
    if payload[:2] != b"PK":
        head = payload[:80].decode("utf-8", "replace").strip()
        raise BhavcopyError(f"not a ZIP (starts {head!r})")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise BhavcopyError(f"corrupt ZIP: {exc}") from exc
    names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise BhavcopyError(f"no CSV inside: {archive.namelist()}")
    return archive.read(names[0]).decode("utf-8", "replace")


def _dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text in {"-", "NA"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _int(value: str | None) -> int | None:
    parsed = _dec(value)
    return None if parsed is None else int(parsed)


def parse(text: str) -> Iterator[Bar]:
    """Every ordinary equity bar in the file, skipping everything else.

    A row is kept only when it is `STK`, in an allowed series, and carries a
    complete OHLC. Anything malformed is DROPPED rather than defaulted: a bar
    with a zero low would sit under every future support level for ever, and a
    bar with a guessed close is worse than no bar at all.
    """
    reader = csv.DictReader(io.StringIO(text))
    required = {"TckrSymb", "SctySrs", "TradDt", "OpnPric", "HghPric",
                "LwPric", "ClsPric"}
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise BhavcopyError(f"missing columns: {sorted(missing)}")

    for row in reader:
        if (row.get("FinInstrmTp") or "").strip() != config.ALLOWED_INSTRUMENT:
            continue
        series = (row.get("SctySrs") or "").strip()
        if series not in config.ALLOWED_SERIES:
            continue
        symbol = (row.get("TckrSymb") or "").strip()
        if not symbol:
            continue
        try:
            traded = datetime.strptime((row["TradDt"] or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            continue

        prices = [_dec(row.get(k)) for k in
                  ("OpnPric", "HghPric", "LwPric", "ClsPric")]
        if any(p is None or p <= 0 for p in prices):
            continue
        open_, high, low, close = prices  # type: ignore[misc]
        # The exchange has published rows where the high is below the low.
        # One is a data error; both make every level computed from it wrong.
        if high < low or high < open_ or high < close or low > open_ or low > close:
            continue

        volume = _int(row.get("TtlTradgVol")) or 0
        turnover = _dec(row.get("TtlTrfVal"))
        yield Bar(
            symbol=symbol,
            name=(row.get("FinInstrmNm") or "").strip() or None,
            isin=(row.get("ISIN") or "").strip() or None,
            series=series,
            date=traded,
            open=open_, high=high, low=low, close=close,
            volume=volume, turnover=turnover,
        )


def parse_index_closes(text: str, index_name: str = config.NIFTY_NAME
                       ) -> tuple[date, Decimal] | None:
    """`(date, close)` for one index out of `ind_close_all_DDMMYYYY.csv`.

    Returns None rather than raising when the index is absent: a missing Nifty
    close makes one window's relative return null, which is the pre-decided
    behaviour, and must never take an ingest down with it.
    """
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = (row.get("Index Name") or row.get("indexName") or "").strip()
        if name.casefold() != index_name.casefold():
            continue
        close = _dec(row.get("Closing Index Value") or row.get("closingValue"))
        raw = (row.get("Index Date") or row.get("indexDate") or "").strip()
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                when = datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
            if close is not None and close > 0:
                return when, close
            break
    return None
