import os

import cloudinary
import cloudinary.uploader
from app.config import settings

from app.errors import ApiError


def _configure_cloudinary():

    if not all((cloud_name, api_key, api_secret)):
        raise RuntimeError("Configuration Cloudinary incomplète")

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def upload_public_image(data: bytes, extension: str) -> dict:
    """Enregistre une image publique et retourne ses références."""

    _configure_cloudinary()

    try:
        result = cloudinary.uploader.upload(
            data,
            folder="jiblot/campaigns",
            resource_type="image",
            public_id=None,
            overwrite=False,
            format="jpg" if extension == ".jpg" else "png",
        )
    except Exception as exc:
        # Journaliser l'erreur technique côté serveur,
        # sans exposer les secrets au client.
        raise ApiError(
            502,
            "IMAGE_STORAGE_FAILED",
            "Impossible d'enregistrer l'image.",
        ) from exc

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
    }