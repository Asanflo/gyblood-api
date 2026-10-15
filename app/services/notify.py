from sqlalchemy.orm import Session

from app.models import Notification
from app.services import push


def notify(db: Session, user_id: int, title: str, message: str, appointment_id: int | None = None) -> None:
    """Enregistre la notification (lue via GET /notifications) puis tente un push. À appeler avant db.commit()."""
    db.add(Notification(user_id=user_id, title=title, message=message, appointment_id=appointment_id))
    data = {"appointmentId": str(appointment_id)} if appointment_id is not None else None
    push.send_to_user(db, user_id, title, message, data)
