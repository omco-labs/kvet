from __future__ import annotations

# The choice to use argparse was primarily driven by the idea that kvet will be called by agents / llms.
# Given this, we want to have the most standardized outputs possible.
import argparse
import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from loguru import logger

from kvet.cli.config.cli_config_schema import CLI_DEFAULTS
from kvet.cli.config.cli_config_schema import CliConfigPreset
from kvet.cli.config.loader import ConfigLoadError
from kvet.cli.config.loader import get_cli_config_file_paths
from kvet.cli.config.loader import get_config_preset
from kvet.cli.config.loader import load_cli_config
from kvet.cli.config.loader import load_custom_guides_config
from kvet.cli.config.loader import load_models_config
from kvet.cli.config.schema import ModelsConfig
from kvet.formatters import OUTPUT_FIELDS
from kvet.formatters import OUTPUT_FORMATS
from kvet.formatters import validate_output_fields
from kvet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from kvet.imbue_core.agents.agent_api.errors import AgentProcessError
from kvet.imbue_core.data_types import AgentHarnessType
from kvet.imbue_core.data_types import IssueCode
from kvet.imbue_core.data_types import get_valid_issue_code_values

VERSION = version("kvet")

_ISSUE_CODE_FIELDS = frozenset({"enabled_issue_codes", "disabled_issue_codes"})
_PATH_FIELDS = frozenset({"repo", "output", "log_file"})
_PATH_LIST_FIELDS = frozenset({"extra_context"})


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kvet",
        description="Identify issues in code changes using LLM-based analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )

    parser.add_argument(
        "goal",
        type=str,
        nargs="?",
        default=CLI_DEFAULTS.goal,
        metavar="GOAL",
        help=(
            "Description of what the code change is trying to accomplish. "
            + "If not provided, only goal-independent issue identifiers will run."
        ),
    )

    parser.add_argument(
        "--repo",
        "-r",
        type=Path,
        default=Path.cwd(),
        metavar="PATH",
        help="Path to the repository for analysis (default: current directory)",
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        metavar="NAME",
        help="Name of the configuration to use. Configurations are defined in .kvet/configs.toml in your target project's root or ~/.config/kvet/configs.toml.",
    )
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="List all available named configurations",
    )

    diff_group = parser.add_argument_group("diff options")
    diff_group.add_argument(
        "--base-commit",
        type=str,
        default=CLI_DEFAULTS.base_commit,
        metavar="REF",
        help=f"Git commit, branch, or ref to use as the base for computing the diff (default: {CLI_DEFAULTS.base_commit})",
    )
    # By default, kvet includes all changes (staged, unstaged, and untracked). With --staged, only staged changes are included.
    diff_group.add_argument("--staged", action="store_true", help="Only analyze staged changes")

    context_group = parser.add_argument_group("context options")
    context_group.add_argument(
        "--history-loader",
        type=str,
        default=CLI_DEFAULTS.history_loader,
        metavar="COMMAND",
        help=(
            "Shell command that outputs conversation history as JSON to stdout. "
            + "Used to derive a goal if one is not provided."
        ),
    )
    context_group.add_argument(
        "--extra-context",
        type=Path,
        nargs="*",
        default=CLI_DEFAULTS.extra_context,
        metavar="FILE",
        help="Path(s) to file(s) containing additional context (e.g., library documentation). Content is included in the prompt after the codebase snapshot.",
    )

    analysis_group = parser.add_argument_group("analysis options")
    # Valid issue codes are defined in imbue_core.data_types.IssueCode
    analysis_group.add_argument(
        "--enabled-issue-codes",
        type=IssueCode,
        nargs="+",
        default=CLI_DEFAULTS.enabled_issue_codes,
        metavar="CODE",
        help="Only report issues of the given type(s). Use --list-issue-codes to see valid codes.",
    )
    analysis_group.add_argument(
        "--disabled-issue-codes",
        type=IssueCode,
        nargs="+",
        default=CLI_DEFAULTS.disabled_issue_codes,
        metavar="CODE",
        help="Do not report issues of the given type(s). Use --list-issue-codes to see valid codes.",
    )
    analysis_group.add_argument(
        "--list-issue-codes",
        action="store_true",
        help="List all available issue codes",
    )

    model_group = parser.add_argument_group("model configuration")
    model_group.add_argument(
        "--model",
        "-m",
        type=str,
        default=CLI_DEFAULTS.model,
        metavar="MODEL",
        help=(
            "LLM to use for analysis. In agentic mode (the default) the model is passed "
            "directly to the Kiro CLI; otherwise it must be defined by a localhost provider "
            "in models.json. If omitted, kvet runs agentically and the Kiro CLI picks its own default."
        ),
    )
    model_group.add_argument(
        "--list-models",
        action="store_true",
        help="List all available models",
    )
    model_group.add_argument(
        "--temperature",
        type=float,
        default=CLI_DEFAULTS.temperature,
        metavar="TEMP",
        help=f"Override the default temperature for the model (default: {CLI_DEFAULTS.temperature}).",
    )

    filter_group = parser.add_argument_group("filtering options")
    filter_group.add_argument(
        "--confidence-threshold",
        type=float,
        default=CLI_DEFAULTS.confidence_threshold,
        metavar="THRESHOLD",
        help=f"Minimum confidence score (0.0-1.0) for issues to be reported (default: {CLI_DEFAULTS.confidence_threshold})",
    )

    parallel_group = parser.add_argument_group("parallelization options")
    parallel_group.add_argument(
        "--max-workers",
        type=int,
        default=CLI_DEFAULTS.max_workers,
        metavar="N",
        help=f"Maximum number of parallel workers for identification (default: {CLI_DEFAULTS.max_workers})",
    )
    parallel_group.add_argument(
        "--max-spend",
        type=float,
        default=CLI_DEFAULTS.max_spend,
        metavar="DOLLARS",
        help="Maximum dollars to spend on API calls (default: no limit)",
    )

    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CLI_DEFAULTS.output,
        metavar="FILE",
        help="Output file path (default: stdout). Use - to write to stdout.",
    )
    output_group.add_argument(
        "--output-format",
        type=str,
        choices=OUTPUT_FORMATS,
        default=CLI_DEFAULTS.output_format,
        metavar="FORMAT",
        help=f"Output format. Choices: {', '.join(OUTPUT_FORMATS)} (default: {CLI_DEFAULTS.output_format})",
    )
    output_group.add_argument(
        "--output-fields",
        type=str,
        nargs="+",
        default=CLI_DEFAULTS.output_fields,
        metavar="FIELD",
        help="Output fields to include (default: all)",
    )
    output_group.add_argument(
        "--list-fields",
        action="store_true",
        help="List all available output data fields",
    )
    output_group.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=CLI_DEFAULTS.verbose,
        help="Increase verbosity. Use -v for debug output, -vv for full trace (raw LLM responses, API details).",
    )
    output_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        default=CLI_DEFAULTS.quiet,
        help="Suppress status messages and 'No issues found.'",
    )
    output_group.add_argument(
        "--log-file",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write full trace log to FILE (default: ~/.local/state/kvet/kvet.log). Also accepts KVET_LOG_FILE environment variable.",
    )

    parser.add_argument(
        "--agentic",
        action="store_true",
        default=CLI_DEFAULTS.agentic,
        help=(
            "Run kvet in agentic mode (uses the Kiro CLI). This is the default when no "
            "--model is given; passing a --model defined in models.json selects API mode instead."
        ),
    )

    return parser


# TODO: There are logical groupings of codes we should consider because some issue_codes are associated with the same prompts / categories of issues.
# This should likely be used to dictate the ordering instead of sorting.
def list_issue_codes() -> None:
    print("Available issue codes:")
    print()
    for code in sorted(get_valid_issue_code_values()):
        print(f"  {code}")


_KIRO_ISSUE_URL = "https://github.com/kirodotdev/Kiro/issues"


def list_models(
    user_config: ModelsConfig | None = None,
    *,
    agentic: bool = False,
) -> None:
    from kvet.cli.models import get_models_by_provider

    if agentic:
        print("Model listing for agentic mode (kiro harness):")
        print()
        print("  In agentic mode, --model is passed directly to the Kiro CLI.")
        print("  kvet does not know which models the Kiro CLI supports. Some")
        print("  models listed below may not work, and the Kiro CLI may accept models")
        print("  not listed here. If --model is omitted, the Kiro CLI uses its own default.")
        print()
        print("  If better model listing support would be useful, consider requesting")
        print("  a model listing feature from the Kiro CLI maintainers:")
        print(f"    {_KIRO_ISSUE_URL}")
        print()
    else:
        print("Available models (localhost providers from models.json):")
        print()

    models_by_provider = get_models_by_provider(user_config)
    if not models_by_provider:
        print("  No localhost providers are configured in models.json.")
    for provider, model_ids in sorted(models_by_provider.items()):
        print(f"  {provider}:")
        for model_id in sorted(model_ids):
            print(f"    {model_id}")
    print()
    print("Agentic mode (the default) uses the Kiro CLI; --model is passed through to it")
    print("and the Kiro CLI is the authority on which models it supports.")


def list_fields() -> None:
    print("Available output fields:")
    print()
    for field in OUTPUT_FIELDS:
        print(f"  {field}")


def list_configs(cli_configs: dict[str, CliConfigPreset], repo_path: Path) -> None:
    print("Available configurations:")
    print()

    if not cli_configs:
        print("  No configurations found.")
        print()
        print("Configuration files are loaded from:")
        for path in get_cli_config_file_paths(repo_path):
            exists_marker = " (exists)" if path.exists() else ""
            print(f"  {path}{exists_marker}")
        return

    for name, preset in sorted(cli_configs.items()):
        print(f"  {name}:")
        preset_dict = preset.model_dump(exclude_none=True)
        if preset_dict:
            for key, value in preset_dict.items():
                print(f"    {key}: {value}")
        else:
            print("    (uses all defaults)")
        print()


def _validate_staged_related_options(args: argparse.Namespace, base_commit_cli_specified: bool) -> str | None:
    """Validate options related to staged analysis.

    Returns an error message string when validation fails (caller should print
    it to stderr and return an exit code of 2), otherwise returns None.
    """
    if args.staged and base_commit_cli_specified:
        # Only treat --base-commit as conflicting if explicitly provided on the CLI.
        # Config/default values (e.g. "main") should not trigger an error because
        # staged mode intentionally ignores base commits.
        return "kvet: --staged and --base-commit are mutually exclusive"

    if args.staged and args.agentic:
        # Sanity check to prevent users from accidentally combining incompatible modes.
        # Note: this runs before agentic-by-default kicks in, so it only fires when
        # agentic was explicitly requested (via the flag or a config preset).
        return "kvet: --staged and --agentic are mutually exclusive"

    if args.staged and args.model is None:
        # --staged requires API mode, which needs an explicit localhost model
        # (there is no default API model; the default mode is agentic).
        return (
            "kvet: --staged requires API mode: pass --model with a model defined by a "
            "localhost provider in models.json"
        )

    return None


_DEFAULT_LOG_FILE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "kvet" / "kvet.log"


def configure_logging(verbose: int, log_file: Path | None) -> None:
    if log_file is None:
        log_file = Path(os.environ["KVET_LOG_FILE"]) if "KVET_LOG_FILE" in os.environ else _DEFAULT_LOG_FILE
    logger.remove()
    if verbose == 1:
        logger.add(sys.stderr, level="DEBUG", format="{level}: {message}")
    elif verbose >= 2:
        logger.add(sys.stderr, level="TRACE", format="{level} | {name}:{line} | {message}")

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_file, level="TRACE", rotation="10 MB", retention=3)
    except OSError as e:
        print(
            f"kvet: warning: could not write to log file {log_file}: {e.strerror}",
            file=sys.stderr,
        )


def load_conversation_from_command(command: str, cwd: Path) -> tuple:
    from kvet.imbue_tools.get_conversation_history.get_conversation_history import parse_conversation_history

    logger.debug("Running history loader command: {}", command)
    result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(
            f"kvet: warning: history loader command failed (exit {result.returncode}): {result.stderr.strip()}",
            file=sys.stderr,
        )
        return ()
    if not result.stdout.strip():
        logger.debug("History loader command returned empty output, no conversation history loaded")
        return ()
    messages = parse_conversation_history(result.stdout)
    logger.debug(
        "Loaded {} conversation history messages from history loader command",
        len(messages),
    )
    return messages


def apply_config_preset(args: argparse.Namespace, preset: CliConfigPreset) -> argparse.Namespace:
    preset_dict = preset.model_dump(exclude_none=True)

    for field, preset_value in preset_dict.items():
        default_value = getattr(CLI_DEFAULTS, field, None)
        if getattr(args, field) == default_value:
            if field in _ISSUE_CODE_FIELDS:
                preset_value = [IssueCode(code) for code in preset_value]
            elif field in _PATH_LIST_FIELDS:
                preset_value = [Path(p) for p in preset_value]
            elif field in _PATH_FIELDS:
                preset_value = Path(preset_value)
            setattr(args, field, preset_value)

    return args


# TODO: This string matching is brittle. Ideally each provider's exception manager would raise PromptTooLongError directly.
_CONTEXT_OVERFLOW_PATTERNS = [
    "prompt is too long",
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "too many tokens",
    "reduce the length of the messages",
    "ran out of room in the model's context window",
]


def _is_context_overflow(e: Exception) -> bool:
    from kvet.imbue_core.agents.llm_apis.errors import PromptTooLongError

    if isinstance(e, PromptTooLongError):
        return True
    error_msg = getattr(e, "error_message", str(e)).lower()
    return any(pattern in error_msg for pattern in _CONTEXT_OVERFLOW_PATTERNS)


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    # Determine whether the user explicitly provided `--base-commit` on the
    # command line. `CLI_DEFAULTS.base_commit` may be non-empty (e.g. "main")
    # coming from config or defaults; we must only treat an explicit CLI
    # `--base-commit` as conflicting with staged mode.
    raw_argv = argv if argv is not None else sys.argv[1:]
    base_commit_cli_specified = any(a == "--base-commit" or a.startswith("--base-commit=") for a in raw_argv)

    # Handle subcommands that don't need config loading.
    if args.list_issue_codes:
        list_issue_codes()
        return 0

    if args.list_fields:
        list_fields()
        return 0

    # Load configs needed by the remaining commands.
    goal = args.goal or ""

    repo_path = args.repo

    try:
        user_config = load_models_config(repo_path)
    except ConfigLoadError as e:
        print(f"kvet: could not load model configuration: {e}", file=sys.stderr)
        return 2

    try:
        custom_guides_config = load_custom_guides_config(repo_path)
    except ConfigLoadError as e:
        print(f"kvet: could not load custom guides: {e}", file=sys.stderr)
        return 2

    if args.list_models:
        list_models(
            user_config,
            agentic=args.agentic,
        )
        return 0

    try:
        cli_configs = load_cli_config(repo_path)
    except ConfigLoadError as e:
        print(f"kvet: could not load CLI configuration: {e}", file=sys.stderr)
        return 2

    if args.list_configs:
        list_configs(cli_configs, repo_path)
        return 0

    if args.config is not None:
        try:
            preset = get_config_preset(args.config, cli_configs, repo_path)
            args = apply_config_preset(args, preset)
        except ConfigLoadError as e:
            print(f"kvet: {e}", file=sys.stderr)
            return 2

    if not repo_path.exists():
        print(f"kvet: repository path does not exist: {repo_path}", file=sys.stderr)
        return 2

    if not repo_path.is_dir():
        print(f"kvet: repository path is not a directory: {repo_path}", file=sys.stderr)
        return 2

    if args.extra_context:
        for extra_context_file in args.extra_context:
            if not extra_context_file.exists():
                print(
                    f"kvet: extra context file does not exist: {extra_context_file}",
                    file=sys.stderr,
                )
                return 2

    staged_err = _validate_staged_related_options(args, base_commit_cli_specified)
    if staged_err is not None:
        print(staged_err, file=sys.stderr)
        return 2

    # Default mode selection: when no --model is given and agentic was not explicitly
    # requested (flag or preset), run agentically. The model stays None so the Kiro
    # CLI uses its own default. When --model is given without --agentic, API mode is
    # selected and the model must resolve to a localhost provider from models.json.
    if not args.agentic and args.model is None:
        args.agentic = True

    if args.verbose and args.quiet:
        print(
            "kvet: --verbose and --quiet are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    if not 0.0 <= args.confidence_threshold <= 1.0:
        print(
            f"kvet: confidence threshold must be between 0.0 and 1.0, got: {args.confidence_threshold}",
            file=sys.stderr,
        )
        return 2

    if not 0.0 <= args.temperature <= 2.0:
        print(
            f"kvet: temperature must be between 0.0 and 2.0, got: {args.temperature}",
            file=sys.stderr,
        )
        return 2

    if args.max_spend is not None and args.max_spend <= 0:
        print(
            f"kvet: max spend must be a positive number, got: {args.max_spend}",
            file=sys.stderr,
        )
        return 2

    configure_logging(args.verbose, args.log_file)

    # Lazy imports: kvet.cli.models transitively imports the LLM SDK provider
    # modules (~1s), so it must NOT be imported at module level. Lightweight
    # subcommands (--version, --list-issue-codes, --list-fields)
    # exit before reaching this point. See startup_time_test.py.
    from kvet.api import find_issues
    from kvet.cli.models import build_language_model_config
    from kvet.cli.models import get_max_output_tokens_for_model
    from kvet.cli.models import validate_api_key_for_model
    from kvet.cli.models import validate_model_id
    from kvet.formatters import format_github_review
    from kvet.formatters import format_issue_text
    from kvet.formatters import issue_to_dict
    from kvet.imbue_core.agents.llm_apis.errors import BadAPIRequestError
    from kvet.imbue_core.agents.llm_apis.errors import MissingAPIKeyError
    from kvet.imbue_core.agents.llm_apis.errors import ModelRefusalError
    from kvet.imbue_core.agents.llm_apis.errors import PromptTooLongError
    from kvet.imbue_tools.types.vet_config import VetConfig

    conversation_history = None
    if args.history_loader is not None:
        conversation_history = load_conversation_from_command(args.history_loader, repo_path)
    else:
        logger.debug("No history loader provided, skipping conversation history loading")
    extra_context = None
    if args.extra_context:
        extra_context_parts = []
        for context_file in args.extra_context:
            extra_context_parts.append(context_file.read_text())
        extra_context = "\n\n".join(extra_context_parts)

    if args.output_fields is not None:
        try:
            validate_output_fields(args.output_fields)
        except ValueError as e:
            print(f"kvet: {e}", file=sys.stderr)
            return 2

    enabled_identifiers = ("agentic_issue_identifier",) if args.agentic else None
    disabled_identifiers = None if args.agentic else ("agentic_issue_identifier",)
    enabled_issue_codes = tuple(args.enabled_issue_codes) if args.enabled_issue_codes else None
    disabled_issue_codes = tuple(args.disabled_issue_codes) if args.disabled_issue_codes else None

    if args.agentic:
        # In agentic mode the model string is passed directly to the external CLI
        # (the Kiro CLI).  We skip kvet's own model validation because
        # the CLI is the authority on which models it supports.  When the user
        # doesn't specify --model, we pass None so the CLI uses its own default.
        config = VetConfig(
            enabled_identifiers=enabled_identifiers,
            disabled_identifiers=disabled_identifiers,
            agent_model_name=args.model,
            enabled_issue_codes=enabled_issue_codes,
            disabled_issue_codes=disabled_issue_codes,
            temperature=args.temperature,
            filter_issues_below_confidence=args.confidence_threshold,
            max_identify_workers=args.max_workers,
            max_identifier_spend_dollars=args.max_spend,
            custom_guides_config=custom_guides_config,
            agent_harness_type=AgentHarnessType.KIRO,
            filter_issues_through_llm_evaluator=False,
            enable_deduplication=False,
        )
    else:
        model_id = args.model
        assert model_id is not None  # Guaranteed by the default mode selection above.

        try:
            model_id = validate_model_id(model_id, user_config)
        except ValueError as e:
            print(f"kvet: {e}", file=sys.stderr)
            return 2

        try:
            validate_api_key_for_model(model_id, user_config)
        except Exception as e:
            print(f"kvet: {e}", file=sys.stderr)
            print(
                "hint: If you have a Kiro subscription, try --agentic to use your\n"
                "      locally installed Kiro CLI instead.",
                file=sys.stderr,
            )
            return 2

        # TODO: Support OFFLINE, UPDATE_SNAPSHOT, and MOCKED modes.
        language_model_config = build_language_model_config(model_id, user_config)
        max_output_tokens = get_max_output_tokens_for_model(model_id, user_config)

        config = VetConfig(
            enabled_identifiers=enabled_identifiers,
            disabled_identifiers=disabled_identifiers,
            language_model_generation_config=language_model_config,
            enabled_issue_codes=enabled_issue_codes,
            disabled_issue_codes=disabled_issue_codes,
            temperature=args.temperature,
            filter_issues_below_confidence=args.confidence_threshold,
            max_identify_workers=args.max_workers,
            max_output_tokens=max_output_tokens or 20000,
            max_identifier_spend_dollars=args.max_spend,
            custom_guides_config=custom_guides_config,
            agent_harness_type=AgentHarnessType.KIRO,
            # TODO: Evaluate if routing filtration/dedup through the agent harness is worth the tradeoff.
            filter_issues_through_llm_evaluator=True,
            enable_deduplication=True,
        )

    if not args.quiet:
        if args.staged:
            print(
                f"analyzing {repo_path} (staged changes)",
                file=sys.stderr,
            )
        else:
            print(
                f"analyzing {repo_path} (relative to {args.base_commit})",
                file=sys.stderr,
            )

    try:
        issues = find_issues(
            repo_path=repo_path,
            relative_to=args.base_commit,
            goal=goal,
            config=config,
            conversation_history=conversation_history,
            extra_context=extra_context,
            only_staged=args.staged,
        )
    except AgentCLINotFoundError as e:
        print(f"kvet: {e}", file=sys.stderr)
        return 2
    except AgentProcessError as e:
        if _is_context_overflow(e):
            print(
                "kvet: review failed because too much context was provided to the model. "
                "Consider using a model with a larger context window, or a narrower base commit.",
                file=sys.stderr,
            )
            return 2
        print(f"kvet: {e}\nRe-run with -vv for more details.", file=sys.stderr)
        return 1
    except MissingAPIKeyError as e:
        print(f"kvet: {e}", file=sys.stderr)
        print(
            "hint: If you have a Kiro subscription, try --agentic to use your\n"
            "      locally installed Kiro CLI instead.",
            file=sys.stderr,
        )
        return 2
    except ModelRefusalError as e:
        print(
            f"kvet: {e} This can happen spuriously on benign inputs; "
            "try re-running, or use a different model via --model.",
            file=sys.stderr,
        )
        return 1
    # TODO: This should be refactored so we only need to handle prompt too long errors when context is overfilled.
    except (PromptTooLongError, BadAPIRequestError) as e:
        if _is_context_overflow(e):
            print(
                "kvet: review failed because too much context was provided to the model. "
                "Consider using a model with a larger context window.",
                file=sys.stderr,
            )
            return 2
        if isinstance(e, BadAPIRequestError):
            print(f"kvet: {e.error_message}", file=sys.stderr)
            return 1
        raise

    output_fields = args.output_fields if args.output_fields else OUTPUT_FIELDS

    output_file = None
    if args.output is not None and str(args.output) != "-":
        output_file = open(args.output, "w")
        output_stream = output_file
    else:
        output_stream = sys.stdout

    try:
        if not issues:
            if args.output_format == "json":
                print(json.dumps({"issues": []}, indent=2), file=output_stream)
            elif args.output_format == "github":
                payload = format_github_review(issues, output_fields)
                print(json.dumps(payload, indent=2), file=output_stream)
            elif not args.quiet:
                print("No issues found.", file=output_stream)
            return 0

        if args.output_format == "json":
            issues_list = [issue_to_dict(issue, output_fields) for issue in issues]
            print(json.dumps({"issues": issues_list}, indent=2), file=output_stream)
        elif args.output_format == "github":
            payload = format_github_review(issues, output_fields)
            print(json.dumps(payload, indent=2), file=output_stream)
        else:
            for issue in issues:
                print(format_issue_text(issue, output_fields), file=output_stream)
                print(file=output_stream)

        return 10
    finally:
        if output_file is not None:
            output_file.close()


if __name__ == "__main__":
    sys.exit(main())
