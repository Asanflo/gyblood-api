"""Stockage privé des documents de groupe sanguin (RG1). Jamais servis directement : seulement via l'API."""

import uuid
from pathlib import Path

from fastapi import UploadFile
import cloudinary
import cloudinary.uploader

from .cloudinary_storage import upload_public_image

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

def save_image(upload: UploadFile) -> dict:
    """Valide une image puis la stocke dans Cloudinary."""

    limit = settings.max_document_bytes
    data = upload.file.read(limit + 1)

    if len(data) > limit:
        raise ApiError(
            400,
            "FILE_TOO_LARGE",
            f"Image trop volumineuse "
            f"({limit // (1024 * 1024)} Mo maximum).",
        )

    if not data:
        raise ApiError(400, "FILE_EMPTY", "L'image est vide.")

    extension = next(
        (
            ext
            for sig, ext, _ in _SIGNATURES
            if ext != ".pdf" and data.startswith(sig)
        ),
        None,
    )

    if extension is None:
        raise ApiError(
            400,
            "FILE_TYPE_INVALID",
            "Format non accepté : envoyez une image JPEG ou PNG.",
        )

    return upload_public_image(data, extension)

def document_path(name: str) -> tuple[Path, str]:
    """Chemin et type MIME d'un document enregistré. Refuse tout nom qui sortirait du dossier."""
    path = (_root() / name).resolve()
    if path.parent != _root() or not path.is_file():
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document introuvable.")
    return path, _MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def delete_document(name: str | dict | None) -> None:
    """Supprime une image Cloudinary ou un document stocké localement."""
    if not name:
        return

    # Image Cloudinary retournée par save_image()
    if isinstance(name, dict):
        public_id = name.get("public_id")

        if public_id:
            cloudinary.uploader.destroy(
                public_id,
                resource_type="image",
            )
        return

    # URL Cloudinary enregistrée dans campaign.image_path
    if isinstance(name, str) and "res.cloudinary.com" in name:
        from urllib.parse import urlparse
        import re

        parsed = urlparse(name)
        parts = parsed.path.split("/")

        try:
            upload_index = parts.index("upload")
            asset_parts = parts[upload_index + 1:]

            # Ignorer une éventuelle version v123456789/
            if asset_parts and re.fullmatch(r"v\d+", asset_parts[0]):
                asset_parts = asset_parts[1:]

            if not asset_parts:
                return

            # Enlever l'extension du fichier
            asset_parts[-1] = asset_parts[-1].rsplit(".", 1)[0]
            public_id = "/".join(asset_parts)

            cloudinary.uploader.destroy(
                public_id,
                resource_type="image",
            )
        except (ValueError, IndexError):
            return

        return

    # Document stocké localement : certificat PDF, JPEG ou PNG
    path = (_root() / name).resolve()

    if path.parent == _root() and path.is_file():
        path.unlink()



