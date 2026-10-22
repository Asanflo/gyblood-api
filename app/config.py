from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ----- Obligatoires (à définir dans le .env)
    app_env: str  # "dev" ou "prod"
    database_url: str
    # URL publique de l'API : sert à la redirection Google et aux liens d'images.
    public_base_url: str
    # Adresse où l'application mobile est rappelée après la connexion Google (schéma déclaré côté MAUI).
    mobile_callback_url: str

    # Préfixe des routes de l'API (doit correspondre à l'adresse de base du mobile).
    api_prefix: str

    jwt_secret: str
    jwt_algorithm: str
    access_token_minutes: int
    refresh_token_days: int
    # Validité du « state » OAuth Google et du code à usage unique rendu à l'application (minutes).
    oauth_state_minutes: int
    auth_code_minutes: int

    # Un donneur est « connecté » s'il a envoyé un signal depuis moins de ... minutes (RG11).
    presence_window_minutes: int
    max_search_radius_km: float
    # Rayon utilisé quand le patient n'en précise pas, nombre de candidats examinés et de donneurs renvoyés.
    default_search_radius_km: float
    search_candidate_limit: int
    search_max_results: int
    # Pagination des listes (taille par défaut et taille maximale).
    page_default_size: int
    page_max_size: int
    # Délai de repos utilisé tant que le sexe du donneur ou la règle correspondante manque (RG5).
    default_min_days_between_donations: int

    # Frais d'entretien et d'examens (FCFA) tant que la structure n'a pas fixé son tarif.
    default_hospital_fee: int
    # Commission de la plateforme, prélevée sur le montant payé par le patient (RG7).
    platform_fee_percent: float
    # Montant minimum d'un financement de campagne (FCFA).
    min_funding_amount: int

    payment_provider: str
    sandbox_auto_confirm: bool
    payment_webhook_secret: str

    # Mot de passe des comptes créés par `python seed_data.py` et `python -m app.seed --demo` (développement).
    demo_password: str

    upload_dir: str
    max_document_bytes: int
    # Durée de mise en cache des images de campagne par le téléphone (secondes).
    image_cache_seconds: int

    # Connexion Google : adresses des services, permissions demandées et délai d'attente des appels (secondes).
    google_auth_url: str
    google_token_url: str
    google_scope: str
    external_timeout_seconds: int

    # ----- Facultatifs (vides = fonction désactivée)
    # Compte administrateur créé au démarrage s'il n'existe pas (mot de passe de 8 caractères minimum).
    admin_email: str | None = None
    admin_password: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Fichier JSON du compte de service Firebase. Vide : pas de push, les notifications restent lisibles via l'API.
    fcm_credentials_file: str | None = None

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.app_env == "prod":
            if len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET doit contenir 32 caractères minimum en production.")
            if len(self.payment_webhook_secret) < 16:
                raise ValueError("PAYMENT_WEBHOOK_SECRET doit contenir 16 caractères minimum en production.")
            if self.payment_webhook_secret == self.jwt_secret:
                raise ValueError("PAYMENT_WEBHOOK_SECRET doit être différent de JWT_SECRET.")
            if self.payment_provider == "sandbox":
                raise ValueError("Le fournisseur de paiement « sandbox » est interdit en production.")
        return self


settings = Settings()