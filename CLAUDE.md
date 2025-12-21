# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code
in this repository.

## Project Overview

This is a Discord bot for Jim's Garage Discord Server. The bot runs a FastAPI
webserver in parallel to provide an API for interacting with the bot. The
application is packaged as a Docker container.

## Development Setup

### Environment Management

This project uses `uv` for Python dependency management. **Do not use pip,
pipx, poetry, or other tools.**

```shell
# Sync dependencies
uv sync --frozen

# Add runtime dependency
uv add package-name

# Add dev dependency
uv add --dev package-name

# Add test dependency
uv add --group test package-name
```

### Initial Setup

```shell
# Sync Python environment
uv sync --frozen

# Check for required non-Python dependencies
invoke deps

# Create .env file from sample
cp sample.env .env

# Install pre-commit hooks
pre-commit install
```

### Running the Application

```shell
# Run directly with uv (for development)
uv run main.py

# Build Docker image
invoke build --tag test

# Run Docker container
invoke run --tag test
```

## Pre-Commit Configuration

This project uses pre-commit hooks to enforce code quality standards on every
commit. **All commits must pass pre-commit checks before they can be
committed.**

### Pre-Commit Hooks

The `.pre-commit-config.yaml` defines three hooks that run automatically:

1. **run-checks** (BLOCKING)
   - Runs: `uv run invoke check`
   - Executes: `scripts/check.sh` which includes:
      - ruff format (Python formatting)
      - ruff check (Python linting)
      - bandit (security linting)
      - Type checking (pyrefly check)
      - hadolint (Dockerfile linting)
      - markdownlint (Markdown linting)
      - yamllint (YAML linting)
      - shellcheck (Bash script linting)
   - **Status**: Must pass for commit to succeed

2. **run-tests** (NON-BLOCKING)
   - Runs: `uv run invoke test --allow-failure`
   - Executes: pytest with coverage checks
   - **Status**: Runs but does not block commits (informational only)

3. **uv-lock** (BLOCKING)
   - Ensures `uv.lock` matches dependencies in `pyproject.toml`
   - Auto-runs when `pyproject.toml` changes
   - **Status**: Must pass for commit to succeed

### Planning Multi-Commit Work

When planning work that will be split across multiple commits (e.g., migrations,
refactoring), you must ensure **each individual commit passes all blocking
pre-commit checks**. Consider these guidelines:

1. **Atomic commits**: Each commit should be a complete, working change that
   passes all checks
2. **Dependency ordering**: If changing the type checker, linter config, or
   dependencies:
   - Update the tool invocation FIRST (e.g., change `scripts/check.sh` to use
     new tool)
   - Then make code changes that the new tool requires
   - Then clean up old tool configuration/dependencies
3. **Version bumping**: Best practice is to bump version in the first commit of
   a PR (not a pre-commit requirement)
4. **Testing strategy**: While tests are non-blocking, aim to keep tests
   passing for each commit

### Example: Type Checker Migration

If migrating from Tool A to Tool B:

**❌ Wrong approach** (commit 2 will fail):

- Commit 1: Convert all ignore comments from Tool A to Tool B syntax
- Commit 2: Update `scripts/check.sh` to use Tool B (FAILS - Tool A can't
  understand Tool B syntax)

**✅ Correct approach** (all commits pass):

- Commit 1: Update `scripts/check.sh` to use Tool B, convert ignore comments,
  and fix errors
- Commit 2: Remove Tool A dependency and configuration
- Commit 3: Update documentation

### Bypassing Pre-Commit (Emergency Only)

In rare cases, you may need to commit without running hooks:

```shell
git commit --no-verify -m "emergency fix"
```

**Warning**: Only use this for emergencies. CI/CD will still enforce all
checks, so bypassing locally just delays the problem.

## Common Commands

```shell
# Code quality checks
invoke check              # Run all linters and checks
invoke fix                # Run checks with auto-fix enabled
pre-commit run --all-files  # Manually run pre-commit hooks

# Testing
invoke test               # Run pytest locally
invoke test-docker        # Run pytest in Docker
pytest path/to/test_file.py  # Run specific test file
pytest path/to/test_file.py::test_function  # Run single test

# Type checking
pyrefly check             # Run Pyrefly type checker

# Linting individual tools (from within venv)
ruff format               # Format Python files
ruff check                # Run ruff linting checks

# Docker operations
invoke build --tag my-tag # Build with custom tag
invoke scan               # Vulnerability scan with Trivy
invoke clean              # Clean up Docker resources
```

## Markdown Formatting Requirements

This project enforces strict markdown linting via markdownlint. Configuration
is in `.markdownlint.rb`.

### Key Rules

**Line Length (MD013)**:

- Maximum 80 characters per line
- Exception: Code blocks and tables are ignored
- Wrap long lines by breaking at logical points

**List Indentation (MD007)**:

- Nested lists use **3-space indentation** (not 2 or 4)
- Example:

   ```markdown
   - Parent item
      - Nested item (3 spaces)
      - Another nested item (3 spaces)
   ```

**Ordered Lists (MD029)**:

- Use sequential numbering (1., 2., 3., etc.)
- Do not use all 1. for every item
- Configuration: `:ordered` style

**Blank Lines Around Lists (MD032)**:

- Always include blank line before a list
- Always include blank line after a list

**Consistent Indentation (MD005)**:

- All items at the same nesting level must use identical indentation
- Mixing 2-space and 3-space indentation in the same document will fail

### Testing Markdown Changes

Before committing markdown changes:

```shell
# Run markdownlint via Docker (same as pre-commit)
docker run --rm -i -v ./:/data markdownlint/markdownlint ./ .github/

# Or run via invoke check
uv run invoke check
```

## Architecture

### Application Entry Point

- `main.py`: Driver script that initializes Config, sets up logging, validates
  API port, and starts the FastAPI server using uvicorn
- The FastAPI app startup automatically launches the Discord bot via the
  `lifespan` context manager

### Core Components

**lib/api.py**: FastAPI application

- Defines the FastAPI app with lifespan management
- Starts the Discord bot asynchronously during app startup
- Provides endpoints: `/healthcheck`, `/status`, `/docs`, `/redoc`
- Stores bot instance in `app.state` for access by API endpoints

**lib/bot.py**: DiscordBot class (extends discord.ext.commands.Bot)

- Central bot implementation with event handlers
- Dynamically loads cogs from `lib/cogs/` directory
- Provides logging methods: `log_to_channel()`, `log_bot_event()`,
  `log_moderation_action()`, `log_user_action()`
- Implements spam detection and auto-banning via `ban_spammer()`
- Handles member join/leave events and welcome messages
- On startup: loads cogs, syncs commands, stores log channel reference in
  config

**lib/config.py**: Configuration singleton

- Loads configuration from `conf/config.yaml`
- Supports environment variable overrides (e.g., `CHANNELS_BOT_LOGS` overrides
  `CHANNELS.BOT_LOGS`)
- Loads version from `pyproject.toml`
- Provides attribute-based access via `ConfigDict` wrapper
- `config` is a singleton instance imported throughout the codebase

**lib/config_parser.py**: YAML config token resolver

- Resolves special tokens in config values: `@env`, `@format`, `@math`
- Example: `"@env BOT_TOKEN,default_value"` retrieves environment variable
  with fallback
- Used for dynamic configuration values

**lib/youtube.py**: YoutubeFeedParser class

- Parses YouTube RSS feeds to detect new videos
- Maintains `seen_videos` set to track already-processed videos
- Used by the `monitor_youtube_videos` background task

**lib/cogs/**: Bot extensions (Cogs)

- `basic_commands.py`: Simple slash commands
- `tasks.py`: Background tasks using discord.ext.tasks
   - `clean_channel_members_task`: Weekly cleanup of members who haven't
     accepted rules
   - `monitor_youtube_videos`: Checks YouTube RSS feeds every 5 minutes for
     new videos

### Logging

**lib/logger_setup.py**: Configures colorlog for both file and stdout logging

- Uses environment variables: `LOG_DIR`, `LOG_FILE`, `LOG_LEVEL_FILE`, `LOG_LEVEL_STDOUT`
- Provides consistent logging format across the application

**lib/bot_log_context.py**: LogContext dataclass for Discord channel logging

- Defines structure for logging to Discord channels with embeds
- Used by bot logging methods to send formatted messages to Discord

## Code Quality Requirements

All PRs must pass:

- **ruff**: Python formatting and linting (configured in pyproject.toml)
- **pyrefly**: Strict type checking
- **bandit**: Security linting
- **pytest**: 100% test coverage required (including branch coverage)
- **trivy**: Container vulnerability scanning
- **hadolint**: Dockerfile linting
- **markdownlint**: Markdown linting
- **yamllint**: YAML linting
- **shellcheck**: Bash script linting

## Important Development Guidelines

1. **Keep main.py minimal**: Extend functionality in `lib/` modules, not in
   main.py
2. **Build Discord features around DiscordBot class**: Add methods to
   `lib/bot.py` or create new cogs in `lib/cogs/`
3. **Fix errors immediately**: When encountering lint, type check, or unit
   test errors, fix them immediately rather than investigating whether they are
   pre-existing issues. The pre-commit hooks ensure quality, so any failure
   should be addressed right away.
4. **Use the logger, not print()**: Import logging and use logger throughout
5. **Version bumping**: Every PR must increment the version in `pyproject.toml`
   following semantic versioning
6. **Configuration**: All configuration values go in `conf/config.yaml`, access
   via the `config` singleton
7. **Environment variables**: Use `.env` file for local development
   (gitignored). Environment variables override config.yaml values.
8. **Cog structure**: New cogs are automatically loaded from `lib/cogs/` if
   they inherit from `commands.Cog`
9. **Background tasks**: Use `discord.ext.tasks` decorators and implement in
   cogs (see `lib/cogs/tasks.py`)
10. **Type hints**: Use strict typing throughout. Pyrefly is configured for
    strict mode.
11. **DRY_RUN mode**: Respect `config.DRY_RUN` flag for testing without side
    effects
12. **Code formatting**: Always run `uv run ruff format` before running checks
    or committing code
13. **Type checking before commits**: Always run `uv run pyrefly check` before
    creating commits to catch type errors early

## Configuration System

The config system supports:

- YAML-based configuration in `conf/config.yaml`
- Environment variable overrides (nested keys use underscore, e.g., `CHANNELS_BOT_LOGS`)
- Special token resolution: `@env`, `@format`, `@math`
- Access via singleton: `from lib.config import config`
- Nested access: `config.CHANNELS.BOT_LOGS`, `config.ROLES.ADMIN`, etc.

## Testing

- Tests are in `tests/` directory
- `conftest.py` provides shared fixtures
- Use `pytest-mock` for mocking
- Use `pytest-asyncio` for async tests
- Coverage must be 100% (including branch coverage)
- Test markers available: `@pytest.mark.no_mock_config` to exclude mock_config fixture
- Environment variables for pytest theme configured in pyproject.toml

## Docker

The application is containerized with multi-stage builds:

- Production image: `ghcr.io/cyberops7/discord_bot`
- Test image: `ghcr.io/cyberops7/discord_bot_test` (includes test
  dependencies)

Container environment variables: `API_PORT`, `BOT_TOKEN`, `LOG_DIR`,
`LOG_FILE`, `LOG_LEVEL_FILE`, `LOG_LEVEL_STDOUT`, `DRY_RUN`

## Key Files

- `pyproject.toml`: Python project metadata, dependencies, and tool
  configurations
- `conf/config.yaml`: Application configuration
- `tasks.py`: Invoke task definitions for common operations
- `scripts/`: Bash scripts for build, test, scan operations (wrapped by invoke
  tasks)
- this project is packaged as a docker image, but is run in production in a
  kubernetes cluster
