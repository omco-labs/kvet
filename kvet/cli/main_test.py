from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from kvet.cli.main import main


def _env_for_isolated_config(tmp_path: Path) -> dict[str, str]:
    """Return env overrides that isolate XDG dirs to tmp_path."""
    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }


def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
    )
    return repo


_LOCALHOST_PROVIDER_JSON = json.dumps(
    {
        "providers": {
            "local": {
                "base_url": "http://localhost:8080/v1",
                "models": {
                    "local-model": {
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
)

_REMOTE_PROVIDER_JSON = json.dumps(
    {
        "providers": {
            "remote": {
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
)


class TestModeSelection:
    """CLI integration tests for agentic-by-default mode selection."""

    def test_no_model_defaults_to_agentic(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                with patch("kvet.api.find_issues", return_value=()) as mock_find_issues:
                    exit_code = main(["test goal", "--repo", str(repo), "--quiet"])

        assert exit_code == 0
        config = mock_find_issues.call_args.kwargs["config"]
        assert config.enabled_identifiers == ("agentic_issue_identifier",)
        assert config.agent_model_name is None
        assert config.language_model_generation_config is None

    def test_explicit_agentic_passes_model_through(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                with patch("kvet.api.find_issues", return_value=()) as mock_find_issues:
                    exit_code = main(
                        ["test goal", "--repo", str(repo), "--quiet", "--agentic", "--model", "any-model-name"]
                    )

        assert exit_code == 0
        config = mock_find_issues.call_args.kwargs["config"]
        assert config.enabled_identifiers == ("agentic_issue_identifier",)
        assert config.agent_model_name == "any-model-name"

    def test_unknown_model_without_agentic_errors(self, tmp_path: Path, capsys) -> None:
        repo = _make_git_repo(tmp_path)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                exit_code = main(["test goal", "--repo", str(repo), "--quiet", "--model", "no-such-model"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Unknown model: no-such-model" in captured.err
        assert "--agentic" in captured.err

    def test_localhost_model_selects_api_mode(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        (repo / ".kvet").mkdir()
        (repo / ".kvet" / "models.json").write_text(_LOCALHOST_PROVIDER_JSON)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                with patch("kvet.api.find_issues", return_value=()) as mock_find_issues:
                    exit_code = main(["test goal", "--repo", str(repo), "--quiet", "--model", "local-model"])

        assert exit_code == 0
        config = mock_find_issues.call_args.kwargs["config"]
        assert config.disabled_identifiers == ("agentic_issue_identifier",)
        assert config.language_model_generation_config is not None
        assert config.language_model_generation_config.custom_base_url == "http://localhost:8080/v1"


class TestRemoteProviderRejection:
    """A remote provider in models.json must be rejected at config-load time."""

    def test_remote_provider_in_models_json_exits_2(self, tmp_path: Path, capsys) -> None:
        repo = _make_git_repo(tmp_path)
        (repo / ".kvet").mkdir()
        (repo / ".kvet" / "models.json").write_text(_REMOTE_PROVIDER_JSON)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                exit_code = main(["test goal", "--repo", str(repo), "--quiet"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "could not load model configuration" in captured.err
        assert "localhost" in captured.err


class TestStagedInteraction:
    """--staged requires API mode (an explicit localhost model)."""

    def test_staged_with_explicit_agentic_errors(self, tmp_path: Path, capsys) -> None:
        repo = _make_git_repo(tmp_path)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                exit_code = main(["test goal", "--repo", str(repo), "--quiet", "--staged", "--agentic"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "--staged and --agentic are mutually exclusive" in captured.err

    def test_staged_without_model_errors(self, tmp_path: Path, capsys) -> None:
        repo = _make_git_repo(tmp_path)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                exit_code = main(["test goal", "--repo", str(repo), "--quiet", "--staged"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "--staged requires API mode" in captured.err

    def test_staged_with_localhost_model_runs_api_mode(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        (repo / ".kvet").mkdir()
        (repo / ".kvet" / "models.json").write_text(_LOCALHOST_PROVIDER_JSON)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            with patch("kvet.cli.main.configure_logging"):
                with patch("kvet.api.find_issues", return_value=()) as mock_find_issues:
                    exit_code = main(
                        ["test goal", "--repo", str(repo), "--quiet", "--staged", "--model", "local-model"]
                    )

        assert exit_code == 0
        assert mock_find_issues.call_args.kwargs["only_staged"] is True


class TestListModels:
    """CLI integration tests for the --list-models flag."""

    def test_list_models_shows_localhost_providers_and_agentic_note(self, tmp_path: Path, capsys) -> None:
        repo = _make_git_repo(tmp_path)
        (repo / ".kvet").mkdir()
        (repo / ".kvet" / "models.json").write_text(_LOCALHOST_PROVIDER_JSON)
        env = _env_for_isolated_config(tmp_path)

        with patch.dict(os.environ, env):
            exit_code = main(["--list-models", "--repo", str(repo)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "local-model" in captured.out
        assert "Kiro CLI" in captured.out


class TestModelRefusal:
    """CLI integration tests for surfacing model refusals."""

    def test_model_refusal_prints_error_and_returns_1(self, tmp_path: Path, capsys) -> None:
        from kvet.imbue_core.agents.llm_apis.errors import ModelRefusalError

        repo = _make_git_repo(tmp_path)
        env = _env_for_isolated_config(tmp_path)
        refusal = ModelRefusalError(
            "The model refused to generate a response (the provider's safety classifiers declined the request)."
        )

        with patch.dict(os.environ, env):
            # configure_logging would tear down the logging handlers installed by test fixtures.
            with patch("kvet.cli.main.configure_logging"):
                with patch("kvet.api.find_issues", side_effect=refusal):
                    exit_code = main(["test goal", "--repo", str(repo), "--quiet"])

        assert exit_code == 1

        captured = capsys.readouterr()
        assert "refused" in captured.err
        assert "try re-running" in captured.err
