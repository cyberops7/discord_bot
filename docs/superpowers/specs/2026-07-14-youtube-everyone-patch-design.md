# Patch 0.12.1 — YouTube `@everyone` fix + small backlog items

## Overview

A patch release bundling one user-facing rendering bug with three small,
low-risk correctness/tooling fixes drawn from the backlog. Each change is
self-contained and preserves 100% branch coverage.

Version: `0.12.0` → `0.12.1`.

## Motivation

When a new YouTube video is posted to `#announcements`, the notification renders
the literal text `<@everyone>` (angle brackets visible) instead of pinging
everyone. Discord only accepts the `<...>` wrapper for **ID-based** mentions
(`<@&roleid>`, `<@userid>`); `@everyone` and `@here` are literal-text mentions
and must be sent unwrapped. The bracketed form neither pings nor renders
cleanly.

While in this area, three small backlog items are rolled in to make the patch
worthwhile.

## Changes

### 1. Fix `@everyone` mention (primary)

**File:** `lib/cogs/tasks.py:330`

```python
# Before
await channel.send(content="<@everyone>", embed=embed)
# After
await channel.send(content="@everyone", embed=embed)
```

**Test:** The existing announcements-channel test
(`tests/cogs/test_tasks.py`, `test_monitor_youtube_videos` variant that asserts
the `#announcements` channel is used) currently only asserts `send` was called.
Tighten it to assert the call was made with `content="@everyone"` so a
regression to the bracketed form fails the suite.

### 2. Fix wrong channel ID in the "channel not found" warning

**File:** `lib/cogs/tasks.py:332-337`

The channel is **selected** using `config.DRY_RUN_YOUTUBE`
(`tasks.py:298-301`), but the fallback warning logs the channel ID chosen by
`config.DRY_RUN`. When the two flags differ, the warning names the wrong
channel. Change the warning's ternary to use `config.DRY_RUN_YOUTUBE` so it
matches the selection logic.

**Test:** In the existing `channel not found` test(s)
(`tests/cogs/test_tasks.py:1092+`), assert the warning message contains the
**correct** channel ID for the active `DRY_RUN_YOUTUBE` value, not just the
`"Could not find channel with ID"` prefix.

### 3. Use direct key access for the required `created_at` field

**File:** `lib/github.py:154-155`

`created_at` is a **required** key on the `GitHubIssue` TypedDict
(`github.py:56`), and sibling required fields (`title`, `html_url`) already use
direct subscript access. Line 154 inconsistently uses `.get()`.

```python
# Before
created = _parse_dt(issue.get("created_at"))
if created and created > self._started_at:
# After
created = _parse_dt(issue["created_at"])
if created > self._started_at:
```

**Coverage note:** With direct access, `_parse_dt(issue["created_at"])` always
returns a non-`None` datetime for well-formed data, so the falsy-`created`
branch of `if created and ...` becomes unreachable and would break 100% branch
coverage. Dropping the now-dead `created and` guard removes that branch. The
`None` return of `_parse_dt` remains exercised via `closed_at`
(`github.py:158`, which legitimately stays `.get()` since `closed_at` is
`NotRequired`/nullable).

**Test:** Adjust any existing test that fed an issue lacking `created_at` to
exercise the removed branch; ensure every derive-events test supplies
`created_at`. Verify full suite still reports 100% branch coverage.

### 4. Make the `uv-lock` pre-commit hook check-only

**File:** `.pre-commit-config.yaml:25-30`

The `uv-lock` hook currently **rewrites** `uv.lock` on drift. Per the backlog
item ("Fix pre-commit uv.lock to only check, not change uv.lock"), add the
`--check` arg so the hook **fails** on drift instead of silently mutating the
lockfile:

```yaml
- id: uv-lock
  description: Ensure uv's lock file matches deps in pyproject.toml
  args: ["--check"]
```

No application code changes.

### 5. Version bump

Per repo convention (CLAUDE.md):

- `pyproject.toml`: `version = "0.12.0"` → `"0.12.1"`.
- `kubernetes/discordbot.yaml`: bump the image tag to match `0.12.1`.

## Out of scope (explicitly closed)

- **GraphQL linkage short-circuit** — investigated and **rejected**, not
  deferred. `closingIssuesReferences` is bundled into the per-PR
  `_resolve_pr_close_details` query that runs anyway for closer attribution
  (`github.py:263`), so short-circuiting saves **zero** API calls and provides
  no rate-limit relief, while adding a threaded flag + branched query + doubled
  test shapes. Premature optimization. The KB open-thread has been removed.

## Testing & verification

- `uv run ruff format` then `uv run invoke check` (ruff, bandit, pyrefly,
  hadolint, markdownlint, yamllint, shellcheck) must pass.
- `uv run pyrefly check` clean.
- `uv run invoke test` — 100% branch coverage maintained.
- All commits individually pass blocking pre-commit hooks.

## Delivery

A dedicated feature branch off `main`, then a PR (not a local merge) with all
pipeline checks green, per repo standard.
