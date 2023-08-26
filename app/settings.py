from functools import cached_property

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import PostgresDsn, RedisDsn, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key = private_key.public_key()


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", frozen=True)

    DATABASE_DSN: PostgresDsn
    REDIS_DSN: RedisDsn
    PUBLIC_KEY: SecretStr = SecretStr(
        public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    )
    PRIVATE_KEY: SecretStr = SecretStr(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
    )
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
