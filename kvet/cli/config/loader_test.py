from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from kvet.cli.config.loader import ConfigLoadError
from kvet.cli.config.loader import _load_single_config_file
from kvet.cli.config.loader import find_git_repo_root
from kvet.cli.config.loader import get_config_file_paths
from kvet.cli.config.loader import get_model_ids_from_config
from kvet.cli.config.loader import get_models_by_provider_from_config
from kvet.cli.config.loader import get_provider_for_model
from kvet.cli.config.loader import get_xdg_config_home
from kvet.cli.config.loader import load_models_config
from kvet.cli.config.schema import ModelConfig
from kvet.cli.config.schema import ModelsConfig
from kvet.cli.config.schema import ProviderConfig
from kvet.cli.models import MissingProviderAPIKeyError
from kvet.cli.models import build_language_model_config
from kvet.cli.models import get_max_output_tokens_for_model
from kvet.cli.models import validate_api_key_for_model


def test_get_xdg_config_home_uses_env_var(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        assert get_xdg_config_home() == tmp_path


def test_get_xdg_config_home_defaults_to_home_config() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("XDG_CONFIG_HOME", None)
        result = get_xdg_config_home()
        assert result == Path.home() / ".config"


def test_find_git_repo_root_finds_root(tmp_path: Path) -> None:
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    subdir = git_root / "src" / "deep" / "nested"
    subdir.mkdir(parents=True)

    result = find_git_repo_root(subdir)
    assert result == git_root


def test_find_git_repo_root_returns_none_when_not_in_repo(tmp_path: Path) -> None:
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()

    result = find_git_repo_root(non_repo)
    assert result is None


def test_get_config_file_paths_returns_global_path(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        paths = get_config_file_paths(repo_path=None)
        assert len(paths) == 1
        assert paths[0] == tmp_path / "kvet" / "models.json"


def test_get_config_file_paths_finds_git_root(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    subdir = git_root / "src" / "submodule"
    subdir.mkdir(parents=True)

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        paths = get_config_file_paths(repo_path=subdir)
        assert len(paths) == 2
        assert paths[0] == xdg_config / "kvet" / "models.json"
        assert paths[1] == git_root / ".kvet" / "models.json"


def test_load_single_config_file_loads_valid_config(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "test-provider": {
                "name": "Test Provider",
                "api_type": "openai_compatible",
                "base_url": "http://localhost:8080/v1",
                "api_key_env": "TEST_API_KEY",
                "models": {
                    "test-model": {
                        "model_id": "test-model-v1",
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    result = _load_single_config_file(config_file)

    assert "test-provider" in result.providers
    provider = result.providers["test-provider"]
    assert provider.name == "Test Provider"
    assert provider.base_url == "http://localhost:8080/v1"
    assert provider.api_key_env == "TEST_API_KEY"
    assert "test-model" in provider.models
    assert provider.models["test-model"].model_id == "test-model-v1"


def test_load_single_config_file_raises_on_invalid_json(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_file.write_text("not valid json")

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "Invalid JSON" in str(exc_info.value)


def test_load_single_config_file_raises_on_invalid_schema(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "test-provider": {
                "name": "Test Provider",
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "Invalid configuration" in str(exc_info.value)


def test_load_single_config_file_raises_on_invalid_api_type(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "test-provider": {
                "name": "Test Provider",
                "api_type": "anthropic",
                "base_url": "http://localhost:8080/v1",
                "api_key_env": "TEST_API_KEY",
                "models": {},
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "Invalid configuration" in str(exc_info.value)


def test_load_models_config_returns_empty_when_no_files_exist(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_models_config(repo_path=tmp_path)
        assert result.providers == {}


def test_load_models_config_loads_project_config(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    vet_dir = repo_path / ".kvet"
    vet_dir.mkdir()
    config_file = vet_dir / "models.json"
    config_data = {
        "providers": {
            "project-provider": {
                "base_url": "http://localhost:8081/v1",
                "api_key_env": "PROJECT_KEY",
                "models": {
                    "project-model": {
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_models_config(repo_path=repo_path)

    assert "project-provider" in result.providers


def test_load_models_config_project_overrides_global(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    (xdg_config / "kvet").mkdir(parents=True)
    global_config = xdg_config / "kvet" / "models.json"
    global_config.write_text(
        json.dumps(
            {
                "providers": {
                    "shared-provider": {
                        "name": "Global Name",
                        "base_url": "http://localhost:8080/v1",
                        "api_key_env": "GLOBAL_KEY",
                        "models": {
                            "global-model": {
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                                "supports_temperature": True,
                            }
                        },
                    }
                }
            }
        )
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".kvet").mkdir()
    project_config = repo_path / ".kvet" / "models.json"
    project_config.write_text(
        json.dumps(
            {
                "providers": {
                    "shared-provider": {
                        "name": "Project Name",
                        "base_url": "http://localhost:8081/v1",
                        "api_key_env": "PROJECT_KEY",
                        "models": {
                            "project-model": {
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                                "supports_temperature": True,
                            }
                        },
                    }
                }
            }
        )
    )

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        result = load_models_config(repo_path=repo_path)

    assert result.providers["shared-provider"].name == "Project Name"
    assert result.providers["shared-provider"].base_url == "http://localhost:8081/v1"


# ---------------------------------------------------------------------------
# Localhost-only model policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8080/v1",
        "http://localhost/v1",
        "https://localhost:11434/v1",
        "http://127.0.0.1:8080/v1",
        "https://127.0.0.1/v1",
        "http://[::1]:8080/v1",
        "https://[::1]/v1",
    ],
)
def test_provider_config_accepts_localhost_base_urls(base_url: str) -> None:
    provider = ProviderConfig(base_url=base_url)
    assert provider.base_url == base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com/v1",
        "https://api.remote-llm-provider.example/v1/",
        "http://remote:8080/v1",
        "http://192.168.1.10:8080/v1",
        "http://10.0.0.5/v1",
        "https://[2001:db8::1]:8080/v1",
        "http://localhost.example.com/v1",
    ],
)
def test_provider_config_rejects_remote_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProviderConfig(base_url=base_url)
    assert "localhost" in str(exc_info.value)
    assert "--agentic" in str(exc_info.value)


def test_load_single_config_file_rejects_remote_provider(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "remote-provider": {
                "name": "Remote Provider",
                "base_url": "https://api.example.com/v1",
                "api_key_env": "REMOTE_KEY",
                "models": {
                    "remote-model": {
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "localhost" in str(exc_info.value)


def test_get_model_ids_from_config_extracts_all_ids() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="KEY1",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                    "model-b": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                },
            ),
            "provider2": ProviderConfig(
                base_url="http://localhost:8081/v1",
                api_key_env="KEY2",
                models={
                    "model-c": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                },
            ),
        }
    )

    result = get_model_ids_from_config(config)

    assert result == {"model-a", "model-b", "model-c"}


def test_get_provider_for_model_finds_provider() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="KEY1",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
            "provider2": ProviderConfig(
                base_url="http://localhost:8081/v1",
                api_key_env="KEY2",
                models={
                    "model-b": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    result = get_provider_for_model("model-b", config)

    assert result is not None
    assert result.api_key_env == "KEY2"


def test_get_provider_for_model_returns_none_for_unknown() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="KEY1",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    result = get_provider_for_model("unknown-model", config)

    assert result is None


def test_validate_api_key_passes_when_key_is_set() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                name="Test Provider",
                base_url="http://localhost:8080/v1",
                api_key_env="TEST_API_KEY",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    with patch.dict(os.environ, {"TEST_API_KEY": "secret-key"}):
        validate_api_key_for_model("model-a", config)


def test_validate_api_key_raises_when_key_not_set() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                name="Test Provider",
                base_url="http://localhost:8080/v1",
                api_key_env="MISSING_KEY",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("MISSING_KEY", None)
        with pytest.raises(MissingProviderAPIKeyError) as exc_info:
            validate_api_key_for_model("model-a", config)

        assert exc_info.value.env_var == "MISSING_KEY"
        assert exc_info.value.model_id == "model-a"
        assert "MISSING_KEY" in str(exc_info.value)


def test_validate_api_key_passes_for_unknown_model() -> None:
    config = ModelsConfig(providers={})
    validate_api_key_for_model("unknown-model", config)


def test_get_models_by_provider_groups_models() -> None:
    config = ModelsConfig(
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
            ),
            "vllm": ProviderConfig(
                base_url="http://localhost:8000/v1",
                api_key_env="VLLM_KEY",
                models={
                    "local/custom-model": ModelConfig(
                        context_window=200000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                },
            ),
        }
    )

    result = get_models_by_provider_from_config(config)

    assert "Ollama Local" in result
    assert set(result["Ollama Local"]) == {"llama3.2:latest", "qwen:7b"}

    assert "vllm" in result
    assert result["vllm"] == ["local/custom-model"]


def _make_provider(base_url: str, model_id: str, api_key_env: str | None = None) -> ProviderConfig:
    return ProviderConfig(
        base_url=base_url,
        api_key_env=api_key_env,
        models={
            model_id: ModelConfig(
                context_window=128000,
                max_output_tokens=16384,
                supports_temperature=True,
            )
        },
    )


def test_build_config_returns_openai_compatible_config() -> None:
    from kvet.imbue_core.agents.configs import OpenAICompatibleModelConfig

    user_config = ModelsConfig(providers={"custom": _make_provider("http://localhost:8080/v1", "my-model")})

    result = build_language_model_config("my-model", user_config)
    assert isinstance(result, OpenAICompatibleModelConfig)
    assert result.custom_base_url == "http://localhost:8080/v1"
    assert result.model_name == "my-model"


def test_build_config_uses_model_id_override() -> None:
    user_config = ModelsConfig(
        providers={
            "custom": ProviderConfig(
                base_url="http://localhost:8080/v1",
                models={
                    "friendly-name": ModelConfig(
                        model_id="upstream/actual-model",
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            )
        }
    )

    result = build_language_model_config("friendly-name", user_config)
    assert result.model_name == "upstream/actual-model"


def test_build_config_raises_for_unknown_model() -> None:
    user_config = ModelsConfig(providers={})
    with pytest.raises(AssertionError):
        build_language_model_config("totally-unknown", user_config)


def test_get_max_output_tokens_for_user_model() -> None:
    user_config = ModelsConfig(
        providers={
            "user": ProviderConfig(
                base_url="http://localhost:8080/v1",
                models={
                    "user-model": ModelConfig(
                        context_window=128000,
                        max_output_tokens=32768,
                        supports_temperature=True,
                    )
                },
            )
        }
    )

    result = get_max_output_tokens_for_model("user-model", user_config)
    assert result == 32768


def test_get_max_output_tokens_returns_none_for_unknown_model() -> None:
    user_config = ModelsConfig(providers={})
    result = get_max_output_tokens_for_model("unknown-model", user_config)
    assert result is None
