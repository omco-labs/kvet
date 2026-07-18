from typing import Annotated

from pydantic import Tag

from kvet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicCachingInfo
from kvet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicModelInfo
from kvet.imbue_core.agents.llm_apis.openai_data_types import OpenAICachingInfo
from kvet.imbue_core.agents.llm_apis.openai_data_types import OpenAIModelInfo
from kvet.imbue_core.pydantic_serialization import build_discriminator

ProviderSpecificModelInfoUnion = Annotated[
    Annotated[AnthropicModelInfo, Tag("AnthropicModelInfo")] | Annotated[OpenAIModelInfo, Tag("OpenAIModelInfo")],
    build_discriminator(),
]

ProviderSpecificCachingInfoUnion = Annotated[
    Annotated[AnthropicCachingInfo, Tag("AnthropicCachingInfo")]
    | Annotated[OpenAICachingInfo, Tag("OpenAICachingInfo")],
    build_discriminator(),
]
