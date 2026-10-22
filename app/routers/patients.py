from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import schemas as s
from app.config import settings
from app.deps import get_db, require_roles
from app.enums import AccountStatus, AppointmentStatus, BloodGroup, Rhesus, UserRole
from app.mappers import patient_dto
from app.models import Appointment, DonorProfile, PatientProfile, User
from app.services.compatibility import compatible_donor_types
from app.services.eligibility import is_eligible, load_intervals
from app.services.geo import bounding_box, haversine_km
from app.utils import utcnow

router = APIRouter(tags=["patients"])

PatientOnly = Depends(require_roles(UserRole.PATIENT, validated=True))


@router.get("/patients/me", response_model=s.PatientDto)
def get_me(user: User = PatientOnly):
    return patient_dto(user)


@router.put("/patients/me", response_model=s.PatientDto)
def update_me(body: s.UpdatePatientRequest, user: User = PatientOnly, db: Session = Depends(get_db)):
    if user.patient is None:
        user.patient = PatientProfile()
    user.patient.blood_group = body.blood_group
    user.patient.rhesus = body.rhesus
    user.patient.latitude = body.latitude
    user.patient.longitude = body.longitude
    db.commit()
    return patient_dto(user)


@router.get("/donors/search", response_model=list[s.DonorDto])
def search_donors(
    blood_group: Annotated[BloodGroup, Query(alias="bloodGroup")],
    rhesus: Rhesus,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(alias="radiusKm", gt=0)] = settings.default_search_radius_km,
    user: User = PatientOnly,
    db: Session = Depends(get_db),
):
    """Donneurs compatibles (RG4) validés, disponibles, connectés (RG11), qui partagent leur position (RG3) et hors délai de repos (RG5)."""
    radius_km = min(radius_km, settings.max_search_radius_km)
    now = utcnow()
    lat_min, lat_max, lon_min, lon_max = bounding_box(lat, lon, radius_km)
    compatible = [
        and_(DonorProfile.blood_group == group, DonorProfile.rhesus == rh)
        for group, rh in compatible_donor_types(blood_group, rhesus)
    ]
    committed = select(Appointment.donor_id).where(
        Appointment.status.in_((AppointmentStatus.ACCEPTED, AppointmentStatus.PAID))
    )

    donors = db.scalars(
        select(DonorProfile)
        .join(User, User.id == DonorProfile.user_id)
        .where(
            User.status == AccountStatus.VALIDATED,
            DonorProfile.is_available.is_(True),
            DonorProfile.share_location.is_(True),
            DonorProfile.last_seen_at >= now - timedelta(minutes=settings.presence_window_minutes),
            DonorProfile.latitude.between(lat_min, lat_max),
            DonorProfile.longitude.between(lon_min, lon_max),
            or_(*compatible),
            DonorProfile.user_id.not_in(committed),
        )
        .limit(settings.search_candidate_limit)
    ).all()

    intervals = load_intervals(db)
    found: list[s.DonorDto] = []
    for donor in donors:
        distance = haversine_km(lat, lon, donor.latitude, donor.longitude)
        if distance <= radius_km and is_eligible(donor, intervals, now):
            found.append(
                s.DonorDto(
                    id=donor.user_id,
                    full_name=donor.full_name,
                    blood_group=donor.blood_group,
                    rhesus=donor.rhesus,
                    latitude=donor.latitude,
                    longitude=donor.longitude,
                    distance_km=round(distance, 2),
                )
            )
    found.sort(key=lambda d: d.distance_km)
    return found[:settings.search_max_results]

