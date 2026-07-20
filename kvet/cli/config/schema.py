from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationInfo
from pydantic import field_validator

ApiType = Literal["openai_compatible"]

# kvet only allows OpenAI-compatible providers whose base_url points at localhost.
# All remote API providers (Anthropic, OpenAI, Groq, Zen, OpenRouter, Gemini, etc.)
# are disallowed; use agentic mode (the Kiro CLI) for anything else.
_LOCALHOST_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str | None = None
    context_window: int
    max_output_tokens: int
    supports_temperature: bool


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    api_type: ApiType = "openai_compatible"
    base_url: str
    api_key_env: str | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _require_localhost_base_url(cls, base_url: str, info: ValidationInfo) -> str:
        hostname = urlparse(base_url).hostname
        if hostname not in _LOCALHOST_HOSTNAMES:
            provider_label = info.data.get("name") or "<unnamed provider>"
            raise ValueError(
                f"Provider '{provider_label}' has base_url '{base_url}', which is not localhost. "
                "kvet only allows OpenAI-compatible providers running on localhost "
                "(localhost, 127.0.0.1, or [::1]); remote API providers are not supported. "
                "Use --agentic to run analysis through the Kiro CLI instead."
            )
        return base_url


class ModelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
