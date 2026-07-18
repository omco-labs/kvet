<p align="center">
  <a href="https://github.com/omco-labs/kvet">
    <img alt="Kvet" src="https://raw.githubusercontent.com/imbue-ai/vet/main/images/Vet.svg" width="21%">
  </a>
</p>

<p align="center">
  <a href="https://www.gnu.org/licenses/agpl-3.0"><img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
  <img src="https://github.com/omco-labs/kvet/actions/workflows/test-unit.yml/badge.svg" alt="Build Status">
</p>

<p align="center">Kvet is a standalone verification tool for <b>code changes</b> and <b>coding agent behavior</b>, specialized for the <a href="https://kiro.dev">Kiro CLI</a>.</p>

> **Note**: kvet is a standalone fork of [imbue-ai/vet](https://github.com/imbue-ai/vet), specialized for the Kiro CLI. The Claude Code, Codex, and OpenCode agent harnesses from upstream have been removed; Kiro is the only agent harness. Kvet is licensed under the AGPL-3.0, the same license as upstream vet.

## Why Kvet

- **Reviews intent and code**: checks agent conversations for goal adherence and code changes for correctness.
- **Runs anywhere**: from the terminal, as an agent skill, or in CI.
- **Bring-your-own-model**: works with any provider using your own API keys.
- **Works with your Kiro subscription**: routes analysis through the Kiro CLI using [`--agentic`](#usage).
- **Free and open source**: no account, fees, or data collection. Requests go directly to your inference provider. Licensed under the AGPL-3.0.

## Using Kvet with Coding Agents

Kvet includes an agent skill. When installed, agents will proactively run kvet after code changes to find issues with the new code and mismatches between the user's request and the agent's actions.

### Install the skill

```bash
curl -fsSL https://raw.githubusercontent.com/omco-labs/kvet/main/install-skill.sh | bash
```

You will be prompted to choose between:

- **Project level**: installs into `.agents/skills/kvet/` and `.kiro/skills/kvet/` at the repo root (run from your repo directory)
- **User level**: installs into `~/.agents/` and `~/.kiro/` skill directories, discovered globally

<details>
<summary>Manual installation</summary>

#### Project Level

From the root of your git repo:

```bash
for dir in .agents .kiro; do
  mkdir -p "$dir/skills/kvet/scripts"
  for file in SKILL.md scripts/export_kiro_session.py; do
    curl -fsSL "https://raw.githubusercontent.com/omco-labs/kvet/main/skills/kvet/$file" \
      -o "$dir/skills/kvet/$file"
  done
done
```

#### User Level

```bash
for dir in ~/.agents ~/.kiro; do
  mkdir -p "$dir/skills/kvet/scripts"
  for file in SKILL.md scripts/export_kiro_session.py; do
    curl -fsSL "https://raw.githubusercontent.com/omco-labs/kvet/main/skills/kvet/$file" \
      -o "$dir/skills/kvet/$file"
  done
done
```

</details>

### Security note

The `--history-loader` option executes the specified shell command as the current user to load the conversation history. It is important to review history loader commands and shared config presets before use.

## Install the CLI

```bash
pip install kvet
```

Or with [pipx](https://pipx.pypa.io/):

```bash
pipx install kvet
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install kvet
```

### Usage

Run Kvet in the current repo:

```bash
kvet "Implement X without breaking Y"
```

Compare against a base ref/commit:

```bash
kvet "Refactor storage layer" --base-commit main
```

Use the Kiro CLI instead of LLM APIs:

```bash
kvet "Implement X without breaking Y" --agentic
```

In agentic mode, `--model` is forwarded to the Kiro CLI. Model IDs come from `kiro-cli chat --list-models` (e.g. `claude-haiku-4.5` for a cheaper judge than the default `auto`).

## GitHub PRs (Actions)

Kvet reviews pull requests using a reusable GitHub Action.

Create `.github/workflows/kvet.yml`:

```yaml
name: Kvet

permissions:
  contents: read
  pull-requests: write

on:
  pull_request:
    types: [opened, edited, synchronize, reopened]

jobs:
  kvet:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
      - uses: omco-labs/kvet@main
        with:
          agentic: false
```

The action handles Python setup, kvet installation, merge base computation, and posting the review to the PR. `ANTHROPIC_API_KEY` must be set as a repository secret when using Anthropic models (the default). Agentic mode requires the Kiro CLI to be installed and authenticated on the runner. See [`action.yml`](https://github.com/omco-labs/kvet/blob/main/action.yml) for all available inputs.

## How it works

Kvet snapshots the repo and diff, optionally adds a goal and agent conversation, runs LLM checks, then filters/deduplicates findings into a final list of issues.

## Output & exit codes

- Exit code `0`: no issues found
- Exit code `1`: unexpected runtime error
- Exit code `2`: invalid usage/configuration error
- Exit code `10`: issues found

Output formats:
- `text`
- `json`
- `github`

## Configuration

### Model configuration

Kvet supports custom model definitions using OpenAI-compatible endpoints via JSON config files searched in:

- `$XDG_CONFIG_HOME/kvet/models.json` (or `~/.config/kvet/models.json`)
- `.kvet/models.json` at your repo root

#### Example `models.json`

```json
{
  "providers": {
    "openrouter": {
      "name": "OpenRouter",
      "api_type": "openai_compatible",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "models": {
        "gpt-5.2": {
          "model_id": "openai/gpt-5.2",
          "context_window": 400000,
          "max_output_tokens": 128000,
          "supports_temperature": true
        },
        "kimi-k2": {
          "model_id": "moonshotai/kimi-k2",
          "context_window": 131072,
          "max_output_tokens": 32768,
          "supports_temperature": true
        }
      }
    }
  }
}
```

Then:

```bash
kvet "Harden error handling" --model gpt-5.2
```

### Model registry

Kvet maintains a remote model registry with community-contributed model definitions. To fetch the latest definitions without upgrading kvet:

```bash
kvet --update-models
```

This downloads model definitions from the [registry](https://github.com/omco-labs/kvet/blob/main/registry/models.json) and caches them locally at `~/.cache/kvet/remote_models.json`. Once cached, registry models appear in `kvet --list-models` and can be used with `--model` like any other model.

Model resolution priority (highest to lowest):
1. User config (`.kvet/models.json` or `~/.config/kvet/models.json`)
2. Builtin models (Anthropic, OpenAI, Gemini)
3. Registry models (cached via `--update-models`)

See [`registry/CONTRIBUTING.md`](https://github.com/omco-labs/kvet/blob/main/registry/CONTRIBUTING.md) for information about contributing model definitions to the registry.

### Configuration profiles (TOML)

Kvet supports named profiles so teams can standardize CI usage without long CLI invocations.

Profiles set defaults like model choice, enabled issue codes, output format, and thresholds.

See [the example](https://github.com/omco-labs/kvet/blob/main/.kvet/configs.toml) in this project.

### Custom issue guides

You can customize the guide text for the issue codes via `guides.toml`. Guide files are loaded from:

- `$XDG_CONFIG_HOME/kvet/guides.toml` (or `~/.config/kvet/guides.toml`)
- `.kvet/guides.toml` at your repo root

#### Example `guides.toml`

```toml
[logic_error]
suffix = """
- Check for integer overflow in arithmetic operations
"""

[insecure_code]
replace = """
- Check for SQL injection: flag any string concatenation or f-string formatting used to build SQL queries rather than parameterized queries
- Check for XSS: flag user-supplied data rendered into HTML templates without proper escaping or sanitization
- Check for path traversal: flag file operations where user input flows into file paths without validation against directory traversal (e.g. ../)
- Check for insecure cryptography: flag use of deprecated or weak algorithms (e.g. MD5, SHA1 for security purposes, DES, RC4)
- Check for hardcoded credentials: flag passwords, API keys, or tokens embedded directly in source code
"""
```

Section keys must be valid issue codes (`kvet --list-issue-codes`). Each section supports three optional fields: `prefix` (prepends to built-in guide), `suffix` (appends to built-in guide), and `replace` (fully replaces the built-in guide). `prefix` and `suffix` can be used together, but `replace` is mutually exclusive with the other two. Guide text should be formatted as a list.

## Attribution

Kvet is a fork of [vet](https://github.com/imbue-ai/vet) by [Imbue](https://imbue.com). For bug reports and feature requests for kvet, please use [GitHub Issues](https://github.com/omco-labs/kvet/issues).

## License

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0-only)](https://github.com/omco-labs/kvet/blob/main/LICENSE).
