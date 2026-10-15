from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt

from app.config import settings
from app.security import pkce_challenge
from app.services import google
from tests.helpers import API, PASSWORD, register

VERIFIER = "v" * 43


def test_register_patient_is_validated_and_json_is_camel_case(client):
    response = client.post(f"{API}/auth/register", json={"email": "Ana@Test.cm", "password": PASSWORD, "role": "PATIENT"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"accessToken", "refreshToken", "user"}
    assert body["user"] == {
        "id": body["user"]["id"],
        "email": "ana@test.cm",
        "role": "PATIENT",
        "status": "VALIDATED",
        "displayName": None,
        "rejectionReason": None,
    }


def test_register_donor_and_structure_wait_for_validation(client):
    assert register(client, "d@test.cm", "DONOR").role == "DONOR"
    me = client.get(f"{API}/me", headers=register(client, "h@test.cm", "STRUCTURE").headers).json()
    assert me["status"] == "PENDING"


def test_cannot_register_as_admin(client):
    response = client.post(f"{API}/auth/register", json={"email": "x@test.cm", "password": PASSWORD, "role": "ADMIN"})
    assert response.status_code == 403
    assert response.json()["code"] == "ROLE_NOT_ALLOWED"


def test_duplicate_email_is_refused_with_standard_error_body(client):
    register(client, "dup@test.cm", "PATIENT")
    response = client.post(f"{API}/auth/register", json={"email": "DUP@test.cm", "password": PASSWORD, "role": "PATIENT"})

    assert response.status_code == 409
    assert response.json() == {"code": "EMAIL_TAKEN", "message": "Cette adresse email est déjà utilisée.", "details": None}


def test_validation_error_uses_the_same_body_shape(client):
    response = client.post(f"{API}/auth/register", json={"email": "pas-un-email", "password": "court", "role": "PATIENT"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["message"] == "Les informations saisies sont invalides."
    assert {"email", "password"} <= set(body["details"])


def test_login_and_wrong_credentials_look_identical(client):
    register(client, "log@test.cm", "PATIENT")

    ok = client.post(f"{API}/auth/login", json={"email": "LOG@test.cm", "password": PASSWORD})
    wrong_password = client.post(f"{API}/auth/login", json={"email": "log@test.cm", "password": "mauvais-mot-de-passe"})
    unknown = client.post(f"{API}/auth/login", json={"email": "inconnu@test.cm", "password": PASSWORD})

    assert ok.status_code == 200
    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json() == unknown.json()


def test_protected_route_needs_a_valid_token(client):
    assert client.get(f"{API}/me").status_code == 401

    expired = jwt.encode(
        {"sub": "1", "typ": "access", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = client.get(f"{API}/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


def test_state_token_cannot_be_used_as_access_token(client):
    from app.security import encode_oauth_state

    state = encode_oauth_state("PATIENT", "c" * 43)
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {state}"}).status_code == 401


def test_refresh_rotates_and_reuse_revokes_every_session(client):
    actor = register(client, "rot@test.cm", "PATIENT")

    first = client.post(f"{API}/auth/refresh", json={"refreshToken": actor.refresh_token})
    assert first.status_code == 200
    new_refresh = first.json()["refreshToken"]
    assert new_refresh != actor.refresh_token

    replay = client.post(f"{API}/auth/refresh", json={"refreshToken": actor.refresh_token})
    assert replay.status_code == 401
    assert replay.json()["code"] == "TOKEN_REUSED"

    # Le jeton légitime est révoqué lui aussi : on ne sait pas qui détient quoi.
    assert client.post(f"{API}/auth/refresh", json={"refreshToken": new_refresh}).status_code == 401


def test_logout_revokes_the_refresh_token(client):
    actor = register(client, "out@test.cm", "PATIENT")

    assert client.post(f"{API}/auth/logout", json={"refreshToken": actor.refresh_token}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refreshToken": actor.refresh_token}).status_code == 401


def test_suspended_account_can_still_read_its_status_but_nothing_else(client):
    from tests.helpers import login_admin

    admin = login_admin(client)
    actor = register(client, "sus@test.cm", "PATIENT")
    assert client.post(f"{API}/admin/accounts/{actor.id}/suspend", headers=admin.headers).status_code == 204

    me = client.get(f"{API}/me", headers=actor.headers)
    assert me.status_code == 200 and me.json()["status"] == "SUSPENDED"
    blocked = client.get(f"{API}/patients/me", headers=actor.headers)
    assert blocked.status_code == 403 and blocked.json()["code"] == "ACCOUNT_SUSPENDED"


# ---------------------------------------------------------------- Google (les appels à Google sont simulés)


def _fake_google(monkeypatch, *, sub="g-123", email="gina@test.cm", verified=True):
    monkeypatch.setattr(google, "exchange_code", lambda code: "fake-id-token")
    monkeypatch.setattr(
        google,
        "verify_id_token",
        lambda token: {"sub": sub, "email": email, "email_verified": verified, "name": "Gina"},
    )


def _start(client, role="DONOR"):
    response = client.get(
        "/oauth2/authorization/google",
        params={"code_challenge": pkce_challenge(VERIFIER), "role": role},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0], response


def test_google_flow_with_pkce_end_to_end(client, monkeypatch):
    _fake_google(monkeypatch)
    state, start = _start(client)
    assert start.headers["location"].startswith("https://accounts.google.com/")
    assert "redirect_uri=http%3A%2F%2Ftestserver%2Foauth2%2Fcallback%2Fgoogle" in start.headers["location"]

    callback = client.get("/oauth2/callback/google", params={"code": "abc", "state": state}, follow_redirects=False)
    assert callback.status_code == 302
    target = urlparse(callback.headers["location"])
    assert f"{target.scheme}://{target.netloc}" == "gyblood://auth"
    query = parse_qs(target.query)
    assert set(query) == {"code"}  # jamais de jeton dans l'URL

    exchange = client.post(f"{API}/auth/google/exchange", json={"code": query["code"][0], "codeVerifier": VERIFIER})
    assert exchange.status_code == 200
    user = exchange.json()["user"]
    assert (user["email"], user["role"], user["status"], user["displayName"]) == ("gina@test.cm", "DONOR", "PENDING", "Gina")

    reused = client.post(f"{API}/auth/google/exchange", json={"code": query["code"][0], "codeVerifier": VERIFIER})
    assert reused.status_code == 400 and reused.json()["code"] == "INVALID_CODE"


def test_google_code_is_useless_without_the_right_verifier(client, monkeypatch):
    _fake_google(monkeypatch)
    state, _ = _start(client)
    query = parse_qs(urlparse(client.get("/oauth2/callback/google", params={"code": "abc", "state": state}, follow_redirects=False).headers["location"]).query)

    stolen = client.post(f"{API}/auth/google/exchange", json={"code": query["code"][0], "codeVerifier": "x" * 43})
    assert stolen.status_code == 400
    # Le code est brûlé par la tentative : l'application légitime doit recommencer.
    legit = client.post(f"{API}/auth/google/exchange", json={"code": query["code"][0], "codeVerifier": VERIFIER})
    assert legit.status_code == 400


def test_google_does_not_take_over_an_existing_password_account(client, monkeypatch):
    register(client, "gina@test.cm", "PATIENT")
    _fake_google(monkeypatch, email="gina@test.cm")
    state, _ = _start(client, "PATIENT")

    callback = client.get("/oauth2/callback/google", params={"code": "abc", "state": state}, follow_redirects=False)

    assert parse_qs(urlparse(callback.headers["location"]).query) == {"error": ["account_exists"]}


def test_google_refuses_unverified_email_and_bad_state(client, monkeypatch):
    _fake_google(monkeypatch, verified=False)
    state, _ = _start(client)
    unverified = client.get("/oauth2/callback/google", params={"code": "abc", "state": state}, follow_redirects=False)
    assert parse_qs(urlparse(unverified.headers["location"]).query) == {"error": ["google_email_unverified"]}

    forged = client.get("/oauth2/callback/google", params={"code": "abc", "state": "forge"}, follow_redirects=False)
    assert parse_qs(urlparse(forged.headers["location"]).query) == {"error": ["invalid_state"]}

    denied = client.get("/oauth2/callback/google", params={"error": "access_denied"}, follow_redirects=False)
    assert parse_qs(urlparse(denied.headers["location"]).query) == {"error": ["access_denied"]}


def test_google_start_requires_a_pkce_challenge_and_configuration(client, cfg):
    assert client.get("/oauth2/authorization/google", follow_redirects=False).status_code == 422

    cfg.google_client_id = None
    response = client.get(
        "/oauth2/authorization/google", params={"code_challenge": pkce_challenge(VERIFIER)}, follow_redirects=False
    )
    assert response.status_code == 503 and response.json()["code"] == "GOOGLE_NOT_CONFIGURED"
