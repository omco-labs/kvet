from __future__ import annotations

import os

from kvet.cli.config.loader import get_model_ids_from_config
from kvet.cli.config.loader import get_models_by_provider_from_config
from kvet.cli.config.loader import get_provider_for_model
from kvet.cli.config.schema import ModelsConfig
from kvet.cli.config.schema import ProviderConfig


class MissingProviderAPIKeyError(Exception):
    def __init__(self, env_var: str, provider_name: str, model_id: str) -> None:
        self.env_var = env_var
        self.provider_name = provider_name
        self.model_id = model_id
        super().__init__(
            f"API key not found: environment variable '{env_var}' is not set. "
            + f"This is required for model '{model_id}' from provider '{provider_name}'."
        )


def get_all_model_ids(user_config: ModelsConfig | None = None) -> set[str]:
    if user_config is None:
        return set()
    return get_model_ids_from_config(user_config)


def is_valid_model_id(model_id: str, user_config: ModelsConfig | None = None) -> bool:
    return model_id in get_all_model_ids(user_config)


def validate_model_id(model_id: str, user_config: ModelsConfig | None = None) -> str:
    if not is_valid_model_id(model_id, user_config):
        raise ValueError(
            f"Unknown model: {model_id}. Define it as a localhost provider in models.json, "
            "or use --agentic to pass it to the Kiro CLI. Use --list-models to see available models."
        )
    return model_id


def get_models_by_provider(user_config: ModelsConfig | None = None) -> dict[str, list[str]]:
    if user_config is None:
        return {}
    return get_models_by_provider_from_config(user_config)


def _resolve_provider(model_id: str, user_config: ModelsConfig) -> ProviderConfig | None:
    return get_provider_for_model(model_id, user_config)


def validate_api_key_for_model(model_id: str, user_config: ModelsConfig) -> None:
    provider = _resolve_provider(model_id, user_config)

    if provider is None:
        return

    api_key_env = provider.api_key_env
    if api_key_env is None:
        return

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        provider_name = provider.name or "unknown provider"
        raise MissingProviderAPIKeyError(
            env_var=api_key_env,
            provider_name=provider_name,
            model_id=model_id,
        )


def get_max_output_tokens_for_model(model_id: str, user_config: ModelsConfig) -> int | None:
    provider = _resolve_provider(model_id, user_config)
    if provider is not None:
        return provider.models[model_id].max_output_tokens
    return None


def build_language_model_config(model_id: str, user_config: ModelsConfig):
    from kvet.imbue_core.agents.configs import OpenAICompatibleModelConfig

    provider = _resolve_provider(model_id, user_config)
    assert provider is not None, f"No localhost provider configured for model '{model_id}'"

    model_config = provider.models[model_id]
    actual_model_name = model_config.model_id or model_id

    return OpenAICompatibleModelConfig(
        model_name=actual_model_name,
        custom_base_url=provider.base_url,
        custom_api_key_env=provider.api_key_env or "",
        custom_context_window=model_config.context_window,
        custom_max_output_tokens=model_config.max_output_tokens,
        custom_supports_temperature=model_config.supports_temperature,
    )
