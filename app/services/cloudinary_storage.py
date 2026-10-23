
import cloudinary
import cloudinary.uploader

from app.config import settings
from app.errors import ApiError


def _configure_cloudinary() -> None:
    """Configure Cloudinary à partir des paramètres de l'application."""

    cloud_name = settings.cloudinary_cloud_name
    api_key = settings.cloudinary_api_key
    api_secret = settings.cloudinary_api_secret

    if not all((cloud_name, api_key, api_secret)):
        raise RuntimeError(
            "Configuration Cloudinary incomplète. "
            "Vérifiez les variables d'environnement."
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def upload_public_image(data: bytes, extension: str) -> dict:
    """Enregistre une image publique sur Cloudinary et retourne ses références."""

    _configure_cloudinary()

    image_format = extension.lower()

    if image_format == ".jpeg":
        image_format = ".jpg"

    if image_format not in (".jpg", ".png"):
        raise ApiError(
            400,
            "UNSUPPORTED_IMAGE_FORMAT",
            "Le format de l'image n'est pas pris en charge.",
        )

    try:
        result = cloudinary.uploader.upload(
            data,
            folder="jiblot/campaigns",
            resource_type="image",
            overwrite=False,
            format=image_format.lstrip("."),
        )

        secure_url = result.get("secure_url")
        public_id = result.get("public_id")

        if not secure_url or not public_id:
            raise RuntimeError(
                "Cloudinary n'a pas retourné les références attendues."
            )

        return {
            "url": secure_url,
            "public_id": public_id,
        }

    except ApiError:
        raise

    except Exception as exc:
        # Conserver les détails techniques dans les logs du serveur.
        # Ne jamais exposer les secrets Cloudinary au client.
        import logging

        logging.getLogger(__name__).exception(
            "Échec de l'envoi de l'image vers Cloudinary."
        )

        raise ApiError(
            502,
            "IMAGE_STORAGE_FAILED",
            "Impossible d'enregistrer l'image.",
        ) from exc
