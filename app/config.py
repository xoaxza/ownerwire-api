from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "OwnerWire")
    app_description: str = os.getenv(
        "APP_DESCRIPTION",
        "Citation-backed API for messy SEC insider ownership filings.",
    )
    base_url: str = os.getenv("BASE_URL", "").rstrip("/")
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "OwnerWire/0.1 (team@scottyshelpers.org)",
    )
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "30"))


settings = Settings()
