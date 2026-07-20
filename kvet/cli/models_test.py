from __future__ import annotations

import pytest

from kvet.cli.config.schema import ModelConfig
from kvet.cli.config.schema import ModelsConfig
from kvet.cli.config.schema import ProviderConfig
from kvet.cli.models import get_all_model_ids
from kvet.cli.models import get_models_by_provider
from kvet.cli.models import is_valid_model_id
from kvet.cli.models import validate_model_id

SAMPLE_USER_CONFIG = ModelsConfig(
    providers={
        "custom": ProviderConfig(
            base_url="http://localhost:8080/v1",
            api_key_env="CUSTOM_KEY",
            models={
                "my-custom-model": ModelConfig(
                    context_window=128000,
                    max_output_tokens=16384,
                    supports_temperature=True,
                ),
                "another-model": ModelConfig(
                    context_window=128000,
                    max_output_tokens=16384,
                    supports_temperature=True,
                ),
            },
        )
    }
)


def test_get_all_model_ids_is_empty_without_config() -> None:
    assert get_all_model_ids(user_config=None) == set()


def test_get_all_model_ids_returns_user_defined_models_only() -> None:
    all_ids = get_all_model_ids(SAMPLE_USER_CONFIG)

    assert all_ids == {"my-custom-model", "another-model"}


def test_builtin_remote_models_are_not_valid() -> None:
    # Remote builtin model IDs (e.g. Anthropic/OpenAI/Gemini) are no longer part
    # of the allowed surface; only user-configured localhost models are valid.
    for remote_id in ("claude-opus-4-8", "gpt-5.1", "gemini-2.5-pro"):
        assert is_valid_model_id(remote_id, SAMPLE_USER_CONFIG) is False


@pytest.mark.parametrize(
    ("model_id", "user_config", "expected"),
    [
        ("my-custom-model", SAMPLE_USER_CONFIG, True),
        ("another-model", SAMPLE_USER_CONFIG, True),
        ("nonexistent-model-xyz", SAMPLE_USER_CONFIG, False),
        ("my-custom-model", None, False),
    ],
)
def test_is_valid_model_id(model_id: str, user_config: ModelsConfig | None, expected: bool) -> None:
    assert is_valid_model_id(model_id, user_config) is expected


def test_validate_model_id_returns_model_id_when_valid() -> None:
    result = validate_model_id("my-custom-model", SAMPLE_USER_CONFIG)
    assert result == "my-custom-model"


def test_validate_model_id_raises_for_invalid_model() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_model_id("nonexistent-model-xyz", SAMPLE_USER_CONFIG)

    assert "Unknown model: nonexistent-model-xyz" in str(exc_info.value)
    assert "localhost" in str(exc_info.value)
    assert "--agentic" in str(exc_info.value)
    assert "--list-models" in str(exc_info.value)


def test_get_models_by_provider_is_empty_without_config() -> None:
    assert get_models_by_provider(user_config=None) == {}


def test_get_models_by_provider_returns_user_defined_providers() -> None:
    user_config = ModelsConfig(
        providers={
            "ollama": ProviderConfig(
                name="Ollama Local",
                base_url="http://localhost:11434/v1",
                api_key_env="OLLAMA_KEY",
                models={
                    "llama3.2:latest": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                    "qwen:7b": ModelConfig(
                        context_window=32768,
                        max_output_tokens=8192,
                        supports_temperature=True,
                    ),
                },
            )
        }
    )

    providers = get_models_by_provider(user_config)

    assert set(providers.keys()) == {"Ollama Local"}
    assert set(providers["Ollama Local"]) == {"llama3.2:latest", "qwen:7b"}
