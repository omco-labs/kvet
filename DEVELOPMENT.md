# Development

For general usage, installation, and configuration, see the [README](README.md).

## Dev Setup

### On your host machine

Ensure you have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed. To actually run analyses you also need at least one of:

- the Kiro CLI (`kiro-cli`) installed and authenticated (agentic mode, the default), and/or
- a localhost OpenAI-compatible server (e.g. Ollama, vLLM) with matching entries in `models.json` (API mode).

Then run:

```bash
uv run kvet
```

### Containerized

You can use the `Containerfile` in `dev/` at the repo root to create a container that suffices to run Kvet for development purposes.

#### Setup

No API keys are required. If your localhost model server needs an API key, create a `.env` file at the repo root with the environment variable referenced by the provider's `api_key_env` in `models.json`.

#### Running Kvet in a Container

```bash
./dev/kvet.sh --list-models
./dev/kvet.sh "check for bugs" --base-commit main
```

Agentic mode requires the Kiro CLI (`kiro-cli`) to be installed and authenticated inside the container; it is not installed by the image.

The image is built automatically on each run. This process should be fast due to layer caching.

#### Interactive Development

```bash
./dev/run.sh
```

Starts an interactive shell in the container. The repo is bind-mounted at `/app`.

## Formatting Hooks

Install pre-commit hooks once per clone:

```bash
uvx pre-commit install
```

Run formatting hooks manually across the repo:

```bash
uvx pre-commit run --all-files
```

After installation, `isort`, `black`, and `ruff check` run automatically on staged Python files before each commit.

To run the same checks manually across the whole repo:

```bash
./dev/lint.sh
```

## Running Tests

### Unit tests

All unit tests are run with:

```bash
uv run pytest
```

This command should be preserved the sole way to run unit tests.

## Security Scanning

Dependency, secret, and misconfiguration scanning is done with [Trivy](https://trivy.dev/):

```bash
./dev/security-scan.sh
```

This is the same check the `Test / Security` CI workflow runs (fails on CRITICAL/HIGH findings). If it flags a vulnerable dependency, prefer upgrading via `uv lock --upgrade-package <name>` over ignoring the finding.

## Concepts

### Issue identifiers

Issue identifiers are pieces of logic capable of finding issues in code. We foresee two basic kinds of those:

1. File-checking ones.
    - To check for "objective" issues in existing files.
2. Commit-checking ones.
    - To check for the quality of a single commit.
    - "Assuming that we can treat the commit message as a requirement, how well does the commit implement it?"

By default, `kvet` runs all the registered issue identifiers and outputs all the found issues on the standard output in JSON format.

#### Adding new Issue Identifiers

If you want to add a new issue identifier, you need to:

1. Implement the `IssueIdentifier` protocol from `kvet.imbue_tools.repo_utils.data_types`.
2. Register the new issue identifier by adding it to `IDENTIFIERS` in `kvet.issue_identifiers.registry`.

Based on your needs, instead of the above, you can also extend one of the existing batched zero-shot issue identifiers:
    - `kvet/issue_identifiers/batched_commit_check.py`
      (for commit checking)
In that case you would simply expand the rubric in the prompt. That is actually the preferred way to catch issues at the moment due to efficiency.
Refer to the source code for more details.

### Model policy

Kvet only allows two model sources: the Kiro CLI (agentic mode, the default) and localhost OpenAI-compatible providers defined in `models.json`. Remote API providers are rejected at config-load time by a validator on `ProviderConfig.base_url` (see `kvet/cli/config/schema.py`).

## CI / CD

### GitHub Actions naming conventions

Workflows follow a consistent naming scheme across three layers:

- **File name**: `<verb>-<target>.yml` (e.g. `test-unit.yml`)
- **Display name** (`name:`): `<Verb> / <Target>` (e.g. `Test / Unit`)
- **Job name**: short target identifier (e.g. `unit`)

The `/` in display names creates visual grouping in the GitHub Actions UI. Group related workflows under a shared prefix (e.g. `Test /`, `Publish /`). Standalone workflows (e.g. `Kvet`) don't need a prefix.

Current workflows:

- `test-unit.yml` (`Test / Unit`, job: `unit`) — lint (isort, black, ruff) + pytest suite
- `test-security.yml` (`Test / Security`, job: `security`) — Trivy scan for dependency CVEs, secrets, and misconfigurations
- `test-pkgbuild.yml` (`Test / PKGBUILD`, job: `pkgbuild`) — Arch Linux package build + smoke test
- `publish-pypi.yml` (`Publish / PyPI`, job: `pypi`) — Build and publish to PyPI on tag push
- `publish-github-release.yml` (`Publish / GitHub Release`, job: `github-release`) — Create a GitHub Release on tag push

### Continuous Deployment

Kvet is published to PyPI via the `publish-pypi.yml` GitHub Actions workflow. NOTE: publishing under the `kvet` name requires the project to be registered on PyPI first. Deployment is triggered by pushing a git tag that starts with `v` (e.g. `v0.2.0`).

### Releasing a new version

1. Create and checkout a branch to bump the version, using the naming convention `{name}/v{version}` (e.g. `john/v0.2.0`)
2. Update the version in `pyproject.toml`
3. Update `pkgver` in `pkg/arch/PKGBUILD`
4. Commit and push the changes
5. Tag the commit and push the tag:
   ```bash
   git tag v0.2.0 -m "v0.2.0: Updated XYZ"
   git push origin v0.2.0
   ```
6. Create a PR for the new branch
7. The `Publish / PyPI` workflow will automatically build and publish the package
8. Merge PR into main.

## Development Notes

### Logging

When creating a new entry point into kvet, you must call `configure_logging(verbose: int, log_file: Path | None)` from `kvet.cli.main`.

User-facing status messages (top-level lifecycle, warnings visible to the user) use `print(..., file=sys.stderr)` directly — not loguru. Loguru is for internal diagnostics only.

Log level heuristics:

- **TRACE** - API payloads, token counts, dollar costs, agent subprocess messages.
- **DEBUG** - Everything internal: API exceptions before re-raise, retries, fallbacks, identifier selection, history loading, context assembly. All LLM provider exception handlers must log at DEBUG before raising (see `_openai_exception_manager` for the pattern).
- **WARNING** - Degraded conditions: LLM content blocked/flagged, unrecognized config values, malformed user data. Note: spend limit warnings also `print()` directly to stderr so they are always visible to the user.
- **ERROR** - Failures that prevent producing results. Use `log_exception()` from `kvet.imbue_core.async_monkey_patches` for tracebacks.

### README links

The README is rendered on PyPI which does not resolve relative links that otherwise work on GitHub. Always use full URLs when linking to resources from the README.
