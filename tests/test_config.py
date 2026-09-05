from forge_astra.config import Settings


def test_credentials_accept_constructor_and_environment_aliases(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")
    assert Settings(_env_file=None).llm_api_key.get_secret_value() == "fallback-key"
    monkeypatch.setenv("ASTRA_LLM_API_KEY", "astra-key")
    assert Settings(_env_file=None).llm_api_key.get_secret_value() == "astra-key"
    explicit = Settings(_env_file=None, llm_api_key="constructor-key")
    assert explicit.llm_api_key.get_secret_value() == "constructor-key"
