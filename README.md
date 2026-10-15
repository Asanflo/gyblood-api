# GyBlood API (FastAPI)

Backend consommé par l'application MAUI GyBlood. Il respecte le contrat du client Refit : base `/api/v1/`, JSON camelCase,
énumérations en `MAJUSCULES_AVEC_TIRET_BAS`, pages au format Spring (`content`, `totalElements`, `totalPages`, `number`, `size`),
erreurs `{code, message, details}` (le `message` est affiché tel quel à l'utilisateur), montants en FCFA entiers.

## Lancer

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                        # puis adapter
python -m app.seed --demo                   # optionnel : 1 compte par rôle (mot de passe Demo-1234), dev uniquement
uvicorn app.main:app --host 0.0.0.0 --port 8080
pytest                                      # 36 tests
```

Documentation interactive : `http://localhost:8080/docs` (désactivée si `APP_ENV=prod`).
Docker : `docker compose up` (PostgreSQL inclus).
L'émulateur Android joint le PC via `http://10.0.2.2:8080/api/v1/`.

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `APP_ENV` | `dev` ou `prod`. En `prod`, le démarrage refuse un `JWT_SECRET` < 32 caractères, le secret webhook par défaut et le fournisseur `sandbox`. |
| `DATABASE_URL` | SQLite en dev (`sqlite:///gyblood.db`), PostgreSQL en prod (`postgresql://…`, pilote psycopg). |
| `PUBLIC_BASE_URL` | URL publique de l'API (sert à construire le `redirect_uri` Google). |
| `JWT_SECRET` | Secret de signature des jetons d'accès. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Compte administrateur créé au démarrage s'il n'existe pas. |
| `PAYMENT_PROVIDER`, `SANDBOX_AUTO_CONFIRM`, `PAYMENT_WEBHOOK_SECRET` | Paiement (voir ci-dessous). |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Connexion Google. Sans eux : 503 `GOOGLE_NOT_CONFIGURED`. |
| `UPLOAD_DIR`, `MAX_DOCUMENT_BYTES` | Stockage privé des documents (5 Mo). |
| `FCM_CREDENTIALS_FILE` | Notifications push Firebase (optionnel). |

## Règles métier implémentées

- Donneurs et structures sont `PENDING` jusqu'à validation par un administrateur, qui exige un profil complet (RG1/RG2).
- Recherche de donneurs : validé, disponible, position partagée, signal de présence < 5 min, compatibilité ABO/Rh,
  hors délai de repos, sans rendez-vous accepté ou payé en cours (RG3/RG4/RG5/RG11). Le patient ne voit que nom, position, groupe.
- Rendez-vous : `REQUESTED → ACCEPTED → PAID → COMPLETED`, ou `CANCELLED` / `NO_SHOW` (RG6). Un refus du donneur devient `CANCELLED`.
- Paiement : le patient règle les frais de la structure ; la part de la plateforme (`PLATFORM_FEE_PERCENT`, 5 %) en est déduite (RG7).
- Un don terminé démarre le délai de repos du donneur.

## Paiement

`SandboxProvider` simule un agrégateur : confirmation immédiate, ou échec si le numéro se termine par `0000`.
Avec `SANDBOX_AUTO_CONFIRM=false` le paiement reste `PENDING` jusqu'au webhook :

```bash
BODY='{"reference":"<reference>","status":"SUCCEEDED"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$PAYMENT_WEBHOOK_SECRET" -hex | sed 's/^.* //')
curl -X POST http://localhost:8080/api/v1/payments/webhook -H "X-Signature: $SIG" -H 'Content-Type: application/json' -d "$BODY"
```

Le webhook est idempotent et un échec tardif ne défait pas un paiement confirmé.
Pour brancher un vrai agrégateur : implémenter `charge()` dans `app/services/payments.py`, l'enregistrer dans `get_provider()`,
puis adapter la vérification de signature à son format.

## Connexion Google (PKCE)

L'application ouvre `/oauth2/authorization/google?code_challenge=…&role=…` → Google → `/oauth2/callback/google` →
redirection `gyblood://auth?code=…` → `POST /api/v1/auth/google/exchange {code, codeVerifier}`. Aucun jeton ne transite dans l'URL.
Le compte Google d'une adresse déjà inscrite par mot de passe n'est **pas** rattaché automatiquement (409 `ACCOUNT_EXISTS`).
`POST /auth/google` (idToken) est aussi disponible. **Non testé contre le vrai Google** : seuls les appels à Google sont simulés dans les tests.

## Limites et décisions à confirmer

- **Non-présentation** : pas de remboursement. Annulation d'un rendez-vous payé : `refund_due` et alerte aux administrateurs ; remboursement **manuel**.
- **Délais de repos** : 56 jours (homme) / 84 jours (femme) pour le sang total sont des valeurs de départ, à faire valider d'après le CNTS (modifiables via `PUT /admin/settings/donation-intervals`).
- Le donneur voit « Patient » comme nom du demandeur (pas d'identité dévoilée).
- Notifications push FCM : code présent, **non testé**.
- Avant la production : limitation de débit (rate limiting), migrations Alembic à la place de `create_all`, HTTPS, sauvegarde des documents, réglage des journaux.
