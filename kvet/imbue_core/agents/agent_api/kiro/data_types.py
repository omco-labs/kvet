import os
from pathlib import Path
from typing import Literal

from pydantic import Field

from kvet.imbue_core.agents.agent_api.data_types import AgentOptions

KiroEngine = Literal["v2", "v3"]

KIRO_ENGINE_ENV_VAR = "KVET_KIRO_ENGINE"
_DEFAULT_KIRO_ENGINE: KiroEngine = "v3"


def _default_kiro_engine() -> KiroEngine:
    """Engine for `kiro-cli acp`; v3 unless overridden via KVET_KIRO_ENGINE (e.g. to fall back to v2)."""
    value = os.environ.get(KIRO_ENGINE_ENV_VAR, _DEFAULT_KIRO_ENGINE)
    if value == "v2":
        return "v2"
    if value == "v3":
        return "v3"
    raise ValueError(f"{KIRO_ENGINE_ENV_VAR} must be 'v2' or 'v3', got {value!r}")


class KiroOptions(AgentOptions):
    """Query options for the Kiro CLI (ACP) harness."""

    object_type: Literal["KiroOptions"] = "KiroOptions"

    model: str | None = None
    # Kiro agent config to pin. session/new otherwise inherits whatever agent
    # mode the user has locally configured as current (e.g. a custom compressed-
    # output mode), which can corrupt the judge's JSON response contract.
    # "kiro_default" is the v2 name; on the v3 engine it maps to the bundled "vibe" mode.
    agent: str | None = "kiro_default"
    cli_path: Path | None = None
    is_cached: bool = False
    # Which Kiro agent engine `kiro-cli acp` runs. The v3 engine rejects the --model,
    # --agent and --trust-* flags, so kvet configures it over ACP instead (see KiroClient).
    agent_engine: KiroEngine = Field(default_factory=_default_kiro_engine)
