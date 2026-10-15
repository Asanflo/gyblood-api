from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PASSWORD = "Passw0rd-test"
PDF = b"%PDF-1.4\n% document de test\n"
API = "/api/v1"

# Autour de Douala : environ 1,3 km entre le patient et le donneur.
PATIENT_POS = (4.0511, 9.7679)
DONOR_POS = (4.0600, 9.7700)
HOSPITAL_POS = (4.0617, 9.7176)


@dataclass
class Actor:
    id: int
    email: str
    role: str
    headers: dict
    refresh_token: str


def register(client, email: str, role: str) -> Actor:
    response = client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD, "role": role})
    assert response.status_code == 201, response.text
    data = response.json()
    return Actor(
        id=data["user"]["id"],
        email=email,
        role=role,
        headers={"Authorization": f"Bearer {data['accessToken']}"},
        refresh_token=data["refreshToken"],
    )


def login_admin(client) -> Actor:
    response = client.post(f"{API}/auth/login", json={"email": "admin@gyblood.test", "password": "Admin-Passw0rd"})
    assert response.status_code == 200, response.text
    data = response.json()
    return Actor(
        id=data["user"]["id"],
        email="admin@gyblood.test",
        role="ADMIN",
        headers={"Authorization": f"Bearer {data['accessToken']}"},
        refresh_token=data["refreshToken"],
    )


def future(days: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def approve(client, admin: Actor, who: Actor) -> None:
    response = client.post(f"{API}/admin/accounts/{who.id}/approve", headers=admin.headers)
    assert response.status_code == 204, response.text


def make_structure(client, admin: Actor, email="hopital@test.cm", name="Hôpital Test", fee=5000) -> Actor:
    structure = register(client, email, "STRUCTURE")
    response = client.put(
        f"{API}/structures/me",
        headers=structure.headers,
        json={
            "name": name,
            "address": "Douala",
            "latitude": HOSPITAL_POS[0],
            "longitude": HOSPITAL_POS[1],
            "phone": "677000000",
            "donationFee": fee,
        },
    )
    assert response.status_code == 200, response.text
    approve(client, admin, structure)
    return structure


def make_donor(client, admin: Actor, email="donneur@test.cm", group="O", rhesus="NEGATIVE", sex="MALE") -> Actor:
    donor = register(client, email, "DONOR")
    response = client.put(
        f"{API}/donors/me",
        headers=donor.headers,
        json={
            "fullName": "Donneur Test",
            "sex": sex,
            "medicalHistory": "Aucun",
            "phone": "697117458",
            "bloodGroup": group,
            "rhesus": rhesus,
        },
    )
    assert response.status_code == 200, response.text
    upload = client.post(
        f"{API}/donors/me/blood-document", headers=donor.headers, files={"file": ("groupe.pdf", PDF, "application/pdf")}
    )
    assert upload.status_code == 200, upload.text
    approve(client, admin, donor)
    return donor


def go_online(client, donor: Actor, pos=DONOR_POS) -> None:
    """Disponible + position partagée + signal de présence : le donneur devient visible dans les recherches."""
    response = client.patch(
        f"{API}/donors/me/availability", headers=donor.headers, json={"isAvailable": True, "shareLocation": True}
    )
    assert response.status_code == 200, response.text
    heartbeat = client.post(
        f"{API}/me/heartbeat", headers=donor.headers, json={"latitude": pos[0], "longitude": pos[1]}
    )
    assert heartbeat.status_code == 204, heartbeat.text


def make_patient(client, email="patient@test.cm", group="A", rhesus="POSITIVE") -> Actor:
    patient = register(client, email, "PATIENT")
    response = client.put(
        f"{API}/patients/me",
        headers=patient.headers,
        json={"bloodGroup": group, "rhesus": rhesus, "latitude": PATIENT_POS[0], "longitude": PATIENT_POS[1]},
    )
    assert response.status_code == 200, response.text
    return patient


def request_donation(client, patient: Actor, donor: Actor, structure: Actor):
    return client.post(
        f"{API}/appointments",
        headers=patient.headers,
        json={"donorId": donor.id, "structureId": structure.id, "scheduledAt": future()},
    )
