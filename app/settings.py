from functools import cached_property

from pydantic import PostgresDsn, RedisDsn, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", frozen=True)

    DATABASE_DSN: PostgresDsn
    REDIS_DSN: RedisDsn
    PUBLIC_KEY: SecretStr
    PRIVATE_KEY: SecretStr
    MAX_MATCHING_TIMEOUT: float = 6.7
    JWT_LIFETIME: int = 3600

    @computed_field  # type: ignore[misc]
    @cached_property
    def REDIS_URL(self) -> str:
        return self.REDIS_DSN.unicode_string()

    @computed_field  # type: ignore[misc]
    @cached_property
    def DATABASE_URL(self) -> str:
        return self.DATABASE_DSN.unicode_string()
