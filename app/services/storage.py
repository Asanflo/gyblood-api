"""Stockage privé des documents de groupe sanguin (RG1). Jamais servis directement : seulement via l'API."""

import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.errors import ApiError

# Signature du contenu (« magic bytes ») : on ne se fie ni au nom ni au type annoncé par le client.
_SIGNATURES = (
    (b"%PDF-", ".pdf", "application/pdf"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
)
_MEDIA_TYPES = {ext: media for _, ext, media in _SIGNATURES}


def _root() -> Path:
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_document(upload: UploadFile) -> str:
    """Valide (taille, type) puis enregistre. Renvoie le nom de fichier généré."""
    limit = settings.max_document_bytes
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(400, "FILE_TOO_LARGE", f"Document trop volumineux ({limit // (1024 * 1024)} Mo maximum).")
    if not data:
        raise ApiError(400, "FILE_EMPTY", "Le document est vide.")

    extension = next((ext for sig, ext, _ in _SIGNATURES if data.startswith(sig)), None)
    if extension is None:
        raise ApiError(400, "FILE_TYPE_INVALID", "Format non accepté : envoyez un PDF, un JPEG ou un PNG.")

    name = f"{uuid.uuid4().hex}{extension}"
    (_root() / name).write_bytes(data)
    return name

def save_image(upload: UploadFile) -> str:
    """Image publique (affiche de campagne) : JPEG ou PNG uniquement, mêmes limites de taille."""
    limit = settings.max_document_bytes
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(400, "FILE_TOO_LARGE", f"Image trop volumineuse ({limit // (1024 * 1024)} Mo maximum).")
    if not data:
        raise ApiError(400, "FILE_EMPTY", "L'image est vide.")
    extension = next((ext for sig, ext, _ in _SIGNATURES if ext != ".pdf" and data.startswith(sig)), None)
    if extension is None:
        raise ApiError(400, "FILE_TYPE_INVALID", "Format non accepté : envoyez une image JPEG ou PNG.")
    name = f"{uuid.uuid4().hex}{extension}"
    (_root() / name).write_bytes(data)
    return name

def document_path(name: str) -> tuple[Path, str]:
    """Chemin et type MIME d'un document enregistré. Refuse tout nom qui sortirait du dossier."""
    path = (_root() / name).resolve()
    if path.parent != _root() or not path.is_file():
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document introuvable.")
    return path, _MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def delete_document(name: str | None) -> None:
    if not name:
        return
    path = (_root() / name).resolve()
    if path.parent == _root() and path.is_file():
        path.unlink()



