# Inline TODO cleanup + robust spam-message capture

## Overview

A backlog-burndown batch resolving the six `TODO @cyberops7` markers in
application code, plus a tightly-coupled improvement to how banned spam
messages are captured and displayed. Every change is self-contained and
preserves 100% branch coverage.

Version: `0.12.1` → `0.13.0` (new behavior: robust message capture,
fail-fast startup, thread-aware ban handling).

## Motivation

Two threads converge in this batch:

1. **Inline debt.** Six `TODO @cyberops7` comments mark small, concrete
   fixes across `main.py`, `lib/utils.py`, `lib/bot.py`, and
   `lib/cogs/tasks.py`. They are cheap to resolve and each produces a
   reviewable diff.
2. **A moderation blind spot** surfaced while reviewing the ban code. On
   2026-07-12 a `#mousetrap` ban fired on a message whose `message.content`
   was empty (an attachment or sticker). The bot logs only `message.content`
   and discord.py's default `Message` repr, so the actual payload was never
   recorded — it is unrecoverable from disk or Loki. The #bot-logs embed also
   dropped its "Message" field because `_send_log_embed` suppresses fields
   with empty values. The bot is blind to exactly the payload types that
   showed up.

## Design principles

- **Two sinks, two fidelities.** The #bot-logs embed gets a concise,
  safe summary; the on-disk/Loki log gets a full, faithful dump. Diffing the
  two later reveals what any embed dropped.
- **Config over constants** for deployment-tunable values, via the existing
  `config` singleton (project convention).
- **Fail loudly** on unrecoverable startup errors rather than running
  half-initialized.
- **Small, pure, testable units** for message formatting.

## Changes

### 1. Config routing

**Files:** `conf/config.yaml`, `main.py:32`, `lib/utils.py:5`

Add flat top-level keys to `conf/config.yaml` (alphabetically placed):

```yaml
API_HOST: "0.0.0.0"
PORT_MAX: 65535
PORT_MIN: 0
```

- `main.py`: replace the hardcoded host with `host=config.API_HOST`; keep
  `# noqa: S104` (the default still binds all interfaces, required in the
  container/k8s deployment). The `API_HOST` env var overrides it via the
  config system automatically.
- `lib/utils.py`: import the `config` singleton and reference
  `config.PORT_MIN` / `config.PORT_MAX` inside `ensure_valid_port`; drop the
  module-level constants. Defaults are unchanged, so validation behavior is
  identical.

**Tests:** update `tests/test_main.py` (assert `uvicorn.run` is called with
`host=config.API_HOST`) and any `test_utils` reference to the former module
constants.

### 2. Fail-fast startup exceptions

**File:** `lib/bot.py:151,155`

Wrap `await self._load_cogs()` and `await self.tree.sync()` each in
`try/except`, `logger.exception(...)` with context, then re-raise so a broken
startup surfaces loudly. A bot that cannot load cogs or sync commands is
broken; it must not run half-dead.

**Lint note:** a blind `except Exception` that re-raises may trip ruff
`BLE001`. Resolve cleanly — log then bare `raise` — adding a scoped
`# noqa: BLE001` only if the re-raise pattern still triggers it.

**Tests:** add branch coverage for each site: the success path and the
raising path (assert the exception propagates and `logger.exception` was
called).

### 3. Thread-aware ban handling

**File:** `lib/bot.py:490`

Widen the `ban_spammer` channel guard from `discord.TextChannel` to
`discord.TextChannel | discord.Thread` so a spammer posting in a thread is
banned too. Both types expose `.name` for logging, and the ban acts on the
user regardless of channel type. Widen the local `channel` annotation
accordingly, and `log_moderation_action`'s `channel` parameter if pyrefly
requires it.

**Tests:** add a `discord.Thread` case to the `ban_spammer` channel-type
tests.

### 4. Drop the #general-chat TODO

**File:** `lib/bot.py:560`

Remove the comment only. #bot-logs remains the moderation record; no public
ban announcement is wanted. No behavior change.

### 5. tasks.py refactor + fragility fix

**File:** `lib/cogs/tasks.py:24`

Extract a `_bootstrap_tasks()` helper from `__init__`, and initialize
`self.youtube_feeds = {}` and `self.github_monitor = None`
**unconditionally** (outside the `is_running()` guards) so `cog_unload` can
never `AttributeError` on abnormal re-init (a latent bug noted in the KB).
The task-start guards stay as-is.

**Tests:** cover the refactored bootstrap and confirm `cog_unload` is safe
when the tasks were never started.

### 6. Robust message formatting (new)

**File:** `lib/message_format.py` (new), consumed by `lib/bot.py`

A new module with two pure functions over `discord.Message`.

#### `summarize_message(message, max_length=config.EMBED_MAX_LENGTH) -> str`

Concise, safe summary for the #bot-logs embed. Always returns a non-empty
string so the embed field is never suppressed again.

- Text content: stripped, included when present.
- Attachments: `[N attachment(s): name1, name2]` — filenames only, **no
  URLs** (the message is deleted within a day, so any CDN link is dead, and
  omitting it avoids re-surfacing a clickable link in #bot-logs).
- Stickers: `[sticker: name]`.
- Embeds: `[N embed(s)]`.
- Combines whatever is present; returns `[no displayable content]` when truly
  empty. Final result truncated to `max_length`.

#### `describe_message_full(message, max_content=4000) -> str`

Full-fidelity dump for the on-disk/Loki log. Nothing collapsed:

- full `message.content` up to a generous `max_content` safety cap;
- each attachment: filename, `content_type`, size, **and** URL;
- each embed: `embed.to_dict()`;
- each sticker: name + id;
- `message.id`, `message.type`, `message.flags`, and jump URL.

#### Call sites

- `log_moderation_action` (`lib/bot.py:390-404`): replace the inline
  `message_snippet` block with `summarize_message(message)` so the embed
  always shows a meaningful Message field.
- `ban_spammer` (`lib/bot.py`): log `describe_message_full(message)` at
  `WARNING` early in the method (before the ban/delete), so **every** ban
  path — not just #mousetrap — records the complete payload.
- `on_message` mousetrap block (`lib/bot.py:626-632`): collapse the two
  existing lines (empty-content log + `Message object: <repr>`) to a single
  concise breadcrumb; the full dump now lives in `ban_spammer`.

**Tests:** unit-test both functions in isolation across text-only,
attachment-only, sticker-only, embed-only, combined, and empty messages;
update the `log_moderation_action` and `on_message`/`ban_spammer` tests for
the new call sites.

## Non-goals

- No public ban announcements (#general-chat dropped).
- No change to spam-*detection* logic; only capture and display.
- `PORT_MIN`/`PORT_MAX` move to config for convention consistency, not
  because they are expected to change.

## Testing & release

- 100% branch coverage maintained; run `uv run invoke check` and
  `uv run invoke test`.
- Bump `version` in `pyproject.toml` to `0.13.0` and the image tag in
  `kubernetes/discordbot.yaml` to `v0.13.0`.

## Plan closeout (for the implementation plan's final task)

- `docs/TODO.md`: the six inline TODOs are code comments, not checklist
  entries, so nothing to check off there; add a note if any follow-up is
  discovered.
- `CLAUDE.md`: fold in any convention or gotcha the work surfaces.
- KB (`~/code/kb`): update the `Jim's Garage Discord Bot` project note (close
  the `github_monitor`/`youtube_feeds` init-fragility open thread; record the
  message-capture improvement) and today's daily note, per `/kb-update`.
