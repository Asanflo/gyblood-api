from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import PageParams, get_db, require_roles
from app.enums import AccountStatus, UserRole
from app.errors import ApiError
from app.mappers import account_summary_dto, display_name, donor_profile_dto, paginate, sponsor_dto, structure_dto
from app.models import DonationInterval, DonorProfile, StructureProfile, User
from app.services import storage
from app.services.notify import notify

router = APIRouter(prefix="/admin", tags=["admin"])

AdminOnly = Depends(require_roles(UserRole.ADMIN, validated=True))


def _account(db: Session, account_id: int) -> User:
    user = db.get(User, account_id)
    if user is None:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Compte introuvable.")
    return user


def _missing_for_review(user: User) -> list[str]:
    """Champs à compléter avant qu'un compte donneur ou structure puisse être validé (RG1, RG2)."""
    missing: list[str] = []
    if user.role == UserRole.DONOR:
        donor: DonorProfile | None = user.donor
        if donor is None or not donor.full_name:
            missing.append("nom complet")
        if donor is None or donor.sex is None:
            missing.append("sexe")
        if donor is None or donor.blood_group is None or donor.rhesus is None:
            missing.append("groupe sanguin")
        if donor is None or not donor.document_path:
            missing.append("document de groupe sanguin")
    elif user.role == UserRole.STRUCTURE:
        structure: StructureProfile | None = user.structure
        if structure is None or not structure.name:
            missing.append("nom")
        if structure is None or not structure.address:
            missing.append("adresse")
        if structure is None or structure.latitude is None or structure.longitude is None:
            missing.append("position")
        if structure is None or not structure.phone:
            missing.append("téléphone")
    return missing


@router.get("/accounts", response_model=s.Page[s.AccountSummaryDto])
def list_accounts(
    status: AccountStatus | None = Query(default=None),
    role: UserRole | None = Query(default=None),
    admin: User = AdminOnly,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    stmt = select(User)
    if status is not None:
        stmt = stmt.where(User.status == status)
    if role is not None:
        stmt = stmt.where(User.role == role)
    # À valider : les plus anciens d'abord, pour traiter les demandes dans l'ordre d'arrivée.
    order = User.created_at.asc() if status == AccountStatus.PENDING else User.created_at.desc()
    return paginate(db, stmt.order_by(order, User.id), page.page, page.size, account_summary_dto)


@router.get("/accounts/{account_id}", response_model=s.AccountDetailDto)
def get_account(account_id: int, admin: User = AdminOnly, db: Session = Depends(get_db)):
    user = _account(db, account_id)
    return s.AccountDetailDto(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        display_name=display_name(user),
        rejection_reason=user.rejection_reason,
        created_at=user.created_at,
        donor=donor_profile_dto(user.donor) if user.donor else None,
        structure=structure_dto(user.structure) if user.structure else None,
        sponsor=sponsor_dto(user.sponsor) if user.sponsor else None,
    )


@router.get("/donors/{donor_id}/blood-document")
def donor_blood_document(donor_id: int, admin: User = AdminOnly, db: Session = Depends(get_db)):
    donor = db.get(DonorProfile, donor_id)
    if donor is None or not donor.document_path:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Aucun document pour ce donneur.")
    path, media_type = storage.document_path(donor.document_path)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/accounts/{account_id}/approve", status_code=204)
def approve(account_id: int, admin: User = AdminOnly, db: Session = Depends(get_db)):
    user = _account(db, account_id)
    if user.status != AccountStatus.PENDING:
        raise ApiError(409, "INVALID_STATE", "Seul un compte en attente peut être validé.")
    missing = _missing_for_review(user)
    if missing:
        raise ApiError(
            409,
            "PROFILE_INCOMPLETE",
            "Profil incomplet : " + ", ".join(missing) + ".",
            {"missing": ", ".join(missing)},
        )
    user.status = AccountStatus.VALIDATED
    user.rejection_reason = None
    notify(db, user.id, "Compte validé", "Votre compte a été validé. Vous pouvez maintenant utiliser GyBlood.")
    db.commit()
    return Response(status_code=204)


@router.post("/accounts/{account_id}/reject", status_code=204)
def reject(account_id: int, body: s.RejectAccountRequest, admin: User = AdminOnly, db: Session = Depends(get_db)):
    user = _account(db, account_id)
    if user.status != AccountStatus.PENDING:
        raise ApiError(409, "INVALID_STATE", "Seul un compte en attente peut être refusé.")
    user.status = AccountStatus.REJECTED
    user.rejection_reason = body.reason
    notify(db, user.id, "Compte refusé", f"Votre compte a été refusé. Motif : {body.reason}")
    db.commit()
    return Response(status_code=204)


@router.post("/accounts/{account_id}/suspend", status_code=204)
def suspend(account_id: int, admin: User = AdminOnly, db: Session = Depends(get_db)):
    user = _account(db, account_id)
    if user.role == UserRole.ADMIN:
        raise ApiError(403, "FORBIDDEN", "Un compte administrateur ne peut pas être suspendu ici.")
    if user.status != AccountStatus.VALIDATED:
        raise ApiError(409, "INVALID_STATE", "Seul un compte validé peut être suspendu.")
    user.status = AccountStatus.SUSPENDED
    if user.donor is not None:
        user.donor.is_available = False  # disparaît des recherches immédiatement
    db.commit()
    return Response(status_code=204)


@router.post("/accounts/{account_id}/reactivate", status_code=204)
def reactivate(account_id: int, admin: User = AdminOnly, db: Session = Depends(get_db)):
    user = _account(db, account_id)
    if user.status != AccountStatus.SUSPENDED:
        raise ApiError(409, "INVALID_STATE", "Seul un compte suspendu peut être réactivé.")
    user.status = AccountStatus.VALIDATED
    notify(db, user.id, "Compte réactivé", "Votre compte est de nouveau actif.")
    db.commit()
    return Response(status_code=204)


def _intervals(db: Session) -> list[s.DonationIntervalDto]:
    rows = db.scalars(select(DonationInterval).order_by(DonationInterval.donation_type, DonationInterval.sex))
    return [s.DonationIntervalDto(sex=r.sex, donation_type=r.donation_type, min_days=r.min_days) for r in rows]


@router.get("/settings/donation-intervals", response_model=list[s.DonationIntervalDto])
def get_intervals(admin: User = AdminOnly, db: Session = Depends(get_db)):
    return _intervals(db)


@router.put("/settings/donation-intervals", response_model=list[s.DonationIntervalDto])
def update_intervals(body: list[s.DonationIntervalDto], admin: User = AdminOnly, db: Session = Depends(get_db)):
    """Fixe le délai minimal entre deux dons (RG5) par sexe et type de don. Les couples absents de la liste ne changent pas."""
    keys = {(item.sex, item.donation_type) for item in body}
    if len(keys) != len(body):
        raise ApiError(422, "DUPLICATE_INTERVAL", "Un couple sexe / type de don ne peut apparaître qu'une fois.")

    existing = {(r.sex, r.donation_type): r for r in db.scalars(select(DonationInterval))}
    for item in body:
        row = existing.get((item.sex, item.donation_type))
        if row is None:
            db.add(DonationInterval(sex=item.sex, donation_type=item.donation_type, min_days=item.min_days))
        else:
            row.min_days = item.min_days
    db.commit()
    return _intervals(db)
