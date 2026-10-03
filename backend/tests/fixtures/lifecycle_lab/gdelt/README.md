# GDELT fixtures

**The success-shape fixture (`live_timelinevolraw.json`) has NOT been captured
live yet.** On 2026-10-03 the development container's network policy blocked
`api.gdeltproject.org` (the proxy answered 403; the adapter recorded
`network_error`), so no real GDELT response exists in this repository.

## What is here

| File | Origin | Expected adapter outcome |
|---|---|---|
| `synthetic_empty_body.json` | SYNTHETIC | UNAVAILABLE `no_data_for_window` |
| `synthetic_empty_object.json` | SYNTHETIC | UNAVAILABLE `no_data_for_window` |
| `synthetic_text_rate_limit.json` | SYNTHETIC (wording from documentation/memory) | ERROR `rate_limited`, run stops |
| `synthetic_text_query_error.json` | SYNTHETIC (wording from documentation/memory) | ERROR `gdelt_query_error`, first 200 chars in run detail |
| `synthetic_malformed_json.json` | SYNTHETIC | ERROR `unparseable` |
| `synthetic_http_503.json` | SYNTHETIC | ERROR `http_503` |
| `synthetic_http_429.json` | SYNTHETIC | ERROR `rate_limited`, run stops |

`synthetic_*` files were written by hand to pin the adapter's failure
classification. They are **not** observations of GDELT: the real wording and
content-type of GDELT's plain-text replies are UNVERIFIED.

## Capturing the live fixture

From an environment that can reach `api.gdeltproject.org`:

```bash
docker compose exec -T backend python scripts/mll_validate_sources.py
```

The script makes one GDELT request (24 h span, the scheduler's cap) and writes
`live_timelinevolraw.json` here **only** if the answer is HTTP 200 with a JSON
body. Commit it; `tests/unit/test_mll_gdelt.py::test_live_fixture_*` stops
skipping and checks the real shape (15-minute buckets at the cap, `date` parse,
non-negative values). If that test then fails, the adapter's documented
assumptions were wrong - fix the adapter, do not edit the fixture.

Fixture format (shared by synthetic and live files): `status`, `headers`
(subset), `body` (raw text, verbatim), `url`, `query`, `retrieved_at` (ISO
8601, UTC).
