from config import Settings


def test_settings_importable():
    s = Settings()
    assert hasattr(s, "neo4j_uri")
    assert hasattr(s, "neo4j_user")
    assert hasattr(s, "neo4j_password")
    assert hasattr(s, "anthropic_api_key")
    assert hasattr(s, "google_drive_folder_id")
    assert hasattr(s, "ollama_model")
    assert hasattr(s, "backend_port")
    assert hasattr(s, "jwt_secret_key")
    assert hasattr(s, "trusted_hosts")
    assert hasattr(s, "rate_limit_enabled")


def test_settings_defaults():
    # Test only fields that are not overridden by .env
    s = Settings()
    assert s.backend_port == 8000
    assert s.ollama_model == "llama3.2:3b"
    assert s.frontend_url == "http://localhost:5173"
    assert s.rate_limit_enabled is True
    assert s.rate_limit_default_requests == 120
    assert s.rate_limit_auth_requests == 10
