"""Every `CsvList` setting must accept a comma-separated string.

This trap has now fired SIX times. A `CsvList` field behaves perfectly until
the day someone adds it to a compose file, at which point Pydantic is handed
the bare string `base` instead of a list and refuses it — and because
`get_settings()` runs at import, EVERY service dies, alembic included. On
2026-09-09 that took down a migration mid-deploy.

The failure is structural, not careless: nothing fails until the anchor entry
exists, and the anchor entry is usually added by someone who is not looking at
this validator. So the check is structural too — it asks the model which fields
are CsvList and proves each one survives a CSV string, rather than listing them
by hand and going stale the same way.
"""

from __future__ import annotations

import typing

from app.core import config as cfg


def _csv_fields() -> list[str]:
    """Field names whose annotation is `CsvList`, asked of the model."""
    out = []
    for name, field in cfg.Settings.model_fields.items():
        ann = field.annotation
        if ann is cfg.CsvList or ann == cfg.CsvList:
            out.append(name)
            continue
        # `CsvList` may be an alias for list[str]; fall back to the shape.
        origin = typing.get_origin(ann)
        args = typing.get_args(ann)
        if origin in (list, typing.List) and args and args[0] is str:
            out.append(name)
    return out


class TestEveryCsvListSurvivesAString:
    def test_at_least_one_exists(self) -> None:
        """If this fails the introspection is wrong, not the settings."""
        assert _csv_fields(), "found no CsvList fields — check the detection"

    def test_each_accepts_a_comma_separated_string(self) -> None:
        """The exact shape compose delivers: `NAME=a,b` and `NAME=a`."""
        broken = []
        for name in _csv_fields():
            for raw in ("alpha,beta", "alpha"):
                try:
                    value = cfg.Settings._split_csv(raw)
                except Exception as exc:  # noqa: BLE001
                    broken.append(f"{name} raised {type(exc).__name__} on {raw!r}")
                    continue
                if not isinstance(value, list):
                    broken.append(f"{name} gave {type(value).__name__} on {raw!r}")
        assert not broken, "CsvList fields that reject a CSV string: " + "; ".join(broken)

    def test_the_validator_registers_every_csvlist_field(self) -> None:
        """The real guard. `_split_csv` only runs for fields named in its
        decorator, so a CsvList missing from that list is the bug that has now
        happened six times — silently, until it reaches a compose file."""
        registered: set[str] = set()
        for dec in cfg.Settings.__pydantic_decorators__.field_validators.values():
            if dec.func.__name__ == "_split_csv":
                registered.update(dec.info.fields)
        missing = sorted(set(_csv_fields()) - registered)
        assert not missing, (
            "CsvList fields not registered with _split_csv — each will refuse a "
            "compose string and stop every service booting: " + ", ".join(missing)
        )
