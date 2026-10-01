"""
App settings, loaded from environment variables (with sane local-dev defaults).

Keeping all of this in one place means the only thing you touch when moving
from your laptop to a real environment is the .env file / env vars -- nothing
in the application code has to change.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "localdevpassword"

    # How often (seconds) the background loop re-runs the discovery and
    # telemetry adapters. Short enough that the dashboard visibly updates,
    # long enough that it doesn't hammer the database on a laptop.
    reconcile_interval_seconds: float = 6.0

    # If a RUNS_ON or DEPENDS_ON fact hasn't been re-confirmed by the
    # discovery feed within this window, we mark it stale rather than
    # trusting data that might no longer be true.
    staleness_ttl_seconds: float = 30.0

    class Config:
        env_file = ".env"


settings = Settings()
