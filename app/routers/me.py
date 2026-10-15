from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import active_user, current_user, get_db, require_roles
from app.enums import UserRole
from app.mappers import user_dto
from app.models import Device, User
from app.utils import utcnow

router = APIRouter(tags=["me"])


@router.get("/me", response_model=s.UserDto)
def get_me(user: User = Depends(current_user)):
    # Volontairement sans contrôle de suspension : l'application doit pouvoir lire l'état du compte pour l'expliquer.
    return user_dto(user)


@router.post("/me/devices", status_code=204)
def register_device(body: s.RegisterDeviceRequest, user: User = Depends(active_user), db: Session = Depends(get_db)):
    device = db.scalar(select(Device).where(Device.fcm_token == body.fcm_token))
    if device is None:
        db.add(Device(user_id=user.id, fcm_token=body.fcm_token))
    else:
        device.user_id = user.id  # le téléphone a changé de compte
    db.commit()
    return Response(status_code=204)


@router.post("/me/heartbeat", status_code=204)
def heartbeat(
    body: s.HeartbeatRequest,
    user: User = Depends(require_roles(UserRole.DONOR, validated=True)),
    db: Session = Depends(get_db),
):
    """Signal de présence (RG11). La position n'est montrée aux patients que si le donneur partage sa localisation."""
    donor = user.donor
    donor.last_seen_at = utcnow()
    donor.latitude = body.latitude
    donor.longitude = body.longitude
    db.commit()
    return Response(status_code=204)
