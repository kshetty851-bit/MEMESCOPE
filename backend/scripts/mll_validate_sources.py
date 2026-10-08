"""Live validation of the Meme Lifecycle Lab's sources - ONE request each.

Run where the sources are reachable (not from the CI / dev container, whose
network policy blocks them - see docs/MEME_LIFECYCLE_LAB.md "LIVE SOURCE
STATUS"):

    docker compose exec -T backend python scripts/mll_validate_sources.py
    docker compose exec -T backend python scripts/mll_validate_sources.py --dry-run

Each enabled source is asked exactly once through its REAL adapter (the same
code the scheduler runs), and the script prints the HTTP status, content-type,
top-level keys and the adapter's parsed status / reason:

  * GDELT       one timeline request at the scheduler's maximum span (24 h), so
                the 15-minute-resolution assumption is checked where it is
                most likely to break;
  * Wikipedia   one per-article daily pageviews request;
  * DexScreener one token-profile request for ``--mint``;
  * pump.fun    no network: the poller's freshness, read from the database if
                one is reachable.

The raw GDELT answer (status, a header subset, verbatim body, url, query,
retrieved_at) is written to
``tests/fixtures/lifecycle_lab/gdelt/live_timelinevolraw.json`` ONLY when it is
HTTP 200 with a JSON object body - so a throttle page or an error is never
committed as "the success shape". Commit that file; the live-shape tests in
``tests/unit/test_mll_gdelt.py`` then stop skipping.

``--dry-run`` sends nothing: requests are intercepted before the network and
printed, and the database is not touched.

The Lab feature flag is forced on *in this process only* so the adapters will
run; each source's own ``MLL_*_ENABLED`` switch is honoured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
FIXTURE_DIR = BACKEND / "tests" / "fixtures" / "lifecycle_lab" / "gdelt"
LIVE_FIXTURE_NAME = "live_timelinevolraw.json"
#: Headers worth keeping with a capture: enough to see what GDELT said about
#: the body and its caching, nothing that identifies the caller.
HEADER_SUBSET = (
    "content-type",
    "content-length",
    "content-encoding",
    "date",
    "server",
    "cache-control",
    "expires",
    "last-modified",
    "retry-after",
)
DEFAULT_NAME = "Pepe"
DEFAULT_WIKIPEDIA_TITLE = "Pepe_the_Frog"
#: BONK - long-lived, reliably listed on DexScreener. Override with --mint.
DEFAULT_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


@dataclass
class Exchange:
    method: str
    url: str
    status: int | None
    headers: dict[str, str]
    body: str
    sent: bool


def top_level(body: str) -> str:
    """A one-line description of a body: JSON keys, list length or a text head."""
    text = body.lstrip("﻿").strip()
    if not text:
        return "<empty body>"
    try:
        parsed = json.loads(text)
    except ValueError:
        return "<not JSON> " + repr(text[:120])
    if isinstance(parsed, dict):
        return "keys=" + ",".join(sorted(parsed)) if parsed else "<empty object>"
    if isinstance(parsed, list):
        return f"<JSON list, {len(parsed)} items>"
    return f"<JSON {type(parsed).__name__}>"


def live_fixture(
    exchange: Exchange, *, query: str, retrieved_at: datetime
) -> dict[str, Any] | None:
    """The fixture document, or None when the answer is not a success shape
    (non-200, or a body that is not a JSON object)."""
    if exchange.status != 200:
        return None
    try:
        parsed = json.loads(exchange.body.lstrip("﻿"))
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        "synthetic": False,
        "captured_by": "scripts/mll_validate_sources.py",
        "url": exchange.url,
        "query": query,
        "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
        "status": exchange.status,
        "headers": {k: v for k, v in exchange.headers.items() if k in HEADER_SUBSET},
        "body": exchange.body,
    }


def write_live_fixture(document: dict[str, Any], directory: Path = FIXTURE_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LIVE_FIXTURE_NAME
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return path


def _print_exchange(ex: Exchange) -> None:
    if not ex.sent:
        print(f"    would request: {ex.method} {ex.url}   (dry-run: not sent)")
        return
    print(f"    request:       {ex.method} {ex.url}")
    if ex.status is None:
        print("    http status:   <no HTTP response: transport failure, see parsed reason>")
        return
    print(f"    http status:   {ex.status}")
    print(f"    content-type:  {ex.headers.get('content-type', '<none>')}")
    print(f"    top level:     {top_level(ex.body)}")


def _print_result(result: Any) -> None:
    print(f"    parsed:        status={result.status.value} reason={result.reason}")
    for key, (status, reason) in sorted(result.per_subject.items()):
        print(f"      subject {key}: {status.value} {reason or ''}".rstrip())
    for key, detail in sorted(result.per_subject_detail.items()):
        print(f"      detail {key}: {detail}")
    widths = sorted(
        {
            o.raw_payload["bucket_seconds"]
            for o in result.observations
            if o.raw_payload and "bucket_seconds" in o.raw_payload
        }
    )
    print(
        f"    observations:  {len(result.observations)}"
        + (f" bucket_seconds={widths}" if widths else "")
    )


async def _pumpfun(cfg: Any, now: datetime, *, dry_run: bool) -> bool:
    from app.lifecycle_lab.adapters import PumpfunRepliesAdapter

    adapter = PumpfunRepliesAdapter(cfg)
    ok, why = adapter.enabled()
    print("\n[pumpfun_replies] (no network: poller freshness from the database)")
    if not ok:
        print(f"    DISABLED: {why}")
        return True
    if dry_run:
        print(
            "    would read: newest pumpfun_social_snapshots.observed_at   (dry-run: not read)"
        )
        return True
    try:
        from app.db.session import SessionFactory
        from app.lifecycle_lab.repository import LifecycleLabRepository

        async with SessionFactory() as session:
            latest = await LifecycleLabRepository(session).pumpfun_social_latest_observed_at()
            await session.rollback()
    except Exception as exc:  # the DB is optional for this script
        print(f"    database unavailable ({type(exc).__name__}); freshness not checked")
        return True
    result = adapter.probe(latest, now=now)
    print(f"    latest observed_at: {latest.isoformat() if latest else None}")
    print(f"    parsed:        status={result.status.value} reason={result.reason}")
    return result.status.value != "error"


async def run(args: argparse.Namespace) -> int:
    import httpx

    from app.core.config import settings
    from app.lifecycle_lab.adapters import (
        DexScreenerAdapter,
        GdeltAdapter,
        Subject,
        WikipediaAdapter,
    )
    from app.lifecycle_lab.adapters.gdelt import (
        MAX_FORWARD_TIMESPAN,
        query_for,
        timespan_param,
    )
    from app.lifecycle_lab.domain import Meme

    cfg = settings.model_copy(update={"FEATURE_LIFECYCLE_LAB_ENABLED": True})
    now = datetime.now(UTC)
    meme = Meme(
        id="validation",
        slug="validation",
        display_name=args.name,
        tracking_started_at=now - timedelta(days=1),
        wikipedia_title=args.wikipedia_title,
        gdelt_query=args.gdelt_query,
    )
    subject = Subject(meme=meme, mints=(args.mint,))
    exchanges: list[Exchange] = []

    async def on_request(request: httpx.Request) -> None:
        exchanges.append(Exchange(request.method, str(request.url), None, {}, "", True))

    async def on_response(response: httpx.Response) -> None:
        await response.aread()
        url = str(response.request.url)
        for ex in reversed(exchanges):
            if ex.url == url and ex.status is None:
                ex.status = response.status_code
                ex.headers = {k.lower(): v for k, v in response.headers.items()}
                ex.body = response.text
                break

    def refuse(request: httpx.Request) -> httpx.Response:
        exchanges.append(Exchange(request.method, str(request.url), None, {}, "", False))
        raise httpx.ConnectError("dry-run: not sent", request=request)

    client = (
        httpx.AsyncClient(transport=httpx.MockTransport(refuse))
        if args.dry_run
        else httpx.AsyncClient(
            timeout=30.0, event_hooks={"request": [on_request], "response": [on_response]}
        )
    )
    print(f"Lifecycle Lab source validation  now={now.isoformat()}  dry_run={args.dry_run}")
    failures = 0
    async with client:
        # ---- GDELT
        gdelt = GdeltAdapter(cfg, client)
        ok, why = gdelt.enabled()
        span = timespan_param(MAX_FORWARD_TIMESPAN)
        print(f"\n[gdelt] query={query_for(subject)!r} span={span}")
        if not ok:
            print(f"    DISABLED: {why}")
        else:
            gdelt.set_schedule(last_success={})  # never collected -> the maximum span
            start = len(exchanges)
            result = await gdelt.collect([subject], now=now)
            for ex in exchanges[start:]:
                _print_exchange(ex)
            if not args.dry_run:
                _print_result(result)
                failures += result.status.value == "error"
                gdelt_ex = exchanges[start] if len(exchanges) > start else None
                doc = (
                    None
                    if gdelt_ex is None
                    else live_fixture(gdelt_ex, query=query_for(subject), retrieved_at=now)
                )
                if doc is None:
                    print(
                        "    fixture:       NOT written (not HTTP 200 with a JSON object body)"
                    )
                elif args.no_fixture:
                    print("    fixture:       success shape seen; not written (--no-fixture)")
                else:
                    path = write_live_fixture(doc, args.fixture_dir)
                    print(f"    fixture:       written to {path}")
            elif result.reason != "network_error":
                print(f"    unexpected dry-run outcome: {result.reason}")

        # ---- Wikipedia
        wiki = WikipediaAdapter(cfg, client)
        ok, why = wiki.enabled()
        print(f"\n[wikipedia] title={args.wikipedia_title!r}")
        if not ok:
            print(f"    DISABLED: {why}")
        else:
            start = len(exchanges)
            result = await wiki.collect([subject], now=now)
            for ex in exchanges[start:]:
                _print_exchange(ex)
            if not args.dry_run:
                _print_result(result)
                failures += result.status.value == "error"

        # ---- DexScreener
        dex = DexScreenerAdapter(cfg, client)
        ok, why = dex.enabled()
        print(f"\n[dexscreener] mint={args.mint}")
        if not ok:
            print(f"    DISABLED: {why}")
        else:
            start = len(exchanges)
            result = await dex.collect([subject], now=now)
            for ex in exchanges[start:]:
                _print_exchange(ex)
            if not args.dry_run:
                _print_result(result)
                failures += result.status.value == "error"

    # ---- pump.fun (no network)
    if not await _pumpfun(cfg, now, dry_run=args.dry_run):
        failures += 1

    sent = sum(1 for ex in exchanges if ex.sent)
    print(
        f"\n{len(exchanges)} request(s) {'planned' if args.dry_run else 'made'}, {sent} sent."
    )
    if args.dry_run:
        return 0
    print(
        "All enabled sources answered." if not failures else f"{failures} source(s) in ERROR."
    )
    return 0 if not failures else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="print requests, send nothing")
    parser.add_argument("--name", default=DEFAULT_NAME, help="display name (GDELT phrase)")
    parser.add_argument("--gdelt-query", default=None, help="curated GDELT query (verbatim)")
    parser.add_argument("--wikipedia-title", default=DEFAULT_WIKIPEDIA_TITLE)
    parser.add_argument("--mint", default=DEFAULT_MINT, help="Solana mint for DexScreener")
    parser.add_argument("--fixture-dir", type=Path, default=FIXTURE_DIR)
    parser.add_argument("--no-fixture", action="store_true", help="never write the fixture")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
