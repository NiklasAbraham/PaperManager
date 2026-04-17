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


def test_settings_defaults():
    # Test only fields that are not overridden by .env
    s = Settings()
    assert s.backend_port == 8000
    assert s.ollama_model == "llama3.2:3b"
    assert s.frontend_url == "http://localhost:5173"
