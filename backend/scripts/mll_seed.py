#!/usr/bin/env python3
"""Seed the Meme Lifecycle Lab's curated registry through its admin API.

    MLL_ADMIN_TOKEN=<admin bearer token> \\
        python scripts/mll_seed.py [--dry-run] [--base-url URL] SEED.json

Why an API client and not SQL: the admin endpoints are where the Lab's
timestamp rules live. ``tracking_started_at``, every alias's ``added_at`` and
every link's ``linked_at`` are the *server's* clock, so a seed run cannot date a
fact earlier than the moment it was curated. Writing rows directly would let a
script backdate a link, which is exactly the look-ahead the Lab exists to
exclude. This script therefore never sends ``linked_at`` (a seed entry that
carries one is refused rather than silently dropped).

Two rules are enforced here, before any request is made, because a bad link
contaminates every feature derived from it and the permanent record cannot be
edited:

* A link needs **evidence**. A ticker, a symbol or a name match is never
  sufficient on its own (thousands of tokens share a ticker), so
  ``exact_symbol`` / ``exact_name`` / ``alias_match`` are refused outright.
  Accepted methods: ``manual`` (with ``evidence_url`` and ``evidence_note``
  saying how identity was verified) and ``website_match`` / ``social_link_match``
  (with ``evidence_url`` and the matched website URL / handle in ``matched``).
* Any value left as ``TO_VERIFY`` is a placeholder, not data. A placeholder
  alias is skipped, and a link whose ``mint`` is ``TO_VERIFY`` is reported as
  pending. A real mint with a placeholder or missing evidence is an error.

Idempotent: the registry is read first (``GET /memes/{slug}``) and anything
already present is skipped; the endpoints are themselves idempotent on the
alias and link keys. An existing meme's description/queries are never
rewritten - they are part of the record.

Each link is sent with its ``method``, ``evidence_url`` and ``evidence_note``;
the server stores them (with the submitting admin) in the link's evidence, shown
by ``GET /memes/{slug}/quality``. For ``website_match`` / ``social_link_match``
the matched website / handle travels as the note when no note is given. The
seed file stays the operator's audit trail too - commit it.

Exit codes: 0 ok, 1 request failure, 2 invalid seed file / usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

PLACEHOLDER = "TO_VERIFY"
API_PREFIX = "/api/v1/lifecycle-lab"
TOKEN_ENV = "MLL_ADMIN_TOKEN"  # noqa: S105 - the variable's name, not a secret
DEFAULT_BASE_URL = "http://localhost:8000"

# Mirror app.lifecycle_lab.schemas / domain. Kept as literals so the script runs
# without importing the app (and so a server-side change shows up as a 422, not
# as a silently different client).
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
ALIAS_KINDS = frozenset(
    {"name", "symbol", "hashtag", "phrase", "wiki_title", "domain", "social_handle"}
)
#: Methods that can rest on evidence beyond a name or ticker.
EVIDENCED_METHODS = frozenset({"manual", "website_match", "social_link_match"})
#: Methods refused outright: a collision-prone text match is not identity.
TEXT_ONLY_METHODS = frozenset({"exact_name", "exact_symbol", "alias_match"})
TEXT_ONLY_BASES = frozenset({"ticker", "symbol", "name", "alias"})

MEME_KEYS = {
    "slug",
    "display_name",
    "description",
    "wikipedia_title",
    "gdelt_query",
    "aliases",
    "identity",
    "links",
}
ALIAS_KEYS = {"alias", "kind"}
LINK_KEYS = {
    "mint",
    "method",
    "confidence",
    "evidence_url",
    "evidence_note",
    "evidence_basis",
    "matched",
}


class SeedError(Exception):
    """The seed file is unusable. ``problems`` lists every defect found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Step:
    """One planned (or skipped) operation."""

    action: str  # create_meme | add_alias | add_link | skip | pending
    slug: str
    detail: str
    method: str | None = None
    path: str | None = None
    body: dict[str, Any] | None = field(default=None, compare=False)

    @property
    def sends_request(self) -> bool:
        return self.method is not None


# --------------------------------------------------------------------------
# Validation (pure)
# --------------------------------------------------------------------------


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip() == PLACEHOLDER


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_link(link: Any, where: str) -> list[str]:
    """Defects in one link entry. A ``TO_VERIFY`` mint is a pending slot, not a defect."""
    if not isinstance(link, dict):
        return [f"{where}: a link must be an object"]
    problems: list[str] = []
    if "linked_at" in link:
        problems.append(
            f"{where}: linked_at is never accepted - the server stamps the link's time"
        )
    for key in sorted(set(link) - LINK_KEYS - {"linked_at"}):
        problems.append(f"{where}: unknown key {key!r}")
    if _is_placeholder(link.get("mint")):
        return problems  # pending: nothing else can be judged until it is real
    mint = link.get("mint")
    if not isinstance(mint, str) or not MINT_RE.match(mint):
        problems.append(f"{where}: mint is not a base58 address")
    method = link.get("method", "manual")
    if method in TEXT_ONLY_METHODS:
        problems.append(
            f"{where}: method {method!r} is a name/ticker match - never sufficient. "
            "Use 'manual', 'website_match' or 'social_link_match' with evidence"
        )
    elif method not in EVIDENCED_METHODS:
        problems.append(f"{where}: unknown method {method!r}")
    basis = link.get("evidence_basis")
    if isinstance(basis, str) and basis.strip().lower() in TEXT_ONLY_BASES:
        problems.append(
            f"{where}: evidence_basis {basis!r} - a ticker/name match alone is not evidence"
        )
    url = link.get("evidence_url")
    if _blank(url) or _is_placeholder(url) or not _http_url(url):
        problems.append(f"{where}: evidence_url is required (http(s) URL showing the match)")
    if method == "manual" and (
        _blank(link.get("evidence_note")) or _is_placeholder(link.get("evidence_note"))
    ):
        problems.append(f"{where}: manual link needs evidence_note (how it was verified)")
    if method in {"website_match", "social_link_match"} and (
        _blank(link.get("matched")) or _is_placeholder(link.get("matched"))
    ):
        problems.append(f"{where}: {method} needs 'matched' (the matched website / handle)")
    try:
        confidence = Decimal(str(link.get("confidence")))
        if not (Decimal(0) < confidence <= Decimal(1)):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        problems.append(f"{where}: confidence must be a decimal in (0, 1]")
    return problems


def validate_seed(seed: Any) -> list[str]:
    """Every defect in the seed document, all at once (so one run fixes them all)."""
    if not isinstance(seed, dict) or not isinstance(seed.get("memes"), list):
        return ["seed must be an object with a 'memes' list"]
    problems: list[str] = []
    seen: set[str] = set()
    for i, meme in enumerate(seed["memes"]):
        if not isinstance(meme, dict):
            problems.append(f"memes[{i}]: must be an object")
            continue
        slug = meme.get("slug")
        where = f"memes[{i}]({slug})"
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            problems.append(f"{where}: slug must match {SLUG_RE.pattern}")
        elif slug in seen:
            problems.append(f"{where}: duplicate slug")
        else:
            seen.add(slug)
        if _blank(meme.get("display_name")) or _is_placeholder(meme.get("display_name")):
            problems.append(f"{where}: display_name is required")
        for key in sorted(set(meme) - MEME_KEYS):
            problems.append(f"{where}: unknown key {key!r}")
        for key in ("wikipedia_title", "gdelt_query"):
            if _is_placeholder(meme.get(key)):
                problems.append(f"{where}: {key} is still {PLACEHOLDER}")
        for j, alias in enumerate(meme.get("aliases") or []):
            a_where = f"{where}.aliases[{j}]"
            if not isinstance(alias, dict) or set(alias) - ALIAS_KEYS:
                problems.append(f"{a_where}: expected only {sorted(ALIAS_KEYS)}")
            elif alias.get("kind") not in ALIAS_KINDS:
                problems.append(f"{a_where}: kind must be one of {sorted(ALIAS_KINDS)}")
            elif _blank(alias.get("alias")):
                problems.append(f"{a_where}: alias is empty")
        for j, link in enumerate(meme.get("links") or []):
            problems += validate_link(link, f"{where}.links[{j}]")
    return problems


# --------------------------------------------------------------------------
# Planning (pure given the registry snapshot)
# --------------------------------------------------------------------------


def _norm(alias: str) -> str:
    return " ".join(alias.casefold().split())


def _link_body(link: Mapping[str, Any]) -> dict[str, Any]:
    method = link.get("method", "manual")
    note = link.get("evidence_note")
    if _blank(note) and method != "manual":
        note = f"matched: {link['matched']}"
    body: dict[str, Any] = {
        "mint": link["mint"],
        "confidence": str(link["confidence"]),
        "method": method,
        "evidence_url": link["evidence_url"],
    }
    if not _blank(note):
        body["evidence_note"] = note
    return body


def plan_meme(meme: dict[str, Any], existing: dict[str, Any] | None) -> list[Step]:
    """Steps for one meme. ``existing`` is ``GET /memes/{slug}`` or ``None``."""
    slug = meme["slug"]
    steps: list[Step] = []
    aliases = [a for a in meme.get("aliases") or [] if not _is_placeholder(a.get("alias"))]
    skipped_placeholders = len(meme.get("aliases") or []) - len(aliases)
    if existing is None:
        body: dict[str, Any] = {
            "slug": slug,
            "display_name": meme["display_name"],
            "aliases": [{"alias": a["alias"], "kind": a["kind"]} for a in aliases],
        }
        for key in ("description", "wikipedia_title", "gdelt_query"):
            if meme.get(key):
                body[key] = meme[key]
        steps.append(
            Step(
                "create_meme",
                slug,
                f"{meme['display_name']} with {len(aliases)} alias(es)",
                "POST",
                f"{API_PREFIX}/memes",
                body,
            )
        )
        known_aliases: set[tuple[str, str]] = {(a["kind"], _norm(a["alias"])) for a in aliases}
        known_mints: set[str] = set()
    else:
        known_aliases = {(a["kind"], _norm(a["alias"])) for a in existing.get("aliases") or []}
        known_mints = {k["mint"] for k in existing.get("links") or []}
        steps.append(Step("skip", slug, "meme exists - description/queries are not rewritten"))
        for alias in aliases:
            key = (alias["kind"], _norm(alias["alias"]))
            if key in known_aliases:
                steps.append(
                    Step("skip", slug, f"alias exists: {alias['kind']} {alias['alias']!r}")
                )
                continue
            known_aliases.add(key)
            steps.append(
                Step(
                    "add_alias",
                    slug,
                    f"{alias['kind']} {alias['alias']!r}",
                    "POST",
                    f"{API_PREFIX}/memes/{slug}/aliases",
                    {"alias": alias["alias"], "kind": alias["kind"]},
                )
            )
    if skipped_placeholders:
        steps.append(
            Step("pending", slug, f"{skipped_placeholders} placeholder alias(es) skipped")
        )
    for link in meme.get("links") or []:
        if _is_placeholder(link.get("mint")):
            steps.append(Step("pending", slug, f"link slot has mint {PLACEHOLDER} - skipped"))
        elif link["mint"] in known_mints:
            steps.append(Step("skip", slug, f"link exists: {link['mint']}"))
        else:
            known_mints.add(link["mint"])
            steps.append(
                Step(
                    "add_link",
                    slug,
                    f"{link['mint']} confidence {link['confidence']} "
                    f"[{link.get('method', 'manual')}] evidence {link['evidence_url']}",
                    "POST",
                    f"{API_PREFIX}/memes/{slug}/links",
                    # Exactly what the endpoint accepts. Never linked_at.
                    _link_body(link),
                )
            )
    return steps


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------


class RequestFailedError(Exception):
    pass


def fetch_existing(client: httpx.Client, slug: str) -> dict[str, Any] | None:
    response = client.get(f"{API_PREFIX}/memes/{slug}")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RequestFailedError(
            f"GET {slug}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()  # type: ignore[no-any-return]


def build_plan(seed: dict[str, Any], client: httpx.Client | None) -> list[Step]:
    """Full plan. With no client (dry-run offline) every meme is planned as new."""
    steps: list[Step] = []
    for meme in seed["memes"]:
        existing = fetch_existing(client, meme["slug"]) if client is not None else None
        steps += plan_meme(meme, existing)
    return steps


def execute(client: httpx.Client, steps: list[Step]) -> list[str]:
    """Send every request step. Returns one outcome line per step."""
    out: list[str] = []
    for step in steps:
        if not step.sends_request:
            out.append(f"{step.action:<11} {step.slug}: {step.detail}")
            continue
        response = client.post(step.path or "", json=step.body)
        if response.status_code == 409:
            out.append(f"exists      {step.slug}: {step.detail} (409, left as is)")
        elif response.status_code not in {200, 201}:
            raise RequestFailedError(
                f"{step.action} {step.slug}: HTTP {response.status_code} {response.text[:300]}"
            )
        else:
            payload = response.json()
            created = payload.get("created", True) if isinstance(payload, dict) else True
            out.append(
                f"{'done' if created else 'exists':<11} "
                f"{step.slug}: {step.action} {step.detail}"
            )
    return out


def render_plan(steps: list[Step]) -> str:
    lines = [f"{s.action:<11} {s.slug}: {s.detail}" for s in steps]
    requests = sum(1 for s in steps if s.sends_request)
    lines.append(f"-- {requests} request(s) planned, {len(steps) - requests} skipped/pending")
    return "\n".join(lines)


def load_seed(path: Path) -> dict[str, Any]:
    try:
        seed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedError([f"cannot read {path}: {exc}"]) from exc
    problems = validate_seed(seed)
    if problems:
        raise SeedError(problems)
    return seed  # type: ignore[no-any-return]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("seed_file", type=Path)
    parser.add_argument(
        "--base-url", default=os.environ.get("MLL_API_BASE_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan; with a token also reads the registry to skip what exists, "
        "but never writes",
    )
    args = parser.parse_args(argv)

    try:
        seed = load_seed(args.seed_file)
    except SeedError as exc:
        print("seed file refused:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    token = os.environ.get(TOKEN_ENV, "")
    if not token and not args.dry_run:
        print(f"{TOKEN_ENV} is not set (an admin bearer token is required)", file=sys.stderr)
        return 2

    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30.0,
        ) as client:
            # Reads are public, so a dry run can see what exists even without a
            # token - but only if the server answers; offline it plans everything as new.
            reachable = True
            if args.dry_run:
                try:
                    client.get(f"{API_PREFIX}/health")
                except httpx.HTTPError:
                    reachable = False
                    print(f"(registry unreachable at {args.base_url} - planning all as new)")
            steps = build_plan(seed, client if reachable else None)
            if args.dry_run:
                print(render_plan(steps))
                return 0
            print(render_plan(steps))
            for line in execute(client, steps):
                print(line)
    except (RequestFailedError, httpx.HTTPError) as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
