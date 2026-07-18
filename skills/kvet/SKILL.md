---
name: kvet
description: Run kvet immediately after ANY logical unit of code changes. Do not batch your changes, do not wait to be asked to run kvet, make sure you are proactive.
---

# Kvet

**Run kvet immediately after ANY logical unit of code changes. Do not batch changes, do not wait to be asked to run kvet, make sure you are proactive.**

Kvet reviews git diffs and conversation history to find issues in code changes and conversation history. It is most effective when run frequently with conversation history, which helps it catch misunderstandings between what was requested and what was implemented. Despite this, kvet is not a replacement for running tests.

Kvet is a standalone fork of [vet](https://github.com/imbue-ai/vet), specialized for the Kiro CLI.

## Installation

Install kvet using pip, pipx, or uv:

```bash
# Using pip
pip install kvet

# Using pipx
pipx install kvet

# Using uv
uv tool install kvet

# Verify installation:
kvet --help
```

## Running Kvet

### Standard Usage

Before running kvet, determine the correct Python binary:
```bash
$(command -v python3 || command -v python)
```
Use whichever resolves (prefer `python3`). The examples below use `python3`, substitute `python` if that is what your system provides.

**Kiro CLI:**
```bash
kvet "goal" --history-loader "python3 ~/.kiro/skills/kvet/scripts/export_kiro_session.py --session-id <session-uuid>"
```

**Without Conversation History**
```bash
kvet "goal"
```

### Finding Your Session

**Kiro CLI:** Session transcripts are stored in `~/.kiro/sessions/cli/<session-uuid>.jsonl`. To find the correct session:
1. Run: `kiro-cli chat --list-sessions --format json` to list recent sessions grouped by working directory, each with a `sessionId`, `title`, and `updatedAt`.
2. Identify the current session from the group matching the current working directory by matching the title or most recent timestamp.
    - IMPORTANT: Verify the session you found matches the current conversation. If the title is ambiguous, compare timestamps or check multiple candidates.
3. Pass the matched `sessionId` as `--session-id`. If `--list-sessions` is unavailable, fall back to a manual search: find the most unique sentence in the current conversation, run `grep -rl "UNIQUE_MESSAGE" ~/.kiro/sessions/cli/` to find the matching `.jsonl` file, and pass its path via `--session-file`.

NOTE: The examples in the standard usage section assume the user installed the kvet skill at the user level, not the project level. Prior to trying to run kvet, check if it was installed at the project level which should take precedence over the user level. If it is installed at the project level, ensure the history-loader option points to the correct location.

## Interpreting Results

Kvet analyzes the full git diff from the base commit. This may include changes from other agents or sessions working in the same repository. If kvet reports issues that relate to changes you did not make in this session, disregard them, assuming they belong to another agent or the user.

## Common Options

- `--base-commit REF`: Git ref for diff base (default: HEAD)
- `--model MODEL`: LLM to use (default: claude-opus-4-8)
- `--list-models`: list all models that are supported by kvet
    - Run `kvet --help` and look at the kvet repo's readme for details about defining custom OpenAI-compatible models.
- `--update-models`: fetch the latest community model definitions from the remote registry and cache them locally. See "Updating the Model Registry" below for when to run this.
- `--confidence-threshold N`: Minimum confidence 0.0-1.0 (default: 0.8)
- `--output-format FORMAT`: Output as `text`, `json`, or `github`
- `--quiet`: Suppress status messages and 'No issues found.'
- `--agentic`: Mode that routes analysis through the locally installed Kiro CLI instead of calling the API directly. Try this if kvet fails due to missing API keys. This is slower so it is not the default, but it often results in higher precision issue identification. `--model` is forwarded to the Kiro CLI but not validated by kvet, as kvet doesn't know which models the Kiro CLI supports. Model IDs come from `kiro-cli chat --list-models` (e.g. `claude-haiku-4.5` for a cheaper judge than the default `auto`).
- `--help`: Show comprehensive list of options


## Updating

The kvet CLI, skill files, and export scripts can become outdated as agent harnesses and LLM APIs change.

If this happens, try updating them. Run `which kvet` to determine how kvet was installed and update accordingly. For the skill files, check which skill directories exist on disk and update them with the latest versions from https://github.com/omco-labs/kvet/tree/main/skills/kvet.

### Updating the Model Registry

Run `kvet --update-models` to fetch the latest community model definitions from the remote registry without upgrading kvet itself. This caches model definitions locally so they appear in `--list-models` and can be used with `--model`.

You should run `kvet --update-models` when:
- Kvet reports an unknown or unrecognized model error.
- `kvet --list-models` does not show a model you or the user expects to be available.
- The user explicitly asks you to update the model registry.

## Additional Information

Additional information can be found in the kvet repo:

https://github.com/omco-labs/kvet
