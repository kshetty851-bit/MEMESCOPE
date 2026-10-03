"""The seeding script is the only door through which curated memes and links
enter the Lab by hand, so its refusals are the Lab's data-quality floor.

The properties that matter, and why:

* a link never rests on a ticker or a name - thousands of tokens share one, and
  a false link contaminates every feature derived from it;
* a link is never dated by the client - a link dated before a pump is exactly
  the look-ahead the Lab exists to exclude;
* a re-run changes nothing - seeding is repeated by hand, mid-curation;
* the example file carries no mint address - none may be copied from memory.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.unit

#: Captured before any test patches ``httpx.Client`` (the script imports the same module).
_RealClient = httpx.Client

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "mll_seed.py"
EXAMPLE = BACKEND.parent / "docs" / "lifecycle_lab_seed.example.json"

_spec = importlib.util.spec_from_file_location("mll_seed", SCRIPT)
assert _spec and _spec.loader
seed_mod: Any = importlib.util.module_from_spec(_spec)
sys.modules["mll_seed"] = seed_mod
_spec.loader.exec_module(seed_mod)

#: A syntactically valid base58 address that is nobody's token (test fixture only).
FAKE_MINT = "So11111111111111111111111111111111111111112"
OTHER_MINT = "Vote111111111111111111111111111111111111111"


def _link(**over: Any) -> dict[str, Any]:
    link: dict[str, Any] = {
        "mint": FAKE_MINT,
        "method": "manual",
        "confidence": "0.9",
        "evidence_url": "https://example.org/proof",
        "evidence_note": "Token site links the meme's canonical account; account links back.",
    }
    link.update(over)
    return {k: v for k, v in link.items() if v is not None}


def _seed(*links: dict[str, Any], slug: str = "doge") -> dict[str, Any]:
    return {
        "memes": [
            {
                "slug": slug,
                "display_name": "Doge",
                "aliases": [{"alias": "Doge", "kind": "name"}],
                "links": list(links),
            }
        ]
    }


# --------------------------------------------------------------------------
# The example file
# --------------------------------------------------------------------------


def _example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text())  # type: ignore[no-any-return]


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_the_example_seed_is_valid_and_has_fifteen_memes() -> None:
    seed = _example()
    assert seed_mod.validate_seed(seed) == []
    assert len(seed["memes"]) == 15
    assert all(m["wikipedia_title"] and m["gdelt_query"] for m in seed["memes"])


def test_the_example_seed_contains_no_mint_address() -> None:
    """Mints are never typed from memory; the example is all placeholders."""
    offenders = [s for s in _strings(_example()) if seed_mod.MINT_RE.match(s)]
    assert offenders == []


def test_every_example_link_slot_is_an_unverified_placeholder() -> None:
    for meme in _example()["memes"]:
        assert meme["links"], meme["slug"]
        assert all(link["mint"] == seed_mod.PLACEHOLDER for link in meme["links"])


def test_planning_the_example_issues_only_meme_creation_requests() -> None:
    steps = seed_mod.build_plan(_example(), None)
    requests = [s for s in steps if s.sends_request]
    assert {s.action for s in requests} == {"create_meme"}
    assert len(requests) == 15
    # Placeholder aliases and link slots are reported, never sent.
    assert any(s.action == "pending" for s in steps)
    assert not any(seed_mod.PLACEHOLDER in json.dumps(s.body) for s in requests)


# --------------------------------------------------------------------------
# Link refusals
# --------------------------------------------------------------------------


def test_a_well_evidenced_manual_link_is_accepted() -> None:
    assert seed_mod.validate_seed(_seed(_link())) == []


@pytest.mark.parametrize(
    "link",
    [
        _link(method="website_match", matched="https://token.example/", evidence_note=None),
        _link(method="social_link_match", matched="@canonical_account", evidence_note=None),
    ],
)
def test_website_and_social_matches_are_accepted_with_the_matched_value(
    link: dict[str, Any],
) -> None:
    assert seed_mod.validate_seed(_seed(link)) == []


@pytest.mark.parametrize(
    ("link", "fragment"),
    [
        (_link(evidence_url=None), "evidence_url"),
        (_link(evidence_url="TO_VERIFY"), "evidence_url"),
        (_link(evidence_url="not a url"), "evidence_url"),
        (_link(evidence_url=""), "evidence_url"),
        (_link(method="exact_symbol", evidence_url=None), "never sufficient"),
        (_link(method="exact_name"), "never sufficient"),
        (_link(method="alias_match"), "never sufficient"),
        (_link(evidence_basis="ticker"), "not evidence"),
        (_link(evidence_basis="symbol"), "not evidence"),
        (_link(evidence_note=None), "evidence_note"),
        (_link(method="website_match", matched=None, evidence_note=None), "matched"),
        (
            _link(method="social_link_match", matched="TO_VERIFY", evidence_note=None),
            "matched",
        ),
        (_link(method="telepathy"), "unknown method"),
        (_link(confidence="1.5"), "confidence"),
        (_link(confidence="0"), "confidence"),
        (_link(confidence="TO_VERIFY"), "confidence"),
        (_link(mint="not-a-mint"), "mint"),
        (_link(linked_at="2026-01-01T00:00:00Z"), "linked_at"),
        (_link(surprise=True), "unknown key"),
    ],
)
def test_an_unevidenced_or_text_only_link_is_refused(
    link: dict[str, Any], fragment: str
) -> None:
    problems = seed_mod.validate_seed(_seed(link))
    assert any(fragment in p for p in problems), problems


def test_a_ticker_only_link_is_refused_even_when_it_names_manual() -> None:
    """The caller cannot launder a symbol match by calling it manual."""
    problems = seed_mod.validate_seed(
        _seed(_link(evidence_url=None, evidence_note=None, evidence_basis="ticker"))
    )
    assert len(problems) >= 2


def test_every_defect_is_reported_in_one_pass() -> None:
    bad = _seed(_link(evidence_url=None), _link(mint=OTHER_MINT, method="exact_symbol"))
    bad["memes"].append({"slug": "Bad Slug", "display_name": "x"})
    assert len(seed_mod.validate_seed(bad)) >= 3


def test_a_placeholder_mint_is_pending_not_an_error() -> None:
    seed = _seed({"mint": "TO_VERIFY", "evidence_url": "TO_VERIFY", "confidence": "TO_VERIFY"})
    assert seed_mod.validate_seed(seed) == []
    steps = seed_mod.build_plan(seed, None)
    assert [s.action for s in steps if s.sends_request] == ["create_meme"]
    assert any(s.action == "pending" and "link slot" in s.detail for s in steps)


@pytest.mark.parametrize("seed", [[], {}, {"memes": "x"}, {"memes": [1]}])
def test_malformed_documents_are_refused(seed: Any) -> None:
    assert seed_mod.validate_seed(seed)


def test_duplicate_slugs_and_bad_alias_kinds_are_refused() -> None:
    dup = _seed()
    dup["memes"].append(dict(dup["memes"][0]))
    assert any("duplicate" in p for p in seed_mod.validate_seed(dup))
    bad = _seed()
    bad["memes"][0]["aliases"] = [{"alias": "x", "kind": "ticker"}]
    assert any("kind" in p for p in seed_mod.validate_seed(bad))


# --------------------------------------------------------------------------
# What is sent
# --------------------------------------------------------------------------


def test_a_link_request_carries_its_evidence_and_never_a_date() -> None:
    existing = {"aliases": [{"alias": "Doge", "kind": "name"}], "links": []}
    link = _link()
    steps = seed_mod.plan_meme(_seed(link)["memes"][0], existing)
    [link_step] = [s for s in steps if s.action == "add_link"]
    assert link_step.body == {
        "mint": FAKE_MINT,
        "confidence": "0.9",
        "method": "manual",
        "evidence_url": link["evidence_url"],
        "evidence_note": link["evidence_note"],
    }
    assert "linked_at" not in json.dumps([s.body for s in steps])


def test_a_website_match_link_sends_the_matched_value_as_its_note() -> None:
    link = _link(method="website_match", matched="doge.example", evidence_note=None)
    [step] = [
        s
        for s in seed_mod.plan_meme(_seed(link)["memes"][0], {"aliases": [], "links": []})
        if s.action == "add_link"
    ]
    assert step.body["method"] == "website_match"
    assert step.body["evidence_note"] == "matched: doge.example"


def test_existing_aliases_and_links_are_skipped() -> None:
    existing = {
        "aliases": [{"alias": "  DOGE ", "kind": "name"}],
        "links": [{"mint": FAKE_MINT}],
    }
    steps = seed_mod.plan_meme(_seed(_link())["memes"][0], existing)
    assert not [s for s in steps if s.sends_request]


def test_a_new_meme_is_created_with_its_aliases_in_one_request() -> None:
    [create] = [s for s in seed_mod.plan_meme(_seed()["memes"][0], None) if s.sends_request]
    assert create.path == "/api/v1/lifecycle-lab/memes"
    assert create.body["aliases"] == [{"alias": "Doge", "kind": "name"}]


# --------------------------------------------------------------------------
# Against a stand-in server: idempotency and dry-run
# --------------------------------------------------------------------------


class FakeLab:
    """The slice of the admin API the script uses, with the real idempotency keys."""

    def __init__(self) -> None:
        self.memes: dict[str, dict[str, Any]] = {}
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.auth: set[str | None] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth.add(request.headers.get("authorization"))
        path = request.url.path
        prefix = "/api/v1/lifecycle-lab"
        if request.method == "GET" and path == f"{prefix}/health":
            return httpx.Response(200, json={"sources": []})
        if request.method == "GET" and path.startswith(f"{prefix}/memes/"):
            meme = self.memes.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=meme) if meme else httpx.Response(404, json={})
        body = json.loads(request.content or b"{}")
        self.posts.append((path, body))
        if path == f"{prefix}/memes":
            self.memes[body["slug"]] = {"aliases": body["aliases"], "links": []}
            return httpx.Response(201, json={"slug": body["slug"]})
        slug = path.split("/")[-2]
        if path.endswith("/aliases"):
            self.memes[slug]["aliases"].append(body)
            return httpx.Response(201, json={**body, "created": True})
        if path.endswith("/links"):
            self.memes[slug]["links"].append({"mint": body["mint"]})
            return httpx.Response(201, json={**body, "created": True})
        return httpx.Response(404, json={})


def _client(lab: FakeLab, token: str = "t") -> httpx.Client:  # noqa: S107
    return _RealClient(
        transport=httpx.MockTransport(lab),
        base_url="http://lab.test",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_a_rerun_changes_nothing() -> None:
    """Creating the meme, then its link, then re-running: the third pass is a no-op.
    (The link needs the meme to exist, so it lands on the second pass.)"""
    lab = FakeLab()
    seed = _seed(_link())
    with _client(lab) as client:
        seed_mod.execute(client, seed_mod.build_plan(seed, client))
        seed_mod.execute(client, seed_mod.build_plan(seed, client))
        settled = len(lab.posts)
        seed_mod.execute(client, seed_mod.build_plan(seed, client))
    assert len(lab.posts) == settled
    assert [p for p, _ in lab.posts] == [
        "/api/v1/lifecycle-lab/memes",
        "/api/v1/lifecycle-lab/memes/doge/links",
    ]


def test_a_new_alias_on_an_existing_meme_goes_through_the_alias_endpoint() -> None:
    lab = FakeLab()
    seed = _seed()
    with _client(lab) as client:
        seed_mod.execute(client, seed_mod.build_plan(seed, client))
        seed["memes"][0]["aliases"].append({"alias": "Much Wow", "kind": "phrase"})
        seed_mod.execute(client, seed_mod.build_plan(seed, client))
    assert lab.posts[-1] == (
        "/api/v1/lifecycle-lab/memes/doge/aliases",
        {"alias": "Much Wow", "kind": "phrase"},
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, lab: FakeLab) -> None:
    def factory(**kwargs: Any) -> httpx.Client:
        return _RealClient(
            transport=httpx.MockTransport(lab),
            base_url=kwargs["base_url"],
            headers=kwargs.get("headers"),
        )

    monkeypatch.setattr(seed_mod.httpx, "Client", factory)


def test_dry_run_writes_nothing_and_needs_no_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lab = FakeLab()
    _patch_client(monkeypatch, lab)
    monkeypatch.delenv("MLL_ADMIN_TOKEN", raising=False)
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(_seed(_link())))

    assert seed_mod.main(["--dry-run", str(path)]) == 0

    assert lab.posts == []
    assert "create_meme" in capsys.readouterr().out


def test_a_live_run_requires_a_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lab = FakeLab()
    _patch_client(monkeypatch, lab)
    monkeypatch.delenv("MLL_ADMIN_TOKEN", raising=False)
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(_seed()))

    assert seed_mod.main([str(path)]) == 2

    assert lab.posts == []
    assert "MLL_ADMIN_TOKEN" in capsys.readouterr().err


def test_a_live_run_sends_the_bearer_token_and_never_prints_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lab = FakeLab()
    _patch_client(monkeypatch, lab)
    monkeypatch.setenv("MLL_ADMIN_TOKEN", "s3cret-token")
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(_seed()))

    assert seed_mod.main(["--base-url", "http://lab.test", str(path)]) == 0

    assert "Bearer s3cret-token" in lab.auth
    captured = capsys.readouterr()
    assert "s3cret-token" not in captured.out + captured.err


def test_an_invalid_seed_aborts_before_any_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lab = FakeLab()
    _patch_client(monkeypatch, lab)
    monkeypatch.setenv("MLL_ADMIN_TOKEN", "t")
    path = tmp_path / "seed.json"
    # A valid meme first, then an unevidenced link: nothing at all may be sent.
    path.write_text(json.dumps(_seed(_link(evidence_url=None))))

    assert seed_mod.main([str(path)]) == 2

    assert lab.posts == []
    assert "evidence_url" in capsys.readouterr().err


def test_a_server_error_is_a_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={})
        return httpx.Response(403, json={"error": "admin only"})

    monkeypatch.setattr(
        seed_mod.httpx,
        "Client",
        lambda **kw: _RealClient(
            transport=httpx.MockTransport(failing), base_url=kw["base_url"]
        ),
    )
    monkeypatch.setenv("MLL_ADMIN_TOKEN", "t")
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(_seed()))

    assert seed_mod.main([str(path)]) == 1
