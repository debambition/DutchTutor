import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.agent.session_memory import SessionStore
from app.main import app

pytestmark = pytest.mark.real_auth


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.api import routes

    store = SessionStore(data_dir=tmp_path)
    monkeypatch.setattr(routes, "_store", store)
    monkeypatch.setattr(auth, "throttle", auth.Throttle())
    return TestClient(app), store


def sign_in(http, user="dave", passphrase="geheim123"):
    return http.post("/api/auth/sign-in", json={"user_id": user, "passphrase": passphrase})


def test_passphrase_is_hashed_and_verified():
    stored = auth.hash_passphrase("geheim123")
    assert "geheim123" not in stored
    assert auth.verify_passphrase("geheim123", stored)
    assert not auth.verify_passphrase("wrong", stored)


def test_tokens_are_signed_and_expire():
    token = auth.issue_token("dave", now=1000)
    assert auth.user_for_token(token, now=1001) == "dave"
    assert auth.user_for_token(token, now=1000 + auth.TOKEN_TTL_SECONDS + 1) is None
    payload, signature = token.split(".")
    assert auth.user_for_token(f"{payload}.{'0' * len(signature)}", now=1001) is None


def test_first_sign_in_claims_the_user_id(client):
    http, store = client
    res = sign_in(http)
    assert res.status_code == 200 and res.json()["created"] is True
    assert store.get_log("dave").passphrase_hash.startswith("scrypt$")
    again = sign_in(http)
    assert again.status_code == 200 and again.json()["created"] is False
    assert sign_in(http, passphrase="wrong-one").status_code == 401


def test_short_passphrase_and_bad_user_id_are_rejected(client):
    http, _ = client
    assert sign_in(http, passphrase="123").status_code == 400
    assert sign_in(http, user="../etc").status_code == 400


def test_learner_routes_require_that_learners_token(client):
    http, _ = client
    dave = sign_in(http).json()["token"]
    erin = sign_in(http, user="erin").json()["token"]

    assert http.get("/api/sessions/dave/progress").status_code == 401
    assert http.get("/api/sessions/dave/progress", headers={"Authorization": f"Bearer {erin}"}).status_code == 401
    assert http.get("/api/sessions/dave/progress", headers={"Authorization": f"Bearer {dave}"}).status_code == 200
    assert http.post("/api/speak", json={"text": "Hallo"}).status_code == 401


def test_passphrase_hash_is_never_returned(client):
    http, _ = client
    token = sign_in(http).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    for path in ("profile", "progress", "conversation"):
        assert "scrypt" not in http.get(f"/api/sessions/dave/{path}", headers=headers).text


def test_repeated_wrong_passphrases_lock_the_user_id(client):
    http, _ = client
    sign_in(http)
    for _ in range(auth.MAX_FAILURES):
        assert sign_in(http, passphrase="wrong-one").status_code == 401
    locked = sign_in(http)  # even the right passphrase is refused while locked
    assert locked.status_code == 429
