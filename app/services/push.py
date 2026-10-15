"""Envoi de notifications push (Firebase Cloud Messaging).

Si FCM_CREDENTIALS_FILE n'est pas défini, ou si firebase-admin n'est pas installé, rien n'est envoyé :
les notifications restent enregistrées en base et lisibles via GET /notifications.
NON TESTÉ contre un vrai projet Firebase.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Device

logger = logging.getLogger(__name__)

_app = None
_unavailable = False


def _firebase():
    global _app, _unavailable
    if _unavailable or not settings.fcm_credentials_file:
        return None
    if _app is not None:
        return _app
    try:
        import firebase_admin
        from firebase_admin import credentials

        _app = firebase_admin.initialize_app(credentials.Certificate(settings.fcm_credentials_file))
        return _app
    except Exception:  # pragma: no cover - dépend de l'environnement
        logger.exception("Firebase indisponible : les notifications push sont désactivées")
        _unavailable = True
        return None


def send_to_user(db: Session, user_id: int, title: str, message: str, data: dict[str, str] | None = None) -> None:
    app = _firebase()
    if app is None:
        return

    tokens = db.scalars(select(Device.fcm_token).where(Device.user_id == user_id)).all()
    if not tokens:
        return

    try:  # pragma: no cover - nécessite Firebase
        from firebase_admin import messaging

        for token in tokens:
            try:
                messaging.send(
                    messaging.Message(
                        token=token,
                        notification=messaging.Notification(title=title, body=message),
                        data=data or {},
                    ),
                    app=app,
                )
            except messaging.UnregisteredError:
                db.query(Device).filter(Device.fcm_token == token).delete()
    except Exception:
        logger.exception("Échec de l'envoi push à l'utilisateur %s", user_id)
