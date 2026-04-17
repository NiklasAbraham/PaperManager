from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the project root (one level above backend/)
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Neo4j
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Google Drive
    google_client_id: str = ""
    google_client_secret: str = ""
    google_drive_folder_id: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # App
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # Ollama
    ollama_model: str = "llama3.2:3b"


settings = Settings()
