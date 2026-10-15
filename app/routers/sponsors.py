from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import PageParams, get_db, require_roles
from app.enums import UserRole
from app.errors import ApiError
from app.mappers import funding_dto, paginate, sponsor_dto
from app.models import Funding, SponsorProfile, User

router = APIRouter(tags=["sponsors"])

SponsorOnly = Depends(require_roles(UserRole.SPONSOR, validated=True))


def _profile(user: User) -> SponsorProfile:
    if user.sponsor is None:
        user.sponsor = SponsorProfile()
    return user.sponsor


@router.get("/sponsors/me", response_model=s.SponsorDto)
def get_me(user: User = SponsorOnly):
    return sponsor_dto(_profile(user))


@router.put("/sponsors/me", response_model=s.SponsorDto)
def update_me(body: s.UpdateSponsorRequest, user: User = SponsorOnly, db: Session = Depends(get_db)):
    # Le logo est affiché dans l'application : on n'accepte que des adresses https (pas de javascript:, data:, http:).
    if body.logo_url and not body.logo_url.startswith("https://"):
        raise ApiError(422, "INVALID_LOGO_URL", "L'adresse du logo doit commencer par https://")
    sponsor = _profile(user)
    sponsor.organisation = body.organisation
    sponsor.contact = body.contact
    sponsor.logo_url = body.logo_url or None
    db.commit()
    return sponsor_dto(sponsor)


@router.get("/sponsors/me/fundings", response_model=s.Page[s.FundingDto])
def my_fundings(user: User = SponsorOnly, page: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = select(Funding).where(Funding.sponsor_id == user.id).order_by(Funding.created_at.desc(), Funding.id.desc())
    return paginate(db, stmt, page.page, page.size, funding_dto)
