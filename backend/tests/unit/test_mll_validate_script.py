"""``scripts/mll_validate_sources.py``: the operator's live-capture tool.

Two promises matter. A dry run sends nothing. And the "live success fixture"
is written only for an HTTP 200 JSON object - a throttle page, an error or a
transport failure must never be committed as GDELT's success shape, because
the live-shape tests would then certify the wrong thing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mll_validate_sources.py"
AT = datetime(2026, 10, 3, 12, 7, tzinfo=UTC)


@pytest.fixture(scope="module")
def script() -> ModuleType:
    # scripts/ is not a package; load by path (dataclasses need sys.modules).
    spec = importlib.util.spec_from_file_location("mll_validate_sources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def exchange(script: ModuleType, status: int | None, body: str) -> object:
    return script.Exchange(
        "GET",
        "https://api.gdeltproject.org/api/v2/doc/doc?query=%22Pepe%22",
        status,
        {"content-type": "application/json", "set-cookie": "secret", "date": "x"},
        body,
        True,
    )


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, "Please limit requests to one every 5 seconds."),
        (200, "[1, 2]"),
        (200, '{"timeline": ['),
        (429, "{}"),
        (503, '{"timeline": []}'),
        (None, ""),
    ],
)
def test_only_a_200_json_object_becomes_the_live_fixture(
    script: ModuleType, status: int | None, body: str
) -> None:
    assert (
        script.live_fixture(exchange(script, status, body), query='"Pepe"', retrieved_at=AT)
        is None
    )


def test_the_fixture_is_verbatim_attributable_and_header_filtered(
    script: ModuleType, tmp_path: Path
) -> None:
    raw = '{"timeline": [{"series": "Article Count", "data": []}]}'
    doc = script.live_fixture(exchange(script, 200, raw), query='"Pepe"', retrieved_at=AT)
    assert doc is not None
    assert doc["body"] == raw and doc["status"] == 200 and doc["synthetic"] is False
    assert doc["query"] == '"Pepe"' and doc["retrieved_at"] == "2026-10-03T12:07:00+00:00"
    assert "set-cookie" not in doc["headers"] and doc["headers"]["content-type"]
    path = script.write_live_fixture(doc, tmp_path)
    assert path.name == "live_timelinevolraw.json"
    assert json.loads(path.read_text()) == doc


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", "<empty body>"),
        ("{}", "<empty object>"),
        ('{"b": 1, "a": 2}', "keys=a,b"),
        ("[1,2,3]", "<JSON list, 3 items>"),
        ("Too many", "<not JSON> 'Too many'"),
    ],
)
def test_top_level_description(script: ModuleType, body: str, expected: str) -> None:
    assert script.top_level(body) == expected


def test_dry_run_sends_nothing_and_writes_nothing(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(["--dry-run", "--fixture-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "0 sent" in out and "dry-run: not sent" in out
    assert "mode=timelinevolraw" in out and "timespan=24h" in out
    assert list(tmp_path.iterdir()) == []
