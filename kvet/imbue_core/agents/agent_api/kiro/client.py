import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from kvet.imbue_core.agents.agent_api.client import RealAgentClient
from kvet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from kvet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from kvet.imbue_core.agents.agent_api.errors import AgentProcessError
from kvet.imbue_core.agents.agent_api.kiro.data_types import KiroOptions
from kvet.imbue_core.agents.agent_api.kiro.message_parser import parse_kiro_message
from kvet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from kvet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions
from kvet.imbue_core.agents.agent_api.transport import AgentTransport

_REQ_ID_INIT = 0
_REQ_ID_SESSION_NEW = 1
_REQ_ID_PROMPT = 2
_REQ_ID_SET_MODE = 3
_REQ_ID_SET_MODEL = 4

# The v2 engine's pinned default agent is "kiro_default"; the v3 engine calls its bundled
# default agent mode "vibe".
_V2_DEFAULT_AGENT = "kiro_default"
_V3_DEFAULT_MODE = "vibe"

_JSONRPC_METHOD_NOT_FOUND = -32601


class KiroClient(RealAgentClient[KiroOptions]):
    """Kiro CLI client implementation.

    Speaks ACP (Agent Client Protocol), JSON-RPC 2.0 over stdio, via `kiro-cli acp`.
    Unlike Claude Code's ACP-adjacent stream-json protocol, Kiro's turn-end signal
    is the JSON-RPC response to the `session/prompt` request itself (carrying a
    `stopReason`), not a separate notification.

    Both the v2 and v3 engines are supported. The v2 engine is configured with CLI flags
    (`--trust-all-tools`, `--model`, `--agent`). The v3 engine rejects those flags, so the
    model and agent mode are set over ACP with `session/set_config_option`, and tool
    permissions are granted by answering the server's `session/request_permission` requests.
    """

    def __init__(self, options: KiroOptions, transport: AgentTransport) -> None:
        super().__init__(options)
        self._transport = transport

    @classmethod
    @contextmanager
    def build(cls, options: KiroOptions) -> Generator[Self, None, None]:
        cmd = cls._build_cli_cmd(options)
        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(cmd=cmd, cwd=options.cwd)
        ) as transport:
            yield cls(options=options, transport=transport)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

        stream = self._transport.receive_messages()

        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": _REQ_ID_INIT,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientCapabilities": {},
                        "clientInfo": {"name": "kvet", "version": "0.1"},
                    },
                }
            ],
            self._options,
        )
        _drain_until_id(stream, _REQ_ID_INIT, self._respond_to_server_request)

        cwd = str(self._options.cwd) if self._options.cwd is not None else str(Path.cwd())
        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": _REQ_ID_SESSION_NEW,
                    "method": "session/new",
                    "params": {"cwd": cwd, "mcpServers": []},
                }
            ],
            self._options,
        )
        session_new_response = _drain_until_id(stream, _REQ_ID_SESSION_NEW, self._respond_to_server_request)
        session_result = session_new_response.get("result", {})
        session_id = session_result.get("sessionId", "")

        session_message = parse_kiro_message(session_new_response)
        if session_message is not None:
            yield session_message

        if self._options.agent_engine == "v3":
            self._configure_v3_session(stream, session_id, session_result)

        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": _REQ_ID_PROMPT,
                    "method": "session/prompt",
                    "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
                }
            ],
            self._options,
        )

        # Kiro streams the response as many small text chunks (e.g. "p", "ong").
        # We accumulate them here and set the concatenation as AgentResultMessage.result
        # below, so kvet's response-extraction logic (which prefers `result` and only
        # falls back to per-block "\n"-joined concatenation) sees the answer intact --
        # the fallback path would inject newlines at arbitrary chunk boundaries.
        response_text = ""
        for data in stream:
            logger.trace(
                "{client_name}: received raw JSON message={data}",
                client_name=type(self).__name__,
                data=data,
            )

            # Requests from the agent carry both an "id" and a "method"; their ids are
            # from the agent's own id space and may collide with ours, so they must be
            # answered and never mistaken for a response to one of our requests.
            if _is_server_request(data):
                self._respond_to_server_request(data)
                continue

            if data.get("id") == _REQ_ID_PROMPT:
                if "error" in data:
                    yield AgentResultMessage(
                        session_id=session_id,
                        is_error=True,
                        result=response_text or None,
                        error=str(data["error"]),
                        original_message=data,
                    )
                    break

                stop_reason = data.get("result", {}).get("stopReason", "")
                is_error = stop_reason != "end_turn"
                yield AgentResultMessage(
                    session_id=session_id,
                    is_error=is_error,
                    result=response_text or None,
                    error=stop_reason if is_error else None,
                    original_message=data,
                )
                break

            message = parse_kiro_message(data)
            if message is None:
                continue

            if isinstance(message, AgentAssistantMessage):
                for block in message.content:
                    if isinstance(block, AgentTextBlock):
                        response_text += block.text

            yield message

        logger.trace(
            "{client_name}: finished calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

    def _configure_v3_session(
        self, stream: Iterator[dict[str, Any]], session_id: str, session_result: dict[str, Any]
    ) -> None:
        """Pin the agent mode and model on a v3 session (the v3 CLI rejects --agent/--model)."""
        mode = self._options.agent
        if mode == _V2_DEFAULT_AGENT:
            mode = _V3_DEFAULT_MODE
        current_mode = session_result.get("modes", {}).get("currentModeId")
        if mode and mode != current_mode:
            self._set_v3_config_option(stream, _REQ_ID_SET_MODE, session_id, "mode", mode)
        if self._options.model:
            self._set_v3_config_option(stream, _REQ_ID_SET_MODEL, session_id, "model", self._options.model)

    def _set_v3_config_option(
        self, stream: Iterator[dict[str, Any]], request_id: int, session_id: str, config_id: str, value: str
    ) -> None:
        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "session/set_config_option",
                    "params": {"sessionId": session_id, "configId": config_id, "value": value},
                }
            ],
            self._options,
        )
        try:
            _drain_until_id(stream, request_id, self._respond_to_server_request)
        except AgentProcessError as e:
            raise AgentProcessError(f"Kiro CLI rejected {config_id}={value!r}: {e}") from e

    def _respond_to_server_request(self, request: dict[str, Any]) -> None:
        """Answer a JSON-RPC request sent by the agent.

        Tool permission requests (`session/request_permission`) are approved, which is
        what `--trust-all-tools` does on the v2 engine. Any other method is rejected as
        unsupported since kvet advertises no client capabilities.
        """
        request_id = request["id"]
        method = request.get("method")
        if method == "session/request_permission":
            params = request.get("params", {})
            option_id = _pick_allow_option_id(params.get("options", []))
            if option_id is None:
                logger.warning("Kiro CLI requested permission with no allow option; cancelling: {}", params)
                outcome: dict[str, Any] = {"outcome": "cancelled"}
            else:
                logger.debug(
                    "Approving Kiro tool permission request: {title}",
                    title=params.get("toolCall", {}).get("title"),
                )
                outcome = {"outcome": "selected", "optionId": option_id}
            response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "result": {"outcome": outcome}}
        else:
            logger.debug("Rejecting unsupported Kiro CLI request: {}", method)
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": _JSONRPC_METHOD_NOT_FOUND, "message": f"Method not supported: {method}"},
            }
        self._transport.send_request([response], self._options)

    @staticmethod
    def _find_cli() -> str:
        """Find Kiro CLI binary."""
        for name in ("kiro-cli", "kiro"):
            cli = shutil.which(name)
            if cli:
                return cli

        locations = [
            Path.home() / ".local/bin/kiro-cli",
            Path("/usr/local/bin/kiro-cli"),
            Path.home() / ".local/bin/kiro",
        ]

        for path in locations:
            if path.exists() and path.is_file():
                return str(path)

        raise AgentCLINotFoundError("Kiro CLI not found. Ensure it is installed and available on your PATH.")

    @classmethod
    def _build_cli_cmd(cls, options: KiroOptions) -> list[str]:
        """Build CLI command with arguments."""
        if options.is_cached:
            # in this case, the cmd should never be used
            cmd = ["CACHED_KIRO_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        cmd = [cli_path, "acp", "--agent-engine", options.agent_engine]
        if options.agent_engine == "v3":
            # The v3 engine rejects --trust-all-tools, --model and --agent. Permissions are
            # granted over ACP and the model/agent are set after session/new.
            return cmd
        cmd.append("--trust-all-tools")
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: KiroOptions) -> list[str]:
        args: list[str] = []
        if options.model:
            args.extend(["--model", options.model])
        if options.agent:
            args.extend(["--agent", options.agent])
        return args


def _is_server_request(data: dict[str, Any]) -> bool:
    """True for a JSON-RPC request from the agent (has both "method" and "id")."""
    return "method" in data and "id" in data


def _pick_allow_option_id(options: list[dict[str, Any]]) -> str | None:
    """Choose the option that allows the tool call once, else any other allow option."""
    for kind in ("allow_once", "allow_always"):
        for option in options:
            if option.get("kind") == kind and "optionId" in option:
                return str(option["optionId"])
    return None


def _drain_until_id(
    stream: Iterator[dict[str, Any]],
    target_id: int,
    on_server_request: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Read from the stream until a JSON-RPC response with the given id arrives.

    Requests from the agent (e.g. permission prompts) are passed to on_server_request
    and never matched against target_id, since the agent's request ids can collide with ours.

    Raises AgentProcessError if a JSON-RPC error response for that id arrives instead
    (e.g. an auth failure surfacing before session/new can succeed), or if the stream
    ends without ever producing a response for target_id (e.g. the CLI crashed or
    closed its stdout early).
    """
    for data in stream:
        if _is_server_request(data):
            on_server_request(data)
            continue
        if data.get("id") == target_id:
            if "error" in data:
                raise AgentProcessError(f"Kiro CLI returned an error: {data['error']}")
            return data
    raise AgentProcessError(f"Kiro CLI closed the stream before responding to request id {target_id}")
