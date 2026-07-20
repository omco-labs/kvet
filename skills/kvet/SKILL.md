---
name: kvet
description: Run kvet immediately after ANY logical unit of code changes. Do not batch your changes, do not wait to be asked to run kvet, make sure you are proactive.
---

# Kvet

**Run kvet immediately after ANY logical unit of code changes. Do not batch changes, do not wait to be asked to run kvet, make sure you are proactive.**

Kvet reviews git diffs and conversation history to find issues in code changes and conversation history. It is most effective when run frequently with conversation history, which helps it catch misunderstandings between what was requested and what was implemented. Despite this, kvet is not a replacement for running tests.

Kvet is a standalone fork of [vet](https://github.com/imbue-ai/vet), specialized for the Kiro CLI.

## Installation

Kvet is not published on PyPI; install it from the GitHub repository:

```bash
# Using uv
uv tool install git+https://github.com/omco-labs/kvet.git@main

# Using pipx
pipx install git+https://github.com/omco-labs/kvet.git@main

# From a local checkout (installs from the current branch)
./install.sh

# Verify installation:
kvet --help
```

Kvet coexists with upstream `vet`: separate binaries, separate tool venvs, and separate config/cache/state paths (`~/.config/kvet`, `~/.cache/kvet`, `~/.local/state/kvet`).

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
- `--model MODEL`: LLM to use. By default kvet runs agentically and the Kiro CLI picks its own default model (`auto`). In agentic mode `--model` is forwarded to the Kiro CLI; model IDs come from `kiro-cli chat --list-models` (e.g. `claude-haiku-4.5` for a cheaper judge). The aliases `haiku`, `sonnet`, and `opus` are mapped to concrete kiro models (kiro has no opus tier, so `opus` resolves to the strongest available model).
- `--list-models`: list localhost provider models defined in models.json (plus a note about agentic mode)
    - Run `kvet --help` and look at the kvet repo's readme for details about defining localhost OpenAI-compatible models.
- `--confidence-threshold N`: Minimum confidence 0.0-1.0 (default: 0.8)
- `--output-format FORMAT`: Output as `text`, `json`, or `github`
- `--quiet`: Suppress status messages and 'No issues found.'
- `--agentic`: Routes analysis through the locally installed Kiro CLI. This is the default mode; the flag exists to force agentic mode when you also pass a `--model` name that kvet would otherwise try to resolve as a localhost API model. API mode is the localhost opt-in: passing `--model` with a model defined in `models.json` (localhost OpenAI-compatible providers only; remote providers are rejected) runs kvet against that local server instead of the Kiro CLI.
- `--help`: Show comprehensive list of options


## Updating

The kvet CLI, skill files, and export scripts can become outdated as agent harnesses and LLM APIs change.

If this happens, try updating them. Run `which kvet` to determine how kvet was installed and update accordingly. For the skill files, check which skill directories exist on disk and update them with the latest versions from https://github.com/omco-labs/kvet/tree/main/skills/kvet.

## Additional Information

Additional information can be found in the kvet repo:

https://github.com/omco-labs/kvet
