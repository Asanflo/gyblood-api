from fastapi import APIRouter, Depends, Response, UploadFile
from fastapi.responses import FileResponse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import PageParams, active_user, get_db, require_roles
from app.enums import PaymentStatus, UserRole
from app.errors import ApiError
from app.mappers import campaign_dto, funding_dto, paginate
from app.models import Campaign, CampaignMember, Funding, User
from app.services import payments as payment_service
from app.services.campaigns import ensure_open, funds_received, has_joined
from app.utils import as_utc, utcnow
from app.services import storage

router = APIRouter(tags=["campaigns"])

StructureOnly = Depends(require_roles(UserRole.STRUCTURE, validated=True))
DonorOnly = Depends(require_roles(UserRole.DONOR, validated=True))
SponsorOnly = Depends(require_roles(UserRole.SPONSOR, validated=True))


def _dto(db: Session, campaign: Campaign, user: User):
    joined = user.role == UserRole.DONOR and has_joined(db, campaign.id, user.id)
    return campaign_dto(campaign, funds_received(db, campaign.id), joined)


def _get(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ApiError(404, "CAMPAIGN_NOT_FOUND", "Campagne introuvable.")
    return campaign


@router.post("/campaigns", response_model=s.CampaignDto, status_code=201)
def create_campaign(body: s.CreateCampaignRequest, user: User = StructureOnly, db: Session = Depends(get_db)):
    campaign = Campaign(
        structure_id=user.id,
        title=body.title,
        location=body.location,
        start_date=as_utc(body.start_date),
        end_date=as_utc(body.end_date),
        target_donations=body.target_donations,
        description=body.description,
    )
    if campaign.end_date < utcnow():
        raise ApiError(422, "INVALID_DATE", "La date de fin est déjà passée.")
    db.add(campaign)
    db.commit()
    return _dto(db, campaign, user)


@router.get("/campaigns", response_model=s.Page[s.CampaignDto])
def list_campaigns(user: User = Depends(active_user), page: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = select(Campaign).order_by(Campaign.start_date.desc(), Campaign.id.desc())
    return paginate(db, stmt, page.page, page.size, lambda c: _dto(db, c, user))


@router.get("/campaigns/{campaign_id}", response_model=s.CampaignDto)
def get_campaign(campaign_id: int, user: User = Depends(active_user), db: Session = Depends(get_db)):
    return _dto(db, _get(db, campaign_id), user)

@router.post("/campaigns/{campaign_id}/image", response_model=s.CampaignDto)
def upload_campaign_image(campaign_id: int, file: UploadFile, user: User = StructureOnly, db: Session = Depends(get_db)):
    """La structure propriétaire ajoute ou remplace l'affiche de sa campagne (JPEG ou PNG)."""
    campaign = _get(db, campaign_id)
    if campaign.structure_id != user.id:
        raise ApiError(403, "FORBIDDEN", "Cette campagne n'appartient pas à votre structure.")
    new_name = storage.save_image(file)
    old_name, campaign.image_path = campaign.image_path, new_name
    db.commit()
    storage.delete_document(old_name)
    return _dto(db, campaign, user)


@router.get("/campaigns/{campaign_id}/image")
def get_campaign_image(campaign_id: int, db: Session = Depends(get_db)):
    """Affiche publique (non sensible), sans jeton : le mobile la charge directement depuis son URL."""
    campaign = _get(db, campaign_id)
    if not campaign.image_path:
        raise ApiError(404, "IMAGE_NOT_FOUND", "Cette campagne n'a pas d'affiche.")
    path, media_type = storage.document_path(campaign.image_path)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": f"public, max-age={settings.image_cache_seconds}"})

@router.post("/campaigns/{campaign_id}/join", status_code=204)
def join_campaign(campaign_id: int, user: User = DonorOnly, db: Session = Depends(get_db)):
    campaign = _get(db, campaign_id)
    ensure_open(campaign, utcnow())
    if not has_joined(db, campaign.id, user.id):  # une adhésion par campagne : rejouer l'appel ne change rien
        db.add(CampaignMember(campaign_id=campaign.id, donor_id=user.id))
        db.commit()
    return Response(status_code=204)


@router.delete("/campaigns/{campaign_id}/join", status_code=204)
def leave_campaign(campaign_id: int, user: User = DonorOnly, db: Session = Depends(get_db)):
    member = db.get(CampaignMember, (campaign_id, user.id))
    if member is not None:
        db.delete(member)
        db.commit()
    return Response(status_code=204)


@router.post("/campaigns/{campaign_id}/fundings", response_model=s.FundingDto, status_code=201)
def fund_campaign(
    campaign_id: int, body: s.FundCampaignRequest, user: User = SponsorOnly, db: Session = Depends(get_db)
):
    campaign = _get(db, campaign_id)
    ensure_open(campaign, utcnow())
    if body.amount < payment_service.MIN_FUNDING_AMOUNT:
        raise ApiError(422, "AMOUNT_TOO_LOW", f"Le montant minimum est de {payment_service.MIN_FUNDING_AMOUNT} FCFA.")

    result = payment_service.get_provider().charge(
        body.amount, body.operator, body.phone_number, f"Financement de la campagne {campaign.id}"
    )
    funding = Funding(
        campaign_id=campaign.id,
        sponsor_id=user.id,
        amount=body.amount,
        operator=body.operator,
        phone_number=body.phone_number,
        reference=result.reference,
        status=PaymentStatus.PENDING,
    )
    db.add(funding)
    db.flush()
    if result.status != PaymentStatus.PENDING:
        payment_service.apply_outcome(db, result.reference, result.status)
    db.commit()
    return funding_dto(funding)
