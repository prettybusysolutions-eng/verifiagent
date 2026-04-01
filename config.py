"""
VerifiAgent — Adversarial Verification as a Product.

SecurityMonitor + VerificationSpecialist + DreamConsolidation
as a hosted API and GitHub App.

Owner: prettybusysolutions-eng
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    app_name: str = "VerifiAgent"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 8003

    # Database
    database_url: str = "sqlite:///./verifiagent.db"

    # GitHub
    github_app_id: Optional[int] = None
    github_app_private_key: Optional[str] = None
    github_webhook_secret: str = "development-secret-change-me"

    # Secrets
    api_key_header: str = "X-API-Key"
    admin_key: Optional[str] = None

    # Attribution
    attribution_split: float = 0.70  # 70% to contributor

    # Paths
    memory_dir: str = "~/.openclaw/workspace-aurex/memory"
    scratch_dir: str = "/tmp/verifiagent-scratch"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
