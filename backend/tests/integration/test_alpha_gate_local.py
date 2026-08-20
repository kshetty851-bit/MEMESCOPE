"""The local alpha gate, and the four things that must stay true about it.

The fix is small; the risk is not. Opening the gate must be impossible
anywhere but local development, and every test here exists to make one route
to production exposure fail loudly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings

pytestmark = pytest.mark.integration


def build(**overrides) -> Settings:
    """A Settings instance with the minimum production needs, plus overrides."""
    base = {
        "ENVIRONMENT": "production",
        "DEBUG": False,
        "SECRET_KEY": "x" * 48,
        "ALLOWED_HOSTS": ["memescope.example"],
        "REFRESH_COOKIE_SECURE": True,
        "ALPHA_ACCESS_REQUIRED": True,
        "ALPHA_ACCESS_CODE": "123456",
        "ALPHA_ACCESS_COOKIE_SECURE": True,
        # Set explicitly so the production validator fails for the reason a
        # test is asserting rather than for an unrelated value inherited from
        # the developer's own environment file.
        "DEVELOPMENT_BYPASS_AUTH": False,
    }
    base.update(overrides)
    return Settings(**base)


class TestTheGateCannotOpenInProduction:
    def test_production_refuses_to_start_with_the_gate_disabled(self) -> None:
        """The first line of defence: it cannot even boot."""
        with pytest.raises(ValidationError, match="ALPHA_ACCESS_REQUIRED must be true"):
            build(ALPHA_ACCESS_REQUIRED=False)

    def test_production_starts_normally_with_the_gate_enabled(self) -> None:
        assert build().ALPHA_ACCESS_REQUIRED is True

    def test_alpha_gate_open_is_false_in_production_even_if_the_flag_were_false(
        self,
    ) -> None:
        """The second, independent defence.

        Constructed by bypassing validation on purpose: if some future change
        ever let a production process start with the flag off, the property
        must still refuse to open the gate. Two locks, one key each.
        """
        instance = build().model_copy(
            update={"ALPHA_ACCESS_REQUIRED": False, "ENVIRONMENT": "production"}
        )
        assert instance.alpha_gate_open is False

    @pytest.mark.parametrize("environment", ["production", "staging", "test"])
    def test_the_gate_only_opens_in_local(self, environment: str) -> None:
        instance = build().model_copy(
            update={"ALPHA_ACCESS_REQUIRED": False, "ENVIRONMENT": environment}
        )
        assert instance.alpha_gate_open is False

    def test_it_opens_in_local_when_the_flag_is_off(self) -> None:
        instance = build().model_copy(
            update={"ALPHA_ACCESS_REQUIRED": False, "ENVIRONMENT": "local"}
        )
        assert instance.alpha_gate_open is True

    def test_local_with_the_flag_on_keeps_the_gate_shut(self) -> None:
        instance = build().model_copy(
            update={"ALPHA_ACCESS_REQUIRED": True, "ENVIRONMENT": "local"}
        )
        assert instance.alpha_gate_open is False


class TestSessionEndpointFollowsTheGate:
    async def test_gate_enabled_requires_a_real_session(self, client) -> None:
        """The default, and what production always does."""
        body = (await client.get("/api/v1/alpha/session")).json()
        assert body["authenticated"] is False

    async def test_gate_open_locally_reports_access(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of the fix: the session read agrees with the API.

        Patched on the property rather than the raw flag, mirroring how the
        auth-bypass tests do it — the suite runs as `test`, so setting the flag
        alone would correctly change nothing.
        """
        monkeypatch.setattr(type(settings), "alpha_gate_open", property(lambda _: True))
        body = (await client.get("/api/v1/alpha/session")).json()
        assert body["authenticated"] is True
        assert body["expires_at"] is None

    async def test_an_open_gate_invents_no_session_or_expiry(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No cookie is issued and no expiry is claimed: there is no session."""
        monkeypatch.setattr(type(settings), "alpha_gate_open", property(lambda _: True))
        response = await client.get("/api/v1/alpha/session")
        assert "set-cookie" not in {key.lower() for key in response.headers}
        assert response.json()["expires_at"] is None
