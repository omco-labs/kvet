from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from kvet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from kvet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from kvet.imbue_core.agents.agent_api.errors import AgentProcessError
from kvet.imbue_core.agents.agent_api.kiro.client import KiroClient
from kvet.imbue_core.agents.agent_api.kiro.data_types import KIRO_ENGINE_ENV_VAR
from kvet.imbue_core.agents.agent_api.kiro.data_types import KiroOptions

_INIT_RESPONSE = {
    "jsonrpc": "2.0",
    "result": {"protocolVersion": 1, "agentInfo": {"name": "Kiro CLI Agent", "version": "2.11.1"}},
    "id": 0,
}
_SESSION_NEW_RESPONSE = {
    "jsonrpc": "2.0",
    "result": {"sessionId": "sess-1", "modes": {"currentModeId": "vibe"}},
    "id": 1,
}
_SESSION_NEW_RESPONSE_OTHER_MODE = {
    "jsonrpc": "2.0",
    "result": {"sessionId": "sess-1", "modes": {"currentModeId": "some-custom-agent"}},
    "id": 1,
}


def _make_mock_transport(events: list[dict]) -> MagicMock:
    mock_transport = MagicMock()
    mock_transport.receive_messages.return_value = iter(events)
    mock_transport.send_request = MagicMock()
    mock_transport.__enter__ = MagicMock(return_value=mock_transport)
    mock_transport.__exit__ = MagicMock(return_value=False)
    return mock_transport


class TestFindCli:
    def test_finds_via_which_kiro_cli(self) -> None:
        with patch("shutil.which", side_effect=lambda name: "/usr/bin/kiro-cli" if name == "kiro-cli" else None):
            assert KiroClient._find_cli() == "/usr/bin/kiro-cli"

    def test_finds_via_which_kiro_fallback(self) -> None:
        with patch("shutil.which", side_effect=lambda name: "/usr/bin/kiro" if name == "kiro" else None):
            assert KiroClient._find_cli() == "/usr/bin/kiro"

    def test_finds_via_known_paths(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        fake_cli = fake_home / ".local/bin/kiro-cli"
        fake_cli.parent.mkdir(parents=True)
        fake_cli.touch()

        with (
            patch("shutil.which", return_value=None),
            patch(
                "kvet.imbue_core.agents.agent_api.kiro.client.Path.home",
                return_value=fake_home,
            ),
        ):
            assert KiroClient._find_cli() == str(fake_cli)

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch(
                "kvet.imbue_core.agents.agent_api.kiro.client.Path.home",
                return_value=tmp_path / "empty_home",
            ),
        ):
            with pytest.raises(AgentCLINotFoundError, match="Kiro CLI not found"):
                KiroClient._find_cli()


class TestBuildCliCmd:
    def test_v2_command(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v2")
        cmd = KiroClient._build_cli_cmd(options)
        assert cmd == [
            "/usr/bin/kiro-cli",
            "acp",
            "--agent-engine",
            "v2",
            "--trust-all-tools",
            "--agent",
            "kiro_default",
        ]

    def test_v2_with_model(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), model="claude-haiku-4.5", agent_engine="v2")
        cmd = KiroClient._build_cli_cmd(options)
        assert "--model" in cmd
        assert "claude-haiku-4.5" in cmd

    def test_v2_agent_none_omits_flag(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent=None, agent_engine="v2")
        cmd = KiroClient._build_cli_cmd(options)
        assert "--agent" not in cmd

    def test_v3_command_omits_flags_the_v3_engine_rejects(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), model="claude-haiku-4.5", agent_engine="v3")
        cmd = KiroClient._build_cli_cmd(options)
        assert cmd == ["/usr/bin/kiro-cli", "acp", "--agent-engine", "v3"]

    def test_default_engine_is_v3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(KIRO_ENGINE_ENV_VAR, raising=False)
        assert KiroOptions().agent_engine == "v3"

    def test_engine_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(KIRO_ENGINE_ENV_VAR, "v2")
        assert KiroOptions().agent_engine == "v2"

    def test_invalid_engine_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(KIRO_ENGINE_ENV_VAR, "v9")
        with pytest.raises(ValueError, match=KIRO_ENGINE_ENV_VAR):
            KiroOptions()

    def test_cached_placeholder(self) -> None:
        options = KiroOptions(is_cached=True)
        cmd = KiroClient._build_cli_cmd(options)
        assert cmd == ["CACHED_KIRO_EXEC_PLACEHOLDER"]


class TestProcessQuery:
    def test_process_query_yields_normalized_messages(self) -> None:
        prompt_end_response = {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2}
        chunk_1 = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "p"}},
            },
        }
        chunk_2 = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ong"}},
            },
        }
        noise = {"jsonrpc": "2.0", "method": "_kiro.dev/metadata", "params": {"sessionId": "sess-1"}}

        events = [_INIT_RESPONSE, _SESSION_NEW_RESPONSE, noise, chunk_1, chunk_2, prompt_end_response]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "kvet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            messages = list(client.process_query("Reply with exactly the word: pong"))

        assert isinstance(messages[0], AgentSystemMessage)
        assert messages[0].session_id == "sess-1"

        assert isinstance(messages[1], AgentAssistantMessage)
        assert isinstance(messages[1].content[0], AgentTextBlock)
        assert messages[1].content[0].text == "p"

        assert isinstance(messages[2], AgentAssistantMessage)
        assert messages[2].content[0].text == "ong"

        result = messages[-1]
        assert isinstance(result, AgentResultMessage)
        assert result.is_error is False
        assert result.result == "pong"
        assert result.session_id == "sess-1"

    def test_non_end_turn_stop_reason_marks_error(self) -> None:
        prompt_end_response = {"jsonrpc": "2.0", "result": {"stopReason": "refusal"}, "id": 2}
        events = [_INIT_RESPONSE, _SESSION_NEW_RESPONSE, prompt_end_response]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "kvet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            messages = list(client.process_query("test prompt"))

        result = messages[-1]
        assert isinstance(result, AgentResultMessage)
        assert result.is_error is True
        assert result.error == "refusal"

    def test_handshake_error_raises_agent_process_error(self) -> None:
        error_response = {"jsonrpc": "2.0", "error": {"code": -32000, "message": "not authenticated"}, "id": 1}
        events = [_INIT_RESPONSE, error_response]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "kvet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            with pytest.raises(AgentProcessError, match="not authenticated"):
                list(client.process_query("test prompt"))

    def test_stream_closes_before_session_new_response_raises_agent_process_error(self) -> None:
        # The CLI exits (or closes stdout) after initialize but before ever responding
        # to session/new -- the stream ends without a matching id.
        events = [_INIT_RESPONSE]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "kvet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            with pytest.raises(AgentProcessError, match="closed the stream"):
                list(client.process_query("test prompt"))


_PERMISSION_OPTIONS = [
    {"optionId": "accept", "name": "Allow", "kind": "allow_once"},
    {"optionId": "always-accept", "name": "Always allow", "kind": "allow_always"},
    {"optionId": "reject", "name": "Deny", "kind": "reject_once"},
    {"optionId": "always-reject", "name": "Always deny", "kind": "reject_always"},
]


def _permission_request(request_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "session/request_permission",
        "params": {
            "sessionId": "sess-1",
            "toolCall": {"toolCallId": "tool-1", "status": "pending", "title": "Read File"},
            "options": _PERMISSION_OPTIONS,
        },
    }


def _sent_messages(mock_transport: MagicMock) -> list[dict]:
    return [message for call in mock_transport.send_request.call_args_list for message in call.args[0]]


def _run_query(events: list[dict], options: KiroOptions) -> tuple[list, MagicMock]:
    mock_transport = _make_mock_transport(events)
    client = KiroClient(options, mock_transport)
    return list(client.process_query("test prompt")), mock_transport


class TestServerRequests:
    def test_permission_request_is_approved_with_allow_once(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            _permission_request(7),
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        messages, transport = _run_query(events, KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v3"))

        replies = [m for m in _sent_messages(transport) if "result" in m]
        assert replies == [
            {"jsonrpc": "2.0", "id": 7, "result": {"outcome": {"outcome": "selected", "optionId": "accept"}}}
        ]
        assert isinstance(messages[-1], AgentResultMessage)
        assert messages[-1].is_error is False

    def test_permission_request_id_colliding_with_prompt_id_is_not_taken_as_turn_end(self) -> None:
        chunk = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}},
            },
        }
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            _permission_request(_PROMPT_ID),
            chunk,
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": _PROMPT_ID},
        ]
        messages, _ = _run_query(events, KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v3"))

        result = messages[-1]
        assert isinstance(result, AgentResultMessage)
        assert result.is_error is False
        assert result.result == "ok"

    def test_permission_request_id_colliding_with_session_new_id_during_handshake(self) -> None:
        events = [
            _INIT_RESPONSE,
            _permission_request(1),
            _SESSION_NEW_RESPONSE,
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        messages, _ = _run_query(events, KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v3"))
        assert isinstance(messages[0], AgentSystemMessage)
        assert messages[0].session_id == "sess-1"

    def test_permission_request_without_allow_option_is_cancelled(self) -> None:
        request = _permission_request(7)
        request["params"]["options"] = [{"optionId": "reject", "name": "Deny", "kind": "reject_once"}]
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            request,
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        _, transport = _run_query(events, KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v3"))

        replies = [m for m in _sent_messages(transport) if "result" in m]
        assert replies == [{"jsonrpc": "2.0", "id": 7, "result": {"outcome": {"outcome": "cancelled"}}}]

    def test_unsupported_server_request_gets_method_not_found(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            {"jsonrpc": "2.0", "id": 9, "method": "fs/read_text_file", "params": {"path": "/x"}},
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        _, transport = _run_query(events, KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v2"))

        errors = [m for m in _sent_messages(transport) if "error" in m]
        assert len(errors) == 1
        assert errors[0]["id"] == 9
        assert errors[0]["error"]["code"] == -32601


_PROMPT_ID = 2


class TestV3SessionConfiguration:
    @staticmethod
    def _set_config_requests(transport: MagicMock) -> list[dict]:
        return [m for m in _sent_messages(transport) if m.get("method") == "session/set_config_option"]

    def test_v3_sets_model_over_acp(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE_OTHER_MODE,  # not on "vibe", so the mode is switched first
            {"jsonrpc": "2.0", "result": {}, "id": 3},
            {"jsonrpc": "2.0", "result": {}, "id": 4},
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), model="claude-haiku-4.5", agent_engine="v3")
        messages, transport = _run_query(events, options)

        requests = self._set_config_requests(transport)
        assert [(r["params"]["configId"], r["params"]["value"]) for r in requests] == [
            ("mode", "vibe"),
            ("model", "claude-haiku-4.5"),
        ]
        assert all(r["params"]["sessionId"] == "sess-1" for r in requests)
        assert messages[-1].is_error is False

    def test_v3_skips_mode_switch_when_already_on_vibe(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        _, transport = _run_query(events, KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent_engine="v3"))
        assert self._set_config_requests(transport) == []

    def test_v3_passes_custom_agent_as_mode(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            {"jsonrpc": "2.0", "result": {}, "id": 3},
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent="my-agent", agent_engine="v3")
        _, transport = _run_query(events, options)
        requests = self._set_config_requests(transport)
        assert [(r["params"]["configId"], r["params"]["value"]) for r in requests] == [("mode", "my-agent")]

    def test_v3_rejected_model_raises(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            {"jsonrpc": "2.0", "error": {"code": -32602, "message": "unknown model"}, "id": 4},
        ]
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), model="nope", agent_engine="v3")
        with pytest.raises(AgentProcessError, match="rejected model='nope'"):
            _run_query(events, options)

    def test_v2_does_not_send_set_config_option(self) -> None:
        events = [
            _INIT_RESPONSE,
            _SESSION_NEW_RESPONSE,
            {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2},
        ]
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), model="claude-haiku-4.5", agent_engine="v2")
        _, transport = _run_query(events, options)
        assert self._set_config_requests(transport) == []


class TestBuildContextManager:
    def test_build_yields_client(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        mock_transport = _make_mock_transport([_INIT_RESPONSE])

        with patch(
            "kvet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            with KiroClient.build(options) as client:
                assert isinstance(client, KiroClient)
