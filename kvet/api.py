"""Public API for kvet.

This module provides functions to identify issues in code changes. Issue identifiers are pieces of logic capable of finding issues in code.
By default, kvet runs all registered issue identifiers and returns all found issues.
"""

from pathlib import Path

from loguru import logger

from kvet.imbue_core.agents.llm_apis.constants import approximate_token_count
from kvet.imbue_core.data_types import IdentifiedVerifyIssue
from kvet.imbue_core.data_types import IssueIdentificationDebugInfo
from kvet.imbue_tools.get_conversation_history.get_conversation_history import ConversationLoadingError
from kvet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from kvet.imbue_tools.repo_utils.project_context import LazyProjectContext
from kvet.imbue_tools.repo_utils.project_context import ProjectContext
from kvet.imbue_tools.types.vet_config import VetConfig
from kvet.imbue_tools.util_prompts.goal_from_conversation import get_goal_from_conversation
from kvet.issue_identifiers import registry
from kvet.issue_identifiers.utils import ReturnCapturingGenerator
from kvet.repo_utils import VET_MAX_PROMPT_TOKENS
from kvet.repo_utils import get_code_to_check
from kvet.vet_types.messages import ConversationMessageUnion

# In agentic mode kvet doesn't know which model the external agent CLI (Kiro) will
# actually use, so there is no LanguageModelGenerationConfig to consult. These are
# only used as a project-context sizing heuristic (how much code to include in the
# snapshot); they are not tied to, and do not imply, any specific remote model.
_AGENTIC_MODE_MODEL_LABEL = "agentic"
_AGENTIC_MODE_CONTEXT_WINDOW_ESTIMATE = 200_000


def get_issues_with_raw_responses(
    base_commit: str,
    diff: str,
    diff_no_binary: str,
    goal: str,
    config: VetConfig,
    repo_path: Path,
    conversation_history: tuple[ConversationMessageUnion, ...] | None = None,
    extra_context: str | None = None,
) -> tuple[tuple[IdentifiedVerifyIssue, ...], IssueIdentificationDebugInfo, ProjectContext]:
    if not goal or not goal.strip():
        logger.debug("No goal was provided, generating one from conversation history")
        # should be not None and not empty
        if conversation_history:
            if config.language_model_generation_config is None:
                # Agentic mode: there's no LanguageModelGenerationConfig to derive a goal
                # with (the Kiro CLI is the authority on models, not kvet). Proceed with
                # no goal rather than guessing at a remote model to call.
                logger.debug(
                    "No language model is configured (agentic mode); skipping goal derivation "
                    "from conversation history. Pass --goal explicitly if one is needed."
                )
                goal = ""
            else:
                try:
                    # TODO: we use the config here, but we may want to configure this separately
                    goal = get_goal_from_conversation(conversation_history, config.language_model_generation_config)
                    logger.debug("Generated goal from conversation history: {}", goal)
                except Exception as e:
                    raise ConversationLoadingError(
                        f"No goal was provided and generating one from conversation history failed: {e}"
                    )
        else:
            # TODO: Consider which CLI options we should show this for (quiet, normal, verbose).
            logger.debug("No goal or conversation history provided, only goal-independent identifiers will run")
            goal = ""

    lm_config = config.language_model_generation_config
    if lm_config is not None:
        language_model_name = lm_config.model_name
        context_window = lm_config.get_max_context_length()
        is_custom_model = lm_config.is_custom_model()
        diff_no_binary_tokens = lm_config.count_tokens(diff_no_binary) if diff_no_binary else 0
    else:
        # Agentic mode: size the project context using an approximation instead of a
        # specific model's tokenizer/context window (see module-level comment above).
        language_model_name = _AGENTIC_MODE_MODEL_LABEL
        context_window = _AGENTIC_MODE_CONTEXT_WINDOW_ESTIMATE
        is_custom_model = True
        diff_no_binary_tokens = approximate_token_count(diff_no_binary) if diff_no_binary else 0

    project_context = LazyProjectContext.build(
        base_commit,
        diff,
        language_model_name=language_model_name,
        repo_path=repo_path,
        # This needs to account for the kvet prompt, as well as the max_tokens output tokens.
        tokens_to_reserve=VET_MAX_PROMPT_TOKENS + diff_no_binary_tokens + config.max_output_tokens,
        context_window=context_window,
        is_custom_model=is_custom_model,
    )

    if conversation_history:
        logger.debug(
            "Passing {} conversation history messages to identifier inputs",
            len(conversation_history),
        )

    identifier_inputs = IdentifierInputs(
        maybe_diff=diff_no_binary or None,
        maybe_goal=goal,
        maybe_conversation_history=conversation_history,
        maybe_extra_context=extra_context,
    )

    results_generator = registry.run(
        identifier_inputs=identifier_inputs,
        project_context=project_context,
        config=config,
    )

    issues = []
    results_generator_with_capture = ReturnCapturingGenerator(results_generator)
    for result in results_generator_with_capture:
        if result.passes_filtration:
            issues.append(result.issue)
    issue_identification_debug_info = results_generator_with_capture.return_value

    return tuple(issues), issue_identification_debug_info, project_context


def find_issues(
    repo_path: Path,
    relative_to: str,
    goal: str,
    config: VetConfig,
    conversation_history: tuple[ConversationMessageUnion, ...] | None = None,
    extra_context: str | None = None,
    only_staged: bool = False,
) -> tuple[IdentifiedVerifyIssue, ...]:
    if only_staged:
        logger.debug(
            "Finding issues in {repo_path} (staged changes)",
            repo_path=repo_path,
        )
    else:
        logger.debug(
            "Finding issues in {repo_path} relative to {relative_to}",
            repo_path=repo_path,
            relative_to=relative_to,
        )

    base_commit, diff, diff_no_binary = get_code_to_check(relative_to, repo_path, only_staged=only_staged)
    if not diff.strip():
        if only_staged:
            logger.debug(
                "No code changes detected in repo {repo_path} for staged changes, skipping issue identification",
                repo_path=repo_path,
            )
        else:
            logger.debug(
                "No code changes detected in repo {repo_path} since the specified relative_to commit {relative_to}, skipping issue identification",
                repo_path=repo_path,
                relative_to=relative_to,
            )
        # No code changes detected, so no issues to find.
        return tuple()

    issues, _, _ = get_issues_with_raw_responses(
        base_commit=base_commit,
        diff=diff,
        diff_no_binary=diff_no_binary,
        goal=goal,
        config=config,
        repo_path=repo_path,
        conversation_history=conversation_history,
        extra_context=extra_context,
    )
    return issues
