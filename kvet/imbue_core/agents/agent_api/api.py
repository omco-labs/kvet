from __future__ import annotations

from contextlib import contextmanager
from functools import singledispatch
from pathlib import Path
from typing import Any
from typing import ContextManager
from typing import Iterator

from kvet.imbue_core.agents.agent_api.client import AgentClient
from kvet.imbue_core.agents.agent_api.client import AgentOptionsT
from kvet.imbue_core.agents.agent_api.client import CachedAgentClient
from kvet.imbue_core.agents.agent_api.data_types import AgentOptions
from kvet.imbue_core.agents.agent_api.kiro.client import KiroClient
from kvet.imbue_core.agents.agent_api.kiro.data_types import KiroOptions


@singledispatch
def _build_client_from_options(
    options: AgentOptions,
) -> ContextManager[AgentClient[Any]]:
    """Return a context manager that builds an AgentClient for the given options."""
    raise ValueError(f"Unsupported agent options type: {type(options).__name__}")


@_build_client_from_options.register
def _(options: KiroOptions) -> ContextManager[AgentClient[KiroOptions]]:
    return KiroClient.build(options)


@contextmanager
def get_agent_client(
    *,
    options: AgentOptionsT,
    cache_path: Path | None = None,
) -> Iterator[AgentClient[AgentOptionsT]]:
    """Build and manage the lifecycle of an AgentClient based on the provided options.

    Args:
        options: AgentOptions instance describing which agent to run.
        cache_path: Optional path to use for caching agent interactions.

    Yields:
        An AgentClient (or CachedAgentClient) bound to the selected agent implementation.
    """

    with _build_client_from_options(options) as client:
        if cache_path is None:
            yield client
            return

        yield CachedAgentClient(client, cache_path)
