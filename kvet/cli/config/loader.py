from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import ValidationError

from kvet.cli.config.cli_config_schema import CliConfigPreset
from kvet.cli.config.cli_config_schema import merge_presets
from kvet.cli.config.cli_config_schema import parse_cli_config_from_dict
from kvet.cli.config.schema import ModelsConfig
from kvet.cli.config.schema import ProviderConfig
from kvet.imbue_core.data_types import CustomGuideConfig
from kvet.imbue_core.data_types import CustomGuidesConfig
from kvet.imbue_core.data_types import get_valid_issue_code_values


class ConfigLoadError(Exception):
    pass


def get_xdg_config_home() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config)
    return Path.home() / ".config"


def find_git_repo_root(start_path: Path) -> Path | None:
    current = start_path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    if (current / ".git").exists():
        return current
    return None


def _get_config_file_paths(
    global_subpath: str,
    global_filename: str,
    project_filename: str,
    repo_path: Path | None = None,
) -> list[Path]:
    paths = [get_xdg_config_home() / global_subpath / global_filename]

    if repo_path:
        git_root = find_git_repo_root(repo_path)
        root = git_root if git_root else repo_path
        paths.append(root / ".kvet" / project_filename)

    return paths


def get_config_file_paths(repo_path: Path | None = None) -> list[Path]:
    return _get_config_file_paths("kvet", "models.json", "models.json", repo_path)


def _load_single_config_file(config_path: Path) -> ModelsConfig:
    try:
        with open(config_path) as f:
            return ModelsConfig.model_validate_json(f.read())
    except ValidationError as e:
        raise ConfigLoadError(f"Invalid configuration in {config_path}: {e}") from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read {config_path}: {e}") from e


def load_models_config(repo_path: Path | None = None) -> ModelsConfig:
    merged_providers: dict[str, ProviderConfig] = {}

    for config_path in get_config_file_paths(repo_path):
        if config_path.exists():
            config = _load_single_config_file(config_path)
            merged_providers.update(config.providers)

    return ModelsConfig(providers=merged_providers)


def get_model_ids_from_config(config: ModelsConfig) -> set[str]:
    return {mid for provider in config.providers.values() for mid in provider.models}


def get_provider_for_model(model_id: str, config: ModelsConfig) -> ProviderConfig | None:
    for provider in config.providers.values():
        if model_id in provider.models:
            return provider
    return None


def get_models_by_provider_from_config(config: ModelsConfig) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for provider_id, provider in config.providers.items():
        display_name = provider.name or provider_id
        result[display_name] = list(provider.models.keys())
    return result


def get_cli_config_file_paths(repo_path: Path | None = None) -> list[Path]:
    return _get_config_file_paths("kvet", "configs.toml", "configs.toml", repo_path)


def _load_cli_config_file(config_path: Path) -> dict[str, CliConfigPreset]:
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return parse_cli_config_from_dict(data)
    except tomllib.TOMLDecodeError as e:
        raise ConfigLoadError(f"Invalid TOML in {config_path}: {e}") from e
    except ValidationError as e:
        raise ConfigLoadError(f"Invalid configuration in {config_path}: {e}") from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read {config_path}: {e}") from e


def load_cli_config(repo_path: Path | None = None) -> dict[str, CliConfigPreset]:
    merged_configs: dict[str, CliConfigPreset] = {}

    for config_path in get_cli_config_file_paths(repo_path):
        if config_path.exists():
            file_configs = _load_cli_config_file(config_path)
            for name, preset in file_configs.items():
                if name in merged_configs:
                    merged_configs[name] = merge_presets(merged_configs[name], preset)
                else:
                    merged_configs[name] = preset

    return merged_configs


def get_config_preset(
    config_name: str,
    cli_configs: dict[str, CliConfigPreset],
    repo_path: Path | None = None,
) -> CliConfigPreset:
    if config_name not in cli_configs:
        available = sorted(cli_configs.keys())
        if available:
            raise ConfigLoadError(f"Configuration '{config_name}' not found. Available configs: {', '.join(available)}")
        else:
            paths = get_cli_config_file_paths(repo_path)
            paths_list = "\n".join(f"  - {p} ({'global' if i == 0 else 'project'})" for i, p in enumerate(paths))
            raise ConfigLoadError(
                f"Configuration '{config_name}' not found.\n\n"
                f"No configuration files found. Create a config at one of these locations:\n{paths_list}"
            )
    return cli_configs[config_name]


def get_guides_config_file_paths(repo_path: Path | None = None) -> list[Path]:
    return _get_config_file_paths("kvet", "guides.toml", "guides.toml", repo_path)


def _load_single_guides_file(config_path: Path) -> CustomGuidesConfig:
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigLoadError(f"Invalid TOML in {config_path}: {e}") from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read {config_path}: {e}") from e

    all_issue_code_values = get_valid_issue_code_values()
    guides: dict[str, CustomGuideConfig] = {}
    for key, value in data.items():
        if key not in all_issue_code_values:
            raise ConfigLoadError(
                f"Unknown issue code '{key}' in {config_path}. " f"Use --list-issue-codes to see valid codes."
            )
        if not isinstance(value, dict):
            raise ConfigLoadError(f"Expected a table for '{key}' in {config_path}, got {type(value).__name__}")
        try:
            guides[key] = CustomGuideConfig.model_validate(value)
        except ValidationError as e:
            raise ConfigLoadError(f"Invalid guide configuration for '{key}' in {config_path}: {e}") from e

    return CustomGuidesConfig(guides=guides)


def load_custom_guides_config(repo_path: Path | None = None) -> CustomGuidesConfig:
    merged_guides: dict[str, CustomGuideConfig] = {}

    for config_path in get_guides_config_file_paths(repo_path):
        if config_path.exists():
            config = _load_single_guides_file(config_path)
            merged_guides.update(config.guides)

    return CustomGuidesConfig(guides=merged_guides)
