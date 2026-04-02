"""
Configuration settings for the KidsChat Parent API.

The golden source for DEMO_PARENT_ID, DEMO_MODE, etc. is your .env file.
BaseSettings (see class Config below: env_file = ".env") loads .env when
Settings() is instantiated and maps each env var to the field with the same
name (e.g. DEMO_PARENT_ID in .env -> settings.DEMO_PARENT_ID). Defaults here
are only used when the env var is missing.
"""

import secrets
from typing import List, Optional, Union

# For Pydantic v2, BaseSettings has moved to pydantic-settings
from pydantic_settings import BaseSettings
from pydantic import field_validator, Field

class Settings(BaseSettings):
    """Application settings. Env vars and .env are the source of truth; defaults are fallbacks."""
    
    # API settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "KidsChat Parent API"
    
    # Security settings — DEMO_* and SECRET_KEY come from .env when set there
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    DEMO_MODE: bool = False
    DEMO_CHILD_ID: Optional[str] = None
    DEMO_PARENT_ID: Optional[str] = None  # set in .env; BaseSettings reads it via env_file=".env"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 7 days
    
    # Database settings
    DATABASE_URI: str = "sqlite:////Users/xhu/Dev/jubu_backend/kidschat.db"
    DATABASE_POOL_SIZE: int = 5
    
    # CORS settings
    CORS_ORIGINS: List[str] = ["*"]
    
    # Encryption key for sensitive data
    ENCRYPTION_KEY: Optional[str] = None
    
    # SQL settings
    SQL_ECHO: bool = False
    
    # In Pydantic v2, validator is replaced with field_validator
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    class Config:
        case_sensitive = True
        env_file = ".env"  # Pydantic loads this and fills DEMO_PARENT_ID, DEMO_MODE, DATABASE_URI, etc.
        extra = "ignore"


settings = Settings()  # <- here .env is loaded and fields (e.g. DEMO_PARENT_ID) get values from it