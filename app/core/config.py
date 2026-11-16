from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Community Missing Item & Asset Tracker"
    API_V1_STR: str = "/api/v1"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "tracker_db"
    POSTGRES_PORT: int = 5432

    # JWT Authentication
    SECRET_KEY: str = "CHANGEME_IN_PRODUCTION_must_be_32_chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # S3 / MinIO Object Storage
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "tracker-images"
    S3_REGION_NAME: str = "us-east-1"

    # Kafka Event Broker (Local Development)
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_DOMAIN_EVENTS_TOPIC: str = "boomerang.domain.events"

    # Transactional Outbox & Dispatcher
    OUTBOX_POLL_INTERVAL_SECONDS: float = Field(default=1.0, gt=0)
    OUTBOX_BATCH_SIZE: int = Field(default=50, ge=1, le=1000)
    OUTBOX_MAX_RETRIES: int = Field(default=5, ge=1)
    OUTBOX_INITIAL_RETRY_DELAY_SECONDS: float = Field(default=1.0, gt=0)
    OUTBOX_MAX_RETRY_DELAY_SECONDS: float = Field(default=60.0, gt=0)
    OUTBOX_BACKOFF_MULTIPLIER: float = Field(default=2.0, ge=1.0)
    OUTBOX_STALE_PROCESSING_SECONDS: float = Field(default=300.0, gt=0)

    # Event Consumer Foundation
    CONSUMER_DEFAULT_GROUP_ID: str = "boomerang-consumer-group"
    CONSUMER_POLL_TIMEOUT_SECONDS: float = Field(default=1.0, gt=0)
    CONSUMER_MAX_POLL_RECORDS: int = Field(default=50, ge=1, le=1000)
    CONSUMER_MAX_RETRIES: int = Field(default=3, ge=1)
    CONSUMER_INITIAL_RETRY_DELAY_SECONDS: float = Field(default=0.5, gt=0)
    CONSUMER_MAX_RETRY_DELAY_SECONDS: float = Field(default=30.0, gt=0)
    CONSUMER_BACKOFF_MULTIPLIER: float = Field(default=2.0, ge=1.0)

    # Firebase Cloud Messaging & Push Dispatcher
    FIREBASE_CREDENTIALS_PATH: str | None = None
    FIREBASE_VAPID_PUBLIC_KEY: str | None = None
    WEB_PUSH_BASE_URL: str = Field(
        default="https://localhost:3000",
        description=(
            "Base URL for Web Push notification click actions. "
            "Must be configured to a valid HTTPS origin in production "
            "(e.g., 'https://app.example.com')."
        ),
    )
    PUSH_DISPATCHER_ENABLED: bool = False
    PUSH_DISPATCHER_POLL_INTERVAL_SECONDS: float = Field(default=2.0, gt=0)
    PUSH_DISPATCHER_BATCH_SIZE: int = Field(default=50, ge=1, le=500)
    PUSH_DISPATCHER_MAX_RETRIES: int = Field(default=3, ge=1)
    PUSH_DISPATCHER_INITIAL_RETRY_DELAY_SECONDS: float = Field(default=2.0, gt=0)
    PUSH_DISPATCHER_MAX_RETRY_DELAY_SECONDS: float = Field(default=300.0, gt=0)
    PUSH_DISPATCHER_BACKOFF_MULTIPLIER: float = Field(default=2.0, ge=1.0)
    PUSH_DISPATCHER_STALE_PROCESSING_SECONDS: float = Field(default=300.0, gt=0)

    # Redis & Distributed Rate Limiting
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0)
    RATE_LIMIT_ENABLED: bool = True
    TRUSTED_PROXIES: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])

    # Authentication & API Rate Limits (per minute)
    RATE_LIMIT_LOGIN_IP_LIMIT: int = Field(default=10, ge=1)
    RATE_LIMIT_LOGIN_ACCOUNT_LIMIT: int = Field(default=5, ge=1)
    RATE_LIMIT_REGISTER_IP_LIMIT: int = Field(default=5, ge=1)
    RATE_LIMIT_REPORTS_ANONYMOUS_LIMIT: int = Field(default=10, ge=1)
    RATE_LIMIT_REPORTS_AUTHENTICATED_LIMIT: int = Field(default=30, ge=1)

    # Authoritative Report Quotas (PostgreSQL)
    QUOTA_TIMEZONE: str = "Asia/Kolkata"
    MISSING_REPORT_DAILY_LIMIT: int = Field(default=5, ge=1)
    MISSING_REPORT_ACTIVE_LIMIT: int = Field(default=10, ge=1)
    FOUND_REPORT_DAILY_LIMIT_NEW: int = Field(default=5, ge=1)
    FOUND_REPORT_DAILY_LIMIT_ESTABLISHED: int = Field(default=15, ge=1)
    FOUND_REPORT_DAILY_LIMIT_TRUSTED: int = Field(default=30, ge=1)

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        if isinstance(v, (list, tuple)):
            return [str(item).strip() for item in v]
        return ["127.0.0.1", "::1"]

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def sync_database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def async_database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )


settings = Settings()
