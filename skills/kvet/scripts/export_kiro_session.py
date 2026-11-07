#!/usr/bin/env python3
"""Export a Kiro CLI session transcript in the format kvet's --history-loader expects.

Supports both transcript formats written by the Kiro CLI:

* v3 engine: ~/.kiro/sessions/<workspace-hash>/sess_<uuid>/messages.jsonl
  (one `{"payload": {"type": "user" | "assistant" | "tool_call" | "tool_result" | ...}}` per line)
* v2 engine: ~/.kiro/sessions/cli/<uuid>.jsonl
  (one `{"kind": "Prompt" | "AssistantMessage" | "ToolResults", "data": {...}}` per line)

Usage:
    export_kiro_session.py --session-id <id>        # id from `kiro-cli chat --list-sessions --format json`
    export_kiro_session.py --session-file <path>    # a messages.jsonl or <uuid>.jsonl; format is auto-detected
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SESSIONS_DIR = Path.home() / ".kiro" / "sessions"


def find_session_file(session_id: str) -> Path | None:
    """Locate the transcript for a session id, trying v3 layouts first, then v2."""
    candidates = [session_id]
    if session_id.startswith("sess_"):
        candidates.append(session_id[len("sess_") :])
    else:
        candidates.append(f"sess_{session_id}")

    for candidate in candidates:
        matches = sorted(SESSIONS_DIR.glob(f"*/{candidate}/messages.jsonl"), key=lambda p: p.stat().st_mtime)
        if matches:
            return matches[-1]
    for candidate in candidates:
        v2_path = SESSIONS_DIR / "cli" / f"{candidate}.jsonl"
        if v2_path.exists():
            return v2_path
    return None


class Exporter:
    """Groups session blocks into assistant messages and emits kvet history objects as JSON lines.

    One assistant message is one model step: the results of the previous step's tool calls,
    followed by the text and tool calls the model produced in response. A step ends when the
    first result of its tool calls arrives.
    """

    def __init__(self) -> None:
        # toolUseId -> (tool_name, tool_input), so results can name the tool that produced them
        self.call_info: dict[str, tuple[str, dict[str, Any]]] = {}
        self.blocks: list[dict[str, Any]] = []
        self.msg_counter = 0

    def user_message(self, text: str) -> None:
        self.flush()
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))

    def text(self, text: str) -> None:
        if text:
            self.blocks.append({"object_type": "TextBlock", "type": "text", "text": text})

    def tool_use(self, tool_use_id: str, name: str, tool_input: dict[str, Any]) -> None:
        self.call_info[tool_use_id] = (name, tool_input)
        self.blocks.append(
            {"object_type": "ToolUseBlock", "type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}
        )

    def tool_result(self, tool_use_id: str, text: str) -> None:
        if self.blocks and self.blocks[-1]["object_type"] != "ToolResultBlock":
            self.flush()
        name, tool_input = self.call_info.get(tool_use_id, ("unknown", {}))
        self.blocks.append(
            {
                "object_type": "ToolResultBlock",
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "tool_name": name,
                "invocation_string": f"{name}({json.dumps(tool_input)})",
                "content": {"content_type": "generic", "text": text},
            }
        )

    def flush(self) -> None:
        """Emit the buffered blocks as a single assistant message."""
        blocks, self.blocks = self.blocks, []
        if not blocks:
            return
        self.msg_counter += 1
        print(
            json.dumps(
                {
                    "object_type": "ResponseBlockAgentMessage",
                    "role": "assistant",
                    "assistant_message_id": f"kiro_msg_{self.msg_counter}",
                    "content": blocks,
                }
            )
        )


def content_items_text(content: Any) -> str:
    """Flatten a Kiro content value (string or list of {kind, data} items) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("kind") == "text":
                    parts.append(item.get("data", ""))
                elif item.get("kind") == "json":
                    parts.append(json.dumps(item.get("data")))
                else:
                    parts.append(json.dumps(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(content)


def export_v3(entry: dict[str, Any], out: Exporter) -> None:
    payload = entry.get("payload", {})
    ptype = payload.get("type")

    if ptype == "user":
        content = payload.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("data", "") for c in content if isinstance(c, dict) and c.get("kind") == "text")
        out.user_message(content)
    elif ptype == "assistant":
        # "Reasoning" is the model's internal chain of thought, not part of the conversation.
        if payload.get("operationType") != "Reasoning":
            out.text(payload.get("content", ""))
    elif ptype == "tool_call":
        out.tool_use(
            payload.get("toolCallId", entry.get("id", "")), payload.get("toolName", ""), payload.get("args", {})
        )
    elif ptype == "tool_result":
        out.tool_result(payload.get("toolCallId", ""), content_items_text(payload.get("content", "")))
    # agent_note, turn_start/turn_end, session_metadata, pending_interaction, interaction_resolved,
    # usage_summary, session_event, session_start, steering_inclusion, sub_agent_*: not conversation.


def export_v2(entry: dict[str, Any], out: Exporter) -> None:
    kind = entry.get("kind")
    data = entry.get("data", {})
    content = data.get("content", [])

    if kind == "Prompt":
        out.user_message(" ".join(c.get("data", "") for c in content if c.get("kind") == "text"))
    elif kind == "AssistantMessage":
        for c in content:
            if c.get("kind") == "text":
                out.text(c.get("data", ""))
            elif c.get("kind") == "toolUse":
                tu = c.get("data", {})
                out.tool_use(tu.get("toolUseId", ""), tu.get("name", ""), tu.get("input", {}))
    elif kind == "ToolResults":
        for c in content:
            if c.get("kind") == "toolResult":
                tr = c.get("data", {})
                out.tool_result(tr.get("toolUseId", ""), content_items_text(tr.get("content", [])))
    # OtelSpan and any other/unknown kind: skip


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Kiro CLI session history for kvet")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session-id", help="Kiro CLI session id (a UUID, or sess_<uuid> for the v3 engine)")
    group.add_argument("--session-file", help="Path to a Kiro CLI session .jsonl file (v2 or v3)")
    args = parser.parse_args()

    if args.session_file:
        session_file: Path | None = Path(args.session_file)
    else:
        session_file = find_session_file(args.session_id)

    if session_file is None or not session_file.exists():
        print(f"WARNING: Kiro session file not found: {session_file or args.session_id}", file=sys.stderr)
        sys.exit(0)

    out = Exporter()
    for line in session_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"WARNING: Skipping malformed JSON line in {session_file}: {e}", file=sys.stderr)
            continue

        if "payload" in entry:
            export_v3(entry, out)
        elif "kind" in entry:
            export_v2(entry, out)

    out.flush()


if __name__ == "__main__":
    main()
