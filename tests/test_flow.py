import hashlib
import hmac
import json

from app.config import settings
from tests.helpers import (
    API, PDF, approve, future, go_online, login_admin, make_donor, make_patient, make_structure, register,
    request_donation,
)


def world(client):
    admin = login_admin(client)
    structure = make_structure(client, admin)
    donor = make_donor(client, admin)
    go_online(client, donor)
    patient = make_patient(client)
    return admin, structure, donor, patient


def search(client, patient, group="A", rhesus="POSITIVE", **extra):
    params = {"bloodGroup": group, "rhesus": rhesus, "lat": 4.0511, "lon": 9.7679, "radiusKm": 10, **extra}
    response = client.get(f"{API}/donors/search", headers=patient.headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def sign(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    signature = hmac.new(settings.payment_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Signature": signature, "Content-Type": "application/json"}


def test_full_donation_flow(client):
    admin, structure, donor, patient = world(client)

    found = search(client, patient)
    assert [d["id"] for d in found] == [donor.id]
    assert set(found[0]) == {"id", "fullName", "bloodGroup", "rhesus", "latitude", "longitude", "distanceKm"}
    assert found[0]["bloodGroup"] == "O" and found[0]["rhesus"] == "NEGATIVE"

    created = request_donation(client, patient, donor, structure)
    assert created.status_code == 201
    appointment = created.json()
    assert appointment["status"] == "REQUESTED" and appointment["hospitalFee"] == 5000
    aid = appointment["id"]

    # Le donneur est prévenu, sans connaître l'identité du patient.
    notifications = client.get(f"{API}/notifications", headers=donor.headers).json()
    request_note = [n for n in notifications["content"] if "A+" in n["message"]]
    assert len(request_note) == 1 and "patient@test.cm" not in request_note[0]["message"]

    # Pas de paiement avant l'acceptation.
    early = client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000001"})
    assert early.status_code == 409

    accepted = client.post(f"{API}/appointments/{aid}/accept", headers=donor.headers)
    assert accepted.status_code == 200 and accepted.json()["status"] == "ACCEPTED"
    assert search(client, patient) == []  # donneur engagé : plus proposé

    paid = client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000001"})
    assert paid.status_code == 201
    payment = paid.json()
    assert payment["status"] == "SUCCEEDED" and payment["amount"] == 5000 and payment["platformFee"] == 250
    assert client.get(f"{API}/appointments/{aid}", headers=patient.headers).json()["status"] == "PAID"

    done = client.post(f"{API}/appointments/{aid}/complete", headers=structure.headers)
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"

    donations = client.get(f"{API}/donors/me/donations", headers=donor.headers).json()
    assert len(donations) == 1 or donations.get("totalElements") == 1
    eligibility = client.get(f"{API}/donors/me/eligibility", headers=donor.headers).json()
    assert eligibility["canDonate"] is False and eligibility["nextDonationDate"]

    # Hors délai de repos : ni dans la recherche, ni réservable.
    go_online(client, donor)
    assert search(client, patient) == []
    again = request_donation(client, patient, donor, structure)
    assert again.status_code == 409 and again.json()["code"] == "DONOR_NOT_ELIGIBLE"


def test_search_filters(client):
    admin, structure, donor, patient = world(client)

    assert search(client, patient, group="AB", rhesus="POSITIVE")  # O- donne à tous
    assert search(client, patient, radiusKm=0.5) == []
    # Un patient O- ne peut recevoir que d'un donneur O-.
    other = make_donor(client, admin, email="b@test.cm", group="A", rhesus="POSITIVE")
    go_online(client, other)
    assert [d["id"] for d in search(client, patient, group="O", rhesus="NEGATIVE")] == [donor.id]

    client.patch(f"{API}/donors/me/availability", headers=donor.headers, json={"isAvailable": False, "shareLocation": True})
    assert search(client, patient) == [d for d in search(client, patient) if d["id"] == other.id]
    client.patch(f"{API}/donors/me/availability", headers=donor.headers, json={"isAvailable": True, "shareLocation": False})
    assert donor.id not in [d["id"] for d in search(client, patient)]


def test_search_hides_stale_presence(client):
    from datetime import timedelta
    from app.database import SessionLocal
    from app.models import DonorProfile
    from app.utils import utcnow

    admin, structure, donor, patient = world(client)
    with SessionLocal() as db:
        db.get(DonorProfile, donor.id).last_seen_at = utcnow() - timedelta(minutes=30)
        db.commit()
    assert search(client, patient) == []


def test_unvalidated_donor_never_appears(client):
    admin = login_admin(client)
    donor = register(client, "pending@test.cm", "DONOR")
    patient = make_patient(client)
    assert search(client, patient) == []
    # Un compte non validé est refusé sur les routes métier.
    assert client.patch(f"{API}/donors/me/availability", headers=donor.headers, json={"isAvailable": True, "shareLocation": True}).status_code == 403


def test_approval_requires_complete_profile(client):
    admin = login_admin(client)
    donor = register(client, "inc@test.cm", "DONOR")
    response = client.post(f"{API}/admin/accounts/{donor.id}/approve", headers=admin.headers)
    assert response.status_code == 409


def test_decline_and_duplicate_request(client):
    admin, structure, donor, patient = world(client)
    first = request_donation(client, patient, donor, structure).json()
    assert request_donation(client, patient, donor, structure).status_code == 409
    declined = client.post(f"{API}/appointments/{first['id']}/decline", headers=donor.headers)
    assert declined.json()["status"] == "CANCELLED"
    assert request_donation(client, patient, donor, structure).status_code == 201


def test_incompatible_and_past_requests_are_refused(client):
    admin, structure, donor, patient = world(client)
    ab_donor = make_donor(client, admin, email="ab@test.cm", group="AB", rhesus="POSITIVE")
    go_online(client, ab_donor)
    bad = request_donation(client, patient, ab_donor, structure)
    assert bad.status_code == 409 and bad.json()["code"] == "INCOMPATIBLE_BLOOD"
    past = client.post(f"{API}/appointments", headers=patient.headers, json={"donorId": donor.id, "structureId": structure.id, "scheduledAt": future(-1)})
    assert past.status_code == 422


def test_appointments_are_private_to_their_parties(client):
    admin, structure, donor, patient = world(client)
    aid = request_donation(client, patient, donor, structure).json()["id"]
    stranger = make_patient(client, email="autre@test.cm")
    assert client.get(f"{API}/appointments/{aid}", headers=stranger.headers).status_code == 404
    assert client.post(f"{API}/appointments/{aid}/accept", headers=patient.headers).status_code == 403
    other_structure = make_structure(client, admin, email="h2@test.cm", name="Autre")
    assert client.post(f"{API}/appointments/{aid}/complete", headers=other_structure.headers).status_code == 404
    page = client.get(f"{API}/appointments", headers=stranger.headers).json()
    assert page["content"] == [] and page["totalElements"] == 0


def test_cancel_after_payment_flags_refund_and_alerts_admin(client):
    admin, structure, donor, patient = world(client)
    aid = request_donation(client, patient, donor, structure).json()["id"]
    client.post(f"{API}/appointments/{aid}/accept", headers=donor.headers)
    client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "ORANGE_MONEY", "phoneNumber": "690000001"})

    cancelled = client.post(f"{API}/appointments/{aid}/cancel", headers=patient.headers)
    assert cancelled.json()["status"] == "CANCELLED"
    admin_notes = client.get(f"{API}/notifications", headers=admin.headers).json()["content"]
    assert any("rembours" in n["title"].lower() or "rembours" in n["message"].lower() for n in admin_notes)
    assert client.post(f"{API}/appointments/{aid}/cancel", headers=patient.headers).status_code == 409


def test_failed_payment_leaves_appointment_accepted_and_allows_retry(client):
    admin, structure, donor, patient = world(client)
    aid = request_donation(client, patient, donor, structure).json()["id"]
    client.post(f"{API}/appointments/{aid}/accept", headers=donor.headers)

    failed = client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000000"})
    assert failed.status_code == 201 and failed.json()["status"] == "FAILED"
    assert client.get(f"{API}/appointments/{aid}", headers=patient.headers).json()["status"] == "ACCEPTED"
    retry = client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000001"})
    assert retry.json()["status"] == "SUCCEEDED"


def test_webhook_signature_and_idempotence(client, cfg):
    cfg.sandbox_auto_confirm = False
    admin, structure, donor, patient = world(client)
    aid = request_donation(client, patient, donor, structure).json()["id"]
    client.post(f"{API}/appointments/{aid}/accept", headers=donor.headers)
    payment = client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000001"}).json()
    assert payment["status"] == "PENDING"
    assert client.post(f"{API}/appointments/{aid}/payments", headers=patient.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000001"}).status_code == 409

    raw, headers = sign({"reference": payment["reference"], "status": "SUCCEEDED"})
    assert client.post(f"{API}/payments/webhook", content=raw).status_code == 401
    assert client.post(f"{API}/payments/webhook", content=raw, headers={**headers, "X-Signature": "00" * 32}).status_code == 401
    assert client.get(f"{API}/appointments/{aid}", headers=patient.headers).json()["status"] == "ACCEPTED"

    assert client.post(f"{API}/payments/webhook", content=raw, headers=headers).status_code == 200
    assert client.post(f"{API}/payments/webhook", content=raw, headers=headers).status_code == 200  # rejouée
    assert client.get(f"{API}/appointments/{aid}", headers=patient.headers).json()["status"] == "PAID"

    # Un échec tardif ne défait pas un paiement déjà confirmé.
    late, late_headers = sign({"reference": payment["reference"], "status": "FAILED"})
    client.post(f"{API}/payments/webhook", content=late, headers=late_headers)
    assert client.get(f"{API}/payments/{payment['id']}", headers=patient.headers).json()["status"] == "SUCCEEDED"

    unknown, unknown_headers = sign({"reference": "inconnue", "status": "SUCCEEDED"})
    assert client.post(f"{API}/payments/webhook", content=unknown, headers=unknown_headers).status_code == 404
    bad, bad_headers = sign({"reference": payment["reference"], "status": "PENDING"})
    assert client.post(f"{API}/payments/webhook", content=bad, headers=bad_headers).status_code == 422


def test_payment_of_someone_elses_appointment_is_404(client):
    admin, structure, donor, patient = world(client)
    aid = request_donation(client, patient, donor, structure).json()["id"]
    client.post(f"{API}/appointments/{aid}/accept", headers=donor.headers)
    stranger = make_patient(client, email="autre@test.cm")
    r = client.post(f"{API}/appointments/{aid}/payments", headers=stranger.headers, json={"operator": "MTN_MOMO", "phoneNumber": "670000001"})
    assert r.status_code == 404


def test_blood_document_rules(client):
    admin = login_admin(client)
    donor = register(client, "doc@test.cm", "DONOR")
    url = f"{API}/donors/me/blood-document"

    fake = client.post(url, headers=donor.headers, files={"file": ("x.pdf", b"MZ not a pdf", "application/pdf")})
    assert fake.status_code in (400, 415, 422)
    big = client.post(url, headers=donor.headers, files={"file": ("x.pdf", PDF + b"0" * (5 * 1024 * 1024), "application/pdf")})
    assert big.status_code == 400 and big.json()["code"] == "FILE_TOO_LARGE"
    ok = client.post(url, headers=donor.headers, files={"file": ("x.pdf", PDF, "application/pdf")})
    assert ok.status_code == 200

    assert client.get(url, headers=donor.headers).content == PDF
    assert client.get(url).status_code == 401
    other = register(client, "doc2@test.cm", "DONOR")
    assert client.get(url, headers=other.headers).status_code == 404
    assert client.get(f"{API}/admin/donors/{donor.id}/blood-document", headers=admin.headers).content == PDF
    assert client.get(f"{API}/admin/donors/{donor.id}/blood-document", headers=donor.headers).status_code == 403
