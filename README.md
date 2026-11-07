<p align="center">
  <a href="https://github.com/omco-labs/kvet">
    <img alt="Kvet" src="https://raw.githubusercontent.com/omco-labs/kvet/main/images/kVet.svg" width="21%">
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
- **Works with your Kiro subscription**: routes analysis through the Kiro CLI (agentic mode, the default).
- **Local models welcome**: alternatively, bring your own OpenAI-compatible server running on localhost (e.g. Ollama, vLLM). Remote API providers are not supported.
- **Free and open source**: no account, fees, or data collection. Requests go directly to your inference provider. Licensed under the AGPL-3.0.

## Using Kvet with Coding Agents

Kvet includes an agent skill. When installed, agents will proactively run kvet after code changes to find issues with the new code and mismatches between the user's request and the agent's actions.

### Install the SKILL

```bash
curl -fsSL https://raw.githubusercontent.com/omco-labs/kvet/main/install-skill.sh | bash
```

You will be prompted to choose between:

- **Project level**: installs into `.kiro/skills/kvet/` at the repo root (run from your repo directory)
- **User level**: installs into `~/.kiro/` skill directory, discovered globally

### Manual installation

##### Project Level SKILL

From the root of your git repo:

```bash
mkdir -p .kiro/skills/kvet/scripts
for file in SKILL.md scripts/export_kiro_session.py; do
  curl -fsSL "https://raw.githubusercontent.com/omco-labs/kvet/main/skills/kvet/$file" \
    -o ".kiro/skills/kvet/$file"
done
```

##### User Level SKILL

```bash
mkdir -p ~/.kiro/skills/kvet/scripts
for file in SKILL.md scripts/export_kiro_session.py; do
  curl -fsSL "https://raw.githubusercontent.com/omco-labs/kvet/main/skills/kvet/$file" \
    -o ~/.kiro/skills/kvet/$file
done
```


### Security note

The `--history-loader` option executes the specified shell command as the current user to load the conversation history. It is important to review history loader commands and shared config presets before use.

## Install the CLI

Kvet is **not published on PyPI**; install it from this repository.

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/omco-labs/kvet.git@main
```

Or with [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/omco-labs/kvet.git@main
```

Or from a local checkout (uses the current branch):

```bash
git clone https://github.com/omco-labs/kvet.git
cd kvet
./install.sh
```

`install.sh` runs `uv tool install --from <repo-root> kvet --reinstall` (falling back to pipx/pip), then prints the installed binary path and `kvet --version`.

### Coexisting with vet

Kvet fully coexists with upstream [vet](https://github.com/imbue-ai/vet) on the same host:

- Separate binaries: `kvet` vs `vet` (separate uv tool/pipx venvs).
- Separate config/cache/state paths: `~/.config/kvet`, `~/.cache/kvet`, and `~/.local/state/kvet` vs the `vet` equivalents.

Both tools can be installed and used side by side without interfering with each other.

### Usage

Run Kvet in the current repo (agentic mode via the Kiro CLI is the default):

```bash
kvet "Implement X without breaking Y"
```

Compare against a base ref/commit:

```bash
kvet "Refactor storage layer" --base-commit main
```

`--model` is forwarded to the Kiro CLI. Model IDs come from `kiro-cli chat --list-models` (e.g. `claude-haiku-4.5` for a cheaper judge than the Kiro CLI's default model). The friendly aliases `haiku`, `sonnet`, and `opus` are mapped to `claude-haiku-4.5`, `claude-sonnet-5.5`, and `claude-opus-5.5`.

Kvet drives `kiro-cli acp` and supports both the Kiro CLI v3 agent engine (the default) and the v2 engine. To fall back to v2, set `KVET_KIRO_ENGINE=v2`. On v3, kvet approves the agent's tool-permission requests once each (the equivalent of `--trust-all-tools` on v2) and sets the model and agent mode over ACP, because the v3 engine rejects the `--trust-all-tools`, `--model` and `--agent` flags.

To use a localhost OpenAI-compatible server instead of the Kiro CLI, define the model in `models.json` (see [Model configuration](#model-configuration)) and pass it explicitly:

```bash
kvet "Implement X without breaking Y" --model qwen3-coder
```

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

Kvet only allows two model sources:

1. **The Kiro CLI** (agentic mode, the default) — `--model` is passed through to `kiro-cli`.
2. **Localhost OpenAI-compatible servers** (API mode) — model definitions from JSON config files. Every provider's `base_url` must point at `localhost`, `127.0.0.1`, or `[::1]`; remote API providers are rejected at config-load time.

JSON config files are searched in:

- `$XDG_CONFIG_HOME/kvet/models.json` (or `~/.config/kvet/models.json`)
- `.kvet/models.json` at your repo root

#### Example `models.json`

```json
{
  "providers": {
    "local": {
      "name": "Local OpenAI-compatible server",
      "api_type": "openai_compatible",
      "base_url": "http://localhost:11434/v1",
      "models": {
        "granite4.1-8b": {
		  "model_id": "granite4.1-8b",
          "context_window": 131072,
          "max_output_tokens": 2048,
          "supports_temperature": true
        }
      }
    }
  }
}
```

Then:

```bash
kvet "Harden error handling" --model granite4.1-8b
```

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
