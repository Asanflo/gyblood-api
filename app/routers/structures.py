from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import active_user, get_db, require_roles
from app.enums import AccountStatus, BloodGroup, Rhesus, UserRole
from app.mappers import stock_dto, structure_dto
from app.models import BloodStock, StructureProfile, User
from app.services.geo import haversine_km
from app.utils import utcnow

router = APIRouter(tags=["structures"])

# Une structure complète son profil pendant l'attente de validation (RG2) ; le reste exige un compte validé.
StructureAny = Depends(require_roles(UserRole.STRUCTURE))
StructureValidated = Depends(require_roles(UserRole.STRUCTURE, validated=True))
PatientOnly = Depends(require_roles(UserRole.PATIENT, validated=True))


def _profile(user: User) -> StructureProfile:
    if user.structure is None:
        user.structure = StructureProfile()
    return user.structure


def _validated_structures(db: Session) -> list[StructureProfile]:
    return list(
        db.scalars(
            select(StructureProfile)
            .join(User, User.id == StructureProfile.user_id)
            .where(User.status == AccountStatus.VALIDATED, StructureProfile.latitude.is_not(None))
            .order_by(StructureProfile.name)
        )
    )


@router.get("/structures/me", response_model=s.StructureDto)
def get_me(user: User = StructureAny):
    return structure_dto(_profile(user))


@router.put("/structures/me", response_model=s.StructureDto)
def update_me(body: s.UpdateStructureRequest, user: User = StructureAny, db: Session = Depends(get_db)):
    structure = _profile(user)
    identity_changed = (structure.name, structure.latitude, structure.longitude) not in (
        ("", None, None),
        (body.name, body.latitude, body.longitude),
    )

    structure.name = body.name
    structure.address = body.address
    structure.latitude = body.latitude
    structure.longitude = body.longitude
    structure.phone = body.phone
    structure.donation_fee = body.donation_fee

    # Nom et position servent à la confiance des patients : un changement repasse la structure en revue.
    if user.status == AccountStatus.REJECTED or (user.status == AccountStatus.VALIDATED and identity_changed):
        user.status = AccountStatus.PENDING
        user.rejection_reason = None
    db.commit()
    return structure_dto(structure)


@router.get("/structures", response_model=list[s.StructureDto])
def list_structures(user: User = Depends(active_user), db: Session = Depends(get_db)):
    return [structure_dto(item) for item in _validated_structures(db)]


@router.get("/structures/nearest", response_model=list[s.StructureDto])
def nearest_structures(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    user: User = PatientOnly,
    db: Session = Depends(get_db),
):
    ranked = sorted(
        ((haversine_km(lat, lon, item.latitude, item.longitude), item) for item in _validated_structures(db)),
        key=lambda pair: pair[0],
    )
    return [structure_dto(item, distance) for distance, item in ranked[:limit]]


@router.get("/stocks", response_model=list[s.StockDto])
def list_stocks(
    blood_group: Annotated[BloodGroup | None, Query(alias="bloodGroup")] = None,
    rhesus: Rhesus | None = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    user: User = Depends(active_user),
    db: Session = Depends(get_db),
):
    """Stocks publiés par les structures validées (RG9), du plus proche au plus loin si une position est donnée."""
    stmt = (
        select(BloodStock)
        .join(StructureProfile, StructureProfile.user_id == BloodStock.structure_id)
        .join(User, User.id == StructureProfile.user_id)
        .where(User.status == AccountStatus.VALIDATED)
    )
    if blood_group is not None:
        stmt = stmt.where(BloodStock.blood_group == blood_group)
    if rhesus is not None:
        stmt = stmt.where(BloodStock.rhesus == rhesus)

    located = lat is not None and lon is not None
    rows: list[tuple[float | None, BloodStock]] = []
    for stock in db.scalars(stmt):
        struct = stock.structure
        distance = (
            haversine_km(lat, lon, struct.latitude, struct.longitude)
            if located and struct.latitude is not None and struct.longitude is not None
            else None
        )
        rows.append((distance, stock))

    rows.sort(
        key=lambda pair: (
            pair[0] if pair[0] is not None else float("inf"),
            pair[1].structure.name,
            pair[1].blood_group.value,
            pair[1].rhesus.value,
        )
    )
    return [stock_dto(stock, distance) for distance, stock in rows]


@router.put("/structures/me/stocks", response_model=list[s.StockDto])
def update_my_stocks(body: s.UpdateStocksRequest, user: User = StructureValidated, db: Session = Depends(get_db)):
    now = utcnow()
    existing = {
        (stock.blood_group, stock.rhesus): stock
        for stock in db.scalars(select(BloodStock).where(BloodStock.structure_id == user.id))
    }
    for item in body.items:
        stock = existing.get((item.blood_group, item.rhesus))
        if stock is None:
            stock = BloodStock(structure_id=user.id, blood_group=item.blood_group, rhesus=item.rhesus)
            db.add(stock)
            existing[(item.blood_group, item.rhesus)] = stock
        stock.quantity = item.quantity
        stock.updated_at = now
    db.commit()

    mine = sorted(existing.values(), key=lambda st: (st.blood_group.value, st.rhesus.value))
    return [stock_dto(stock) for stock in mine]
