"""Configuration lue dans l'environnement (ou dans un fichier .env), sans préfixe : DATABASE_URL, JWT_SECRET, UPLOAD_DIR...

Reconstruit après un écrasement accidentel de l'original : les noms utilisés par database.py, services/ et
docker-compose.yml (DATABASE_URL, UPLOAD_DIR, PORT, env_file .env) sont conservés.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-change-me-0123456789abcdef"
DEV_WEBHOOK_SECRET = "dev-only-webhook-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"  # "dev" ou "prod"
    database_url: str = "sqlite:///./gyblood.db"
    # URL publique de l'API : sert à la redirection Google (<URL>/oauth2/callback/google).
    public_base_url: str = "http://10.0.2.2:8080"

    jwt_secret: str = DEV_JWT_SECRET
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # Compte administrateur créé au démarrage s'il n'existe pas (mot de passe de 8 caractères minimum).
    admin_email: str | None = None
    admin_password: str | None = None

    # Un donneur est « connecté » s'il a envoyé un signal depuis moins de ... minutes (RG11).
    presence_window_minutes: int = 5
    max_search_radius_km: float = 50
    # Délai de repos utilisé tant que le sexe du donneur ou la règle correspondante manque (RG5). À fixer d'après le CNTS.
    default_min_days_between_donations: int = 56

    # Frais d'entretien et d'examens (FCFA) tant que la structure n'a pas fixé son tarif.
    default_hospital_fee: int = 5000
    # Commission de la plateforme, prélevée sur le montant payé par le patient (RG7).
    platform_fee_percent: float = 5

    payment_provider: str = "sandbox"
    sandbox_auto_confirm: bool = True
    payment_webhook_secret: str = DEV_WEBHOOK_SECRET

    google_client_id: str | None = None
    google_client_secret: str | None = None

    upload_dir: str = "./uploads"
    max_document_bytes: int = 5 * 1024 * 1024

    # Fichier JSON du compte de service Firebase. Vide : pas de push, les notifications restent lisibles via l'API.
    fcm_credentials_file: str | None = None

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.app_env == "prod":
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET doit être défini (32 caractères minimum) en production.")
            if self.payment_webhook_secret == DEV_WEBHOOK_SECRET:
                raise ValueError("PAYMENT_WEBHOOK_SECRET doit être défini en production.")
            if self.payment_provider == "sandbox":
                raise ValueError("Le fournisseur de paiement « sandbox » est interdit en production.")
        return self


settings = Settings()
