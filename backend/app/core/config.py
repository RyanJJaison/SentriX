from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-only-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""

    rescore_interval_minutes: int = 5

    audit_log_path: str = "audit.log"


settings = Settings()
