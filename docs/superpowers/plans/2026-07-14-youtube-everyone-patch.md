# YouTube `@everyone` Patch (0.12.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `<@everyone>` bracket rendering on YouTube announcements and
roll in three small backlog fixes as patch release 0.12.1.

**Architecture:** Four independent, self-contained edits (two in the YouTube
monitor cog, one in the GitHub monitor, one in pre-commit config), plus a
version bump. Each change carries its own test cycle where a test applies; each
commit passes all blocking pre-commit hooks on its own.

**Tech Stack:** Python 3.14, uv, discord.py, pytest (100% branch coverage),
ruff/pyrefly/bandit, pre-commit, GitHub Actions → ghcr → ArgoCD.

## Global Constraints

- Version bumps this release: `pyproject.toml` `0.12.0` → `0.12.1`;
  `kubernetes/discordbot.yaml` image tag `v0.12.0` → `v0.12.1` (must match). The
  `check-version` CI job fails if `pyproject.toml`'s version equals main's.
- 100% branch coverage is mandatory (`uv run invoke test`).
- Every commit must pass blocking pre-commit hooks (`run-checks`, `uv-lock`).
- Run `uv run ruff format` before checks/commits; run `uv run pyrefly check`
  before committing.
- No Claude/AI attribution in any git artifact (commits, PR title/body).
- Delivery is a feature branch → PR (not a local merge). Work happens on the
  already-created branch `youtube-everyone-patch`.

---

### Task 1: Version bump

**Files:**

- Modify: `pyproject.toml` (the `[project]` `version` field)
- Modify: `kubernetes/discordbot.yaml:75` (the `image:` tag)

**Interfaces:**

- Consumes: nothing.
- Produces: version `0.12.1` referenced by the release/deploy steps.

- [ ] **Step 1: Bump the project version**

In `pyproject.toml`, change:

```toml
version = "0.12.0"
```

to:

```toml
version = "0.12.1"
```

- [ ] **Step 2: Bump the image tag to match**

In `kubernetes/discordbot.yaml:75`, change:

```yaml
          image: ghcr.io/cyberops7/discord_bot:v0.12.0
```

to:

```yaml
          image: ghcr.io/cyberops7/discord_bot:v0.12.1
```

- [ ] **Step 3: Verify both changed and nothing else drifted**

Run: `git diff --stat`
Expected: exactly `pyproject.toml` and `kubernetes/discordbot.yaml` modified.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml kubernetes/discordbot.yaml
git commit -m "chore: bump version to 0.12.1"
```

Expected: pre-commit `run-checks` and `uv-lock` pass.

---

### Task 2: Fix `@everyone` mention brackets

**Files:**

- Modify: `lib/cogs/tasks.py:330`
- Test: `tests/cogs/test_tasks.py`
  (`TestTasks::test_monitor_youtube_videos_with_new_videos_announcements_channel`,
  ~line 981-1022)

**Interfaces:**

- Consumes: nothing.
- Produces: `channel.send` is called with `content="@everyone"` (unwrapped) on a
  new-video post.

- [ ] **Step 1: Tighten the existing test to assert the mention content**

In `tests/cogs/test_tasks.py`, add `ANY` to the mock import (line 8):

```python
from unittest.mock import ANY, AsyncMock, MagicMock, patch
```

In `test_monitor_youtube_videos_with_new_videos_announcements_channel`, replace
the existing send assertion (currently `mock_channel.send.assert_called_once()`,
~line 1022) with:

```python
        # Verify channel send was called with an unwrapped @everyone mention
        mock_channel.send.assert_called_once_with(content="@everyone", embed=ANY)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest "tests/cogs/test_tasks.py::TestTasks::test_monitor_youtube_videos_with_new_videos_announcements_channel" -v
```

Expected: FAIL — actual call is `content='<@everyone>'`, so
`assert_called_once_with(content="@everyone", ...)` raises AssertionError.

- [ ] **Step 3: Fix the mention in the cog**

In `lib/cogs/tasks.py:330`, change:

```python
                    await channel.send(content="<@everyone>", embed=embed)
```

to:

```python
                    await channel.send(content="@everyone", embed=embed)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest "tests/cogs/test_tasks.py::TestTasks::test_monitor_youtube_videos_with_new_videos_announcements_channel" -v
```

Expected: PASS.

- [ ] **Step 5: Format, check, commit**

```bash
uv run ruff format
uv run pyrefly check
git add lib/cogs/tasks.py tests/cogs/test_tasks.py
git commit -m "fix(youtube): send @everyone unwrapped so Discord pings instead of showing brackets"
```

---

### Task 3: Fix wrong channel ID in the "channel not found" warning

**Files:**

- Modify: `lib/cogs/tasks.py:332-337`
- Test: `tests/cogs/test_tasks.py` (`TestTasks`, new test near
  `test_monitor_youtube_videos_channel_not_found`, ~line 1092)

**Interfaces:**

- Consumes: nothing.
- Produces: the "Could not find channel" warning logs the same channel the
  selection logic chose (keyed on `config.DRY_RUN_YOUTUBE`).

**Background:** The channel is selected via `config.DRY_RUN_YOUTUBE`
(`tasks.py:298-301`) but the fallback warning picks the ID via `config.DRY_RUN`.
When those differ, the warning names the wrong channel. In the mock config,
`BOT_PLAYGROUND=123` and `ANNOUNCEMENTS=987`.

- [ ] **Step 1: Write a failing test where the two flags differ**

In `tests/cogs/test_tasks.py`, add this test method to `TestTasks` (place it
right after `test_monitor_youtube_videos_channel_not_found`, ~line 1118):

```python
    @async_test
    async def test_monitor_youtube_videos_not_found_warning_uses_youtube_flag(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """The not-found warning reports the channel the selection logic chose.

        Selection keys on DRY_RUN_YOUTUBE, so with DRY_RUN_YOUTUBE=True (→
        BOT_PLAYGROUND=123) and DRY_RUN=False, the warning must name 123, not
        the ANNOUNCEMENTS id 987.
        """
        mock_config.DRY_RUN = False
        mock_config.DRY_RUN_YOUTUBE = True

        mock_feed_parser = MagicMock()
        mock_feed_parser.get_new_videos.return_value = ["video1"]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        # Channel not found so the warning branch runs
        tasks_cog.bot.get_channel = MagicMock(return_value=None)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        message = warning_records[0].getMessage()
        assert "123" in message
        assert "987" not in message
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest "tests/cogs/test_tasks.py::TestTasks::test_monitor_youtube_videos_not_found_warning_uses_youtube_flag" -v
```

Expected: FAIL — the warning currently uses `config.DRY_RUN` (False) → logs
`987`, so `assert "123" in message` fails.

- [ ] **Step 3: Fix the warning's channel-ID selection**

In `lib/cogs/tasks.py`, change the warning's ternary (currently lines 332-337):

```python
                logger.warning(
                    "Could not find channel with ID %s or it is not a TextChannel",
                    config.CHANNELS.BOT_PLAYGROUND
                    if config.DRY_RUN
                    else config.CHANNELS.ANNOUNCEMENTS,
                )
```

to key on `config.DRY_RUN_YOUTUBE` (matching the selection logic above):

```python
                logger.warning(
                    "Could not find channel with ID %s or it is not a TextChannel",
                    config.CHANNELS.BOT_PLAYGROUND
                    if config.DRY_RUN_YOUTUBE
                    else config.CHANNELS.ANNOUNCEMENTS,
                )
```

- [ ] **Step 4: Run the new test plus the existing not-found tests**

Run:

```bash
uv run pytest "tests/cogs/test_tasks.py::TestTasks" -k "not_found or wrong_type or warning_uses_youtube_flag" -v
```

Expected: PASS (all).

- [ ] **Step 5: Format, check, commit**

```bash
uv run ruff format
uv run pyrefly check
git add lib/cogs/tasks.py tests/cogs/test_tasks.py
git commit -m "fix(youtube): report the selected channel id in the not-found warning"
```

---

### Task 4: Use direct key access for the required `created_at` field

**Files:**

- Modify: `lib/github.py:154`
- Test: `tests/test_github.py` (no change — existing derive-events tests cover
  both branches)

**Interfaces:**

- Consumes: nothing.
- Produces: no signature change; `_derive_events` behavior is identical.

**Background:** `created_at` is a required key on the `GitHubIssue` TypedDict
(`github.py:56`); siblings `title`/`html_url` already use subscript access. The
`created and` guard on line 155 **stays** — `_parse_dt` returns `datetime |
None`, so it is needed for type-safety (dropping it makes pyrefly flag `None >
datetime`). Coverage is unaffected: coverage.py does not track the `and`
short-circuit as a separate branch, and the `if` is already exercised both ways
by the `AFTER` (true) and `BEFORE` (false) tests in `tests/test_github.py`.

- [ ] **Step 1: Change `.get()` to direct subscript access**

In `lib/github.py:154`, change:

```python
            created = _parse_dt(issue.get("created_at"))
```

to:

```python
            created = _parse_dt(issue["created_at"])
```

Leave line 155 (`if created and created > self._started_at:`) unchanged.

- [ ] **Step 2: Run the derive-events tests**

Run: `uv run pytest tests/test_github.py -k derive -v`
Expected: PASS (all), including `test_derive_new_issue_opened` and
`test_derive_ignores_opened_before_startup`.

- [ ] **Step 3: Type-check**

Run: `uv run pyrefly check`
Expected: clean — no `None`-comparison error on line 155.

- [ ] **Step 4: Commit**

```bash
uv run ruff format
git add lib/github.py
git commit -m "refactor(github): use direct key access for required created_at field"
```

---

### Task 5: Make the `uv-lock` pre-commit hook check-only

**Files:**

- Modify: `.pre-commit-config.yaml:28-29`

**Interfaces:**

- Consumes: nothing.
- Produces: the `uv-lock` hook fails on drift instead of silently rewriting
  `uv.lock`.

- [ ] **Step 1: Add the `--check` arg to the hook**

In `.pre-commit-config.yaml`, change the `uv-lock` hook (lines 27-29):

```yaml
      - id: uv-lock
        description: Ensure uv's lock file matches deps in pyproject.toml
```

to:

```yaml
      - id: uv-lock
        description: Ensure uv's lock file matches deps in pyproject.toml
        args: ["--check"]
```

- [ ] **Step 2: Verify the hook passes on the current (in-sync) lockfile**

Run: `uv run pre-commit run uv-lock --all-files`
Expected: PASS (lockfile matches `pyproject.toml`) and no file is modified by
the hook (`git status --short` shows no change to `uv.lock`).

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "ci: make uv-lock pre-commit hook check-only"
```

---

### Task 6: Full-suite verification and PR

**Files:**

- None (verification + delivery).

**Interfaces:**

- Consumes: Tasks 1-5.
- Produces: an open PR against `main` with green CI.

- [ ] **Step 1: Run the full check + test suite**

Run:

```bash
uv run invoke check
uv run invoke test
```

Expected: all linters/type-checks pass; pytest reports 100% branch coverage.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin youtube-everyone-patch
```

- [ ] **Step 3: Open the PR**

Use the `github` skill for the body. Title:
`fix(youtube): unwrap @everyone mention + small backlog fixes (0.12.1)`

Body should summarize: the `@everyone` render fix (with before/after), the
`DRY_RUN_YOUTUBE` warning fix, the `created_at` key-access cleanup, the
`uv-lock` check-only change, and the version bump. No AI attribution.

```bash
gh pr create --base main --head youtube-everyone-patch \
  --title "fix(youtube): unwrap @everyone mention + small backlog fixes (0.12.1)" \
  --body-file <path-to-body>
```

- [ ] **Step 4: Confirm all PR checks pass**

Run: `gh pr checks --watch`
Expected: `check-test` and `check-version` (and any other required checks) all
green.

---

## Post-merge (human-gated; per spec Deployment + Wrap-up)

These run after a human merges the PR — they are not code-editing tasks:

1. **Deploy (releasing-to-cluster, Mode A):** merge = release trigger. Watch
   `publish.yaml` (`gh run watch`), gate on
   `crane digest ghcr.io/cyberops7/discord_bot:v0.12.1`, verify ArgoCD
   `discordbot` Synced-to-merge-SHA + Healthy (a soft `--refresh` may miss the
   raw-URL manifest bump — use `--hard-refresh` if so), then pod-log smoke
   `kubectl -n discordbot logs deploy/bot` for the startup banner and the
   `Version 0.12.1` event in `#bot-logs`.
2. **KB update:** run the `kb-update` skill to record the patch and the
   verified-live line in `~/code/kb/01-Projects/Jim's Garage Discord Bot.md`.
3. **TODO updates:** mark the `uv-lock` "check, not change" item done in
   `docs/TODO.md`.
