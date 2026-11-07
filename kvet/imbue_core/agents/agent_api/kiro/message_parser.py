import json
from typing import Any

from kvet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from kvet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from kvet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from kvet.imbue_core.agents.agent_api.data_types import AgentThinkingBlock
from kvet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from kvet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from kvet.imbue_core.agents.agent_api.data_types import AgentUnknownMessage

_KIRO_PRIVATE_METHOD_PREFIXES = ("_kiro.dev/", "_kiro/")

# "session/update" kinds that carry only UI/bookkeeping state (session title and context
# usage, slash-command lists, mode and config changes) and nothing kvet consumes. Dropped
# so they don't surface as AgentUnknownMessage.
_IGNORED_SESSION_UPDATE_KINDS = frozenset(
    {
        "session_info_update",
        "available_commands_update",
        "current_mode_update",
        "config_option_update",
    }
)


def parse_kiro_message(data: dict[str, Any]) -> AgentMessage | None:
    """Parse a single JSON-RPC line from `kiro-cli acp` into a normalized AgentMessage.

    Handles JSON-RPC responses (have "id") for session/new, and "session/update"
    notifications for streaming content. The initialize response and the prompt
    turn's terminal response (identified by "stopReason" in its result) are
    intentionally not turned into messages here -- the client handles both directly
    since it needs to correlate them with request ids and, for the terminal
    response, with accumulated response text. Kiro-private notifications
    ("_kiro.dev/*" on the v2 engine, "_kiro/*" on v3) and bookkeeping
    "session/update" kinds are dropped. Requests from the agent (which carry both
    an "id" and a "method"; e.g. "session/request_permission") are answered by
    the client and produce no message here.
    """
    if "method" in data and "id" in data:
        return None

    if "id" in data:
        if "result" in data:
            return _parse_response(data.get("result", {}), data)
        if "error" in data:
            return AgentResultMessage(session_id="", is_error=True, error=str(data["error"]), original_message=data)
        return None

    method = data.get("method", "")
    if method == "session/update":
        return _parse_session_update(data)

    if method.startswith(_KIRO_PRIVATE_METHOD_PREFIXES):
        return None

    return AgentUnknownMessage(raw=data, original_message=data)


def _parse_response(result: dict[str, Any], data: dict[str, Any]) -> AgentMessage | None:
    if "sessionId" in result:
        return AgentSystemMessage(
            event_type=AgentSystemEventType.SESSION_STARTED,
            session_id=result["sessionId"],
            original_message=data,
        )
    # initialize response (has "agentInfo") and the prompt turn's terminal
    # response (has "stopReason") are both handled by the client, not here.
    return None


def _parse_session_update(data: dict[str, Any]) -> AgentMessage | None:
    update = data.get("params", {}).get("update", {})
    kind = update.get("sessionUpdate", "")

    if kind in _IGNORED_SESSION_UPDATE_KINDS:
        return None

    if kind == "agent_message_chunk":
        text = update.get("content", {}).get("text", "")
        if not text:
            return None
        return AgentAssistantMessage(content=[AgentTextBlock(text=text)], original_message=data)

    if kind == "agent_thought_chunk":
        text = update.get("content", {}).get("text", "")
        if not text:
            return None
        return AgentAssistantMessage(content=[AgentThinkingBlock(content=text)], original_message=data)

    if kind == "tool_call":
        tool_name = update.get("_meta", {}).get("kiro", {}).get("toolName") or update.get("kind", "")
        return AgentAssistantMessage(
            content=[
                AgentToolUseBlock(
                    id=update.get("toolCallId", ""),
                    name=tool_name,
                    input=update.get("rawInput") or {},
                )
            ],
            original_message=data,
        )

    if kind == "tool_call_update":
        status = update.get("status")
        if status in ("pending", "in_progress"):
            return None
        raw_output = update.get("rawOutput")
        return AgentAssistantMessage(
            content=[
                AgentToolResultBlock(
                    tool_use_id=update.get("toolCallId", ""),
                    content=json.dumps(raw_output) if raw_output is not None else None,
                    is_error=status == "failed",
                )
            ],
            original_message=data,
        )

    return AgentUnknownMessage(raw=data, original_message=data)
