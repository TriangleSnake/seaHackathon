from app.settings import Settings


def test_detection_model_defaults_to_logprobs_capable_model(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    assert Settings.from_env().openai_model == "gpt-4.1-mini"
