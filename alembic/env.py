
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base, normalize_url

# Charger les modèles SQLAlchemy afin de remplir Base.metadata.
import app.models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Métadonnées utilisées par l'autogénération des migrations.
target_metadata = Base.metadata

# Réutiliser la configuration de connexion de l'application.
database_url = normalize_url(settings.database_url)

config.set_main_option(
    "sqlalchemy.url",
    database_url.replace("%", "%%"),
)


def run_migrations_offline() -> None:
    """Générer le SQL sans ouvrir de connexion à la base."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Exécuter les migrations avec une connexion réelle."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        print(
            f"Tables SQLAlchemy détectées : "
            f"{len(target_metadata.tables)}"
        )

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
