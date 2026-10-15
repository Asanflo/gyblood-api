from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import PageParams, get_db, require_roles
from app.enums import AccountStatus, UserRole
from app.errors import ApiError
from app.mappers import campaign_dto, donation_dto, donor_profile_dto, paginate
from app.models import Campaign, CampaignMember, Donation, DonorProfile, User
from app.services import storage
from app.services.campaigns import funds_received
from app.services.eligibility import load_intervals, next_donation_date
from app.utils import utcnow

router = APIRouter(tags=["donors"])

# Le profil se complète pendant l'attente de validation ; tout le reste exige un compte validé.
DonorAny = Depends(require_roles(UserRole.DONOR))
DonorValidated = Depends(require_roles(UserRole.DONOR, validated=True))


def _donor(user: User) -> DonorProfile:
    if user.donor is None:
        user.donor = DonorProfile()
    return user.donor


def _back_to_review(user: User, donor: DonorProfile) -> None:
    """Un changement qui touche à la preuve du groupe sanguin repasse le compte en revue (RG1)."""
    if user.status in (AccountStatus.REJECTED, AccountStatus.VALIDATED):
        user.status = AccountStatus.PENDING
        user.rejection_reason = None
        donor.is_available = False


@router.get("/donors/me", response_model=s.DonorProfileDto)
def get_me(user: User = DonorAny):
    return donor_profile_dto(_donor(user))


@router.put("/donors/me", response_model=s.DonorProfileDto)
def update_me(body: s.UpdateDonorRequest, user: User = DonorAny, db: Session = Depends(get_db)):
    donor = _donor(user)
    group_changed = (donor.blood_group, donor.rhesus) not in ((None, None), (body.blood_group, body.rhesus))

    donor.full_name = body.full_name
    donor.sex = body.sex
    donor.medical_history = body.medical_history
    donor.phone = body.phone
    donor.blood_group = body.blood_group
    donor.rhesus = body.rhesus

    if user.status == AccountStatus.REJECTED or (user.status == AccountStatus.VALIDATED and group_changed):
        _back_to_review(user, donor)
    db.commit()
    return donor_profile_dto(donor)


@router.post("/donors/me/blood-document", response_model=s.DonorProfileDto)
def upload_blood_document(file: UploadFile, user: User = DonorAny, db: Session = Depends(get_db)):
    donor = _donor(user)
    new_name = storage.save_document(file)
    old_name, donor.document_path = donor.document_path, new_name
    _back_to_review(user, donor)
    db.commit()
    storage.delete_document(old_name)
    return donor_profile_dto(donor)


@router.get("/donors/me/blood-document")
def download_blood_document(user: User = DonorAny):
    """Le donneur relit son propre document. Les documents ne sont jamais servis en accès libre."""
    donor = _donor(user)
    if not donor.document_path:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Aucun document envoyé.")
    path, media_type = storage.document_path(donor.document_path)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.patch("/donors/me/availability", response_model=s.DonorProfileDto)
def set_availability(body: s.AvailabilityRequest, user: User = DonorValidated, db: Session = Depends(get_db)):
    """Un donneur n'apparaît dans les recherches que s'il est disponible ET partage sa position (US-27)."""
    donor = _donor(user)
    donor.is_available = body.is_available
    donor.share_location = body.share_location
    db.commit()
    return donor_profile_dto(donor)


@router.get("/donors/me/eligibility", response_model=s.EligibilityDto)
def get_eligibility(user: User = DonorValidated, db: Session = Depends(get_db)):
    next_date = next_donation_date(_donor(user), load_intervals(db))
    return s.EligibilityDto(can_donate=next_date is None or next_date <= utcnow(), next_donation_date=next_date)


@router.get("/donors/me/donations", response_model=s.Page[s.DonationDto])
def get_donations(
    user: User = DonorValidated, page: PageParams = Depends(), db: Session = Depends(get_db)
):
    stmt = select(Donation).where(Donation.donor_id == user.id).order_by(Donation.donated_at.desc(), Donation.id.desc())
    return paginate(db, stmt, page.page, page.size, donation_dto)


@router.get("/donors/me/campaigns", response_model=s.Page[s.CampaignDto])
def get_campaigns(user: User = DonorValidated, page: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = (
        select(Campaign)
        .join(CampaignMember, CampaignMember.campaign_id == Campaign.id)
        .where(CampaignMember.donor_id == user.id)
        .order_by(Campaign.start_date.desc(), Campaign.id.desc())
    )
    return paginate(db, stmt, page.page, page.size, lambda c: campaign_dto(c, funds_received(db, c.id), True))
