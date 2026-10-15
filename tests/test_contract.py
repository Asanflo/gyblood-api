"""Le client MAUI (Refit) appelle exactement ces routes ; l'API doit toutes les exposer."""

import re

from app.main import app
from tests.helpers import API, login_admin, make_donor, make_patient, make_structure, register

MAUI_OPERATIONS = [
    ("DELETE", "/api/v1/campaigns/{id}/join"),
    ("GET", "/api/v1/admin/accounts"),
    ("GET", "/api/v1/admin/donors/{id}/blood-document"),
    ("GET", "/api/v1/admin/settings/donation-intervals"),
    ("GET", "/api/v1/appointments"),
    ("GET", "/api/v1/appointments/{id}"),
    ("GET", "/api/v1/campaigns"),
    ("GET", "/api/v1/campaigns/{id}"),
    ("GET", "/api/v1/donors/me"),
    ("GET", "/api/v1/donors/me/campaigns"),
    ("GET", "/api/v1/donors/me/donations"),
    ("GET", "/api/v1/donors/me/eligibility"),
    ("GET", "/api/v1/donors/search"),
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/notifications"),
    ("GET", "/api/v1/patients/me"),
    ("GET", "/api/v1/payments/{id}"),
    ("GET", "/api/v1/sponsors/me/fundings"),
    ("GET", "/api/v1/stocks"),
    ("GET", "/api/v1/structures"),
    ("GET", "/api/v1/structures/me"),
    ("GET", "/api/v1/structures/nearest"),
    ("PATCH", "/api/v1/donors/me/availability"),
    ("PATCH", "/api/v1/notifications/{id}/read"),
    ("POST", "/api/v1/admin/accounts/{id}/approve"),
    ("POST", "/api/v1/admin/accounts/{id}/reactivate"),
    ("POST", "/api/v1/admin/accounts/{id}/reject"),
    ("POST", "/api/v1/admin/accounts/{id}/suspend"),
    ("POST", "/api/v1/appointments"),
    ("POST", "/api/v1/appointments/{id}/accept"),
    ("POST", "/api/v1/appointments/{id}/cancel"),
    ("POST", "/api/v1/appointments/{id}/complete"),
    ("POST", "/api/v1/appointments/{id}/decline"),
    ("POST", "/api/v1/appointments/{id}/no-show"),
    ("POST", "/api/v1/appointments/{id}/payments"),
    ("POST", "/api/v1/auth/google"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/campaigns"),
    ("POST", "/api/v1/campaigns/{id}/fundings"),
    ("POST", "/api/v1/campaigns/{id}/join"),
    ("POST", "/api/v1/donors/me/blood-document"),
    ("POST", "/api/v1/me/devices"),
    ("POST", "/api/v1/me/heartbeat"),
    ("PUT", "/api/v1/admin/settings/donation-intervals"),
    ("PUT", "/api/v1/donors/me"),
    ("PUT", "/api/v1/patients/me"),
    ("PUT", "/api/v1/sponsors/me"),
    ("PUT", "/api/v1/structures/me"),
    ("PUT", "/api/v1/structures/me/stocks"),
]


def _norm(path):
    return re.sub(r"\{\w+\}", "{id}", path)


def test_every_route_used_by_the_maui_client_exists():
    available = {(m.upper(), _norm(p)) for p, ops in app.openapi()["paths"].items() for m in ops}
    missing = [op for op in MAUI_OPERATIONS if (op[0], _norm(op[1])) not in available]
    assert missing == []


def test_page_shape_is_spring_style(client):
    admin = login_admin(client)
    page = client.get(f"{API}/admin/accounts", headers=admin.headers, params={"page": 0, "size": 5}).json()
    assert set(page) == {"content", "totalElements", "totalPages", "number", "size"}
    assert page["number"] == 0 and page["size"] == 5 and page["totalElements"] >= 1


def test_enums_are_screaming_snake_case_in_queries_and_bodies(client):
    admin = login_admin(client)
    make_donor(client, admin)
    pending = register(client, "p@test.cm", "DONOR")
    page = client.get(f"{API}/admin/accounts", headers=admin.headers, params={"status": "PENDING", "role": "DONOR"}).json()
    assert [a["id"] for a in page["content"]] == [pending.id]
    assert client.get(f"{API}/admin/accounts", headers=admin.headers, params={"status": "pending"}).status_code == 422


def test_stocks_and_structures(client):
    admin = login_admin(client)
    structure = make_structure(client, admin)
    patient = make_patient(client)
    put = client.put(f"{API}/structures/me/stocks", headers=structure.headers, json={"items": [
        {"bloodGroup": "O", "rhesus": "NEGATIVE", "quantity": 7}, {"bloodGroup": "AB", "rhesus": "POSITIVE", "quantity": 0}]})
    assert put.status_code in (200, 204), put.text
    dup = client.put(f"{API}/structures/me/stocks", headers=structure.headers, json={"items": [
        {"bloodGroup": "O", "rhesus": "NEGATIVE", "quantity": 1}, {"bloodGroup": "O", "rhesus": "NEGATIVE", "quantity": 2}]})
    assert dup.status_code == 422
    stocks = client.get(f"{API}/stocks", headers=patient.headers, params={"bloodGroup": "O", "rhesus": "NEGATIVE"})
    assert stocks.status_code == 200, stocks.text
    assert "O" in stocks.text and "7" in stocks.text
    nearest = client.get(f"{API}/structures/nearest", headers=patient.headers, params={"lat": 4.05, "lon": 9.76})
    assert nearest.status_code == 200 and nearest.json()[0]["id"] == structure.id


def test_campaign_and_funding_flow(client):
    from tests.helpers import future
    admin = login_admin(client)
    structure = make_structure(client, admin)
    donor = make_donor(client, admin)
    sponsor = register(client, "sp@test.cm", "SPONSOR")
    assert client.put(f"{API}/sponsors/me", headers=sponsor.headers, json={"organisation": "Sponsor SA", "contact": "a@b.cm"}).status_code == 200

    body = {"title": "Collecte", "location": "Douala", "startDate": future(1), "endDate": future(3), "targetDonations": 50}
    campaign = client.post(f"{API}/campaigns", headers=structure.headers, json=body)
    assert campaign.status_code == 201, campaign.text
    cid = campaign.json()["id"]
    assert client.post(f"{API}/campaigns", headers=donor.headers, json=body).status_code == 403

    assert client.post(f"{API}/campaigns/{cid}/join", headers=donor.headers).status_code == 204
    joined = client.get(f"{API}/donors/me/campaigns", headers=donor.headers).json()
    assert [c["id"] for c in joined["content"]] == [cid] and joined["content"][0]["joined"] is True
    assert client.delete(f"{API}/campaigns/{cid}/join", headers=donor.headers).status_code == 204

    funded = client.post(f"{API}/campaigns/{cid}/fundings", headers=sponsor.headers, json={"amount": 10000, "operator": "MTN_MOMO", "phoneNumber": "670000001"})
    assert funded.status_code == 201, funded.text
    assert funded.json()["status"] == "SUCCEEDED" and funded.json()["amount"] == 10000
    tiny = client.post(f"{API}/campaigns/{cid}/fundings", headers=sponsor.headers, json={"amount": 100, "operator": "MTN_MOMO", "phoneNumber": "670000001"})
    assert tiny.status_code in (409, 422)
    mine = client.get(f"{API}/sponsors/me/fundings", headers=sponsor.headers).json()
    assert mine["content"][0]["campaignTitle"] == "Collecte"
    assert client.get(f"{API}/campaigns/{cid}", headers=donor.headers).json()["fundsReceived"] == 10000


def test_roles_are_enforced(client):
    admin = login_admin(client)
    patient = make_patient(client)
    structure = make_structure(client, admin)
    for method, url, actor in [
        ("get", "/admin/accounts", patient),
        ("get", "/admin/accounts", structure),
        ("get", "/donors/me", patient),
        ("put", "/structures/me/stocks", patient),
        ("get", "/donors/search", structure),
        ("post", "/appointments", structure),
    ]:
        assert getattr(client, method)(API + url, headers=actor.headers).status_code == 403, (method, url)
    assert client.get(API + "/admin/accounts").status_code == 401


def test_admin_reject_and_donation_intervals(client):
    admin = login_admin(client)
    donor = register(client, "rej@test.cm", "DONOR")
    rejected = client.post(f"{API}/admin/accounts/{donor.id}/reject", headers=admin.headers, json={"reason": "Document illisible"})
    assert rejected.status_code == 204, rejected.text
    me = client.get(f"{API}/me", headers=donor.headers).json()
    assert me["status"] == "REJECTED" and me["rejectionReason"] == "Document illisible"

    intervals = client.get(f"{API}/admin/settings/donation-intervals", headers=admin.headers)
    assert intervals.status_code == 200 and {i["minDays"] for i in intervals.json()} == {56, 84}
