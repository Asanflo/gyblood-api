from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.deps import PageParams, active_user, get_db
from app.errors import ApiError
from app.mappers import notification_dto, paginate
from app.models import Notification, User

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=s.Page[s.NotificationDto])
def list_notifications(user: User = Depends(active_user), page: PageParams = Depends(), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id).order_by(
        Notification.created_at.desc(), Notification.id.desc()
    )
    return paginate(db, stmt, page.page, page.size, notification_dto)


@router.patch("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: int, user: User = Depends(active_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "Notification introuvable.")
    notification.read = True
    db.commit()
    return Response(status_code=204)
