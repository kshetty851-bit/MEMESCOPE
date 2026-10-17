from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.security import hash_password
from app.real_wallet import family, fivebags_api


def _client(monkeypatch, password="right-one"):  # noqa: S107 - test value
    monkeypatch.setattr(settings, "FIVEBAGS_PASSWORD_HASH", SecretStr(hash_password(password)))
    monkeypatch.setattr(family, "THROTTLE", family.Throttle())
    app = FastAPI()
    app.include_router(fivebags_api.router)

    @app.get("/check", dependencies=[fivebags_api.Depends(fivebags_api._signed_in)])
    async def check():
        return {"in": True}
    return TestClient(app, base_url="https://testserver")


def test_right_password_opens_and_wrong_ones_lock_out(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/check").status_code == 401
    assert c.post("/fivebags/unlock", json={"password": "nope"}).status_code == 401
    r = c.post("/fivebags/unlock", json={"password": "right-one"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    c.cookies.set("fivebags", r.cookies["fivebags"])
    assert c.get("/check").status_code == 200
    for _ in range(5):
        c.post("/fivebags/unlock", json={"password": "nope"})
    assert c.post("/fivebags/unlock", json={"password": "right-one"}).status_code == 429


def test_no_hash_means_nobody_gets_in(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(settings, "FIVEBAGS_PASSWORD_HASH", SecretStr(""))
    assert c.post("/fivebags/unlock", json={"password": ""}).status_code == 401
