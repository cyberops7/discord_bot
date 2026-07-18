# Inline TODO cleanup + robust spam-message capture

## Overview

A backlog-burndown batch resolving the six `TODO @cyberops7` markers in
application code, plus a tightly-coupled improvement to how banned spam
messages are captured and displayed. Every change is self-contained and
preserves 100% branch coverage.

Version: `0.12.1` → `0.13.0` (new behavior: robust message capture,
process-level fail-fast startup, thread-aware ban handling).

This revision incorporates three expert reviews (discord.py, Python, and
operations). The most consequential change from the first draft: naive
"fail-fast" in an `on_ready` handler is a no-op (discord.py swallows handler
exceptions), so startup validation moves to `setup_hook` and is wired to
actually terminate the process.

## Motivation

Two threads converge in this batch:

1. **Inline debt.** Six `TODO @cyberops7` comments mark small, concrete
   fixes across `main.py`, `lib/utils.py`, `lib/bot.py`, and
   `lib/cogs/tasks.py`.
2. **A moderation blind spot** surfaced while reviewing the ban code. On
   2026-07-12 a `#mousetrap` ban fired on a message whose `message.content`
   was empty (an attachment or sticker). The bot logs only `message.content`
   and discord.py's default `Message` repr, so the actual payload was never
   recorded — it is unrecoverable from disk or Loki. The #bot-logs embed also
   dropped its "Message" field because `_send_log_embed` suppresses fields
   with empty values. The bot is blind to exactly the payload types that show
   up in this channel.

The bot connects with `Intents.all()`, which forces the Message Content
privileged intent, so an empty `message.content` genuinely means a non-text
payload — not a missing intent. The design premise holds.

## Design principles

- **Two sinks, two fidelities.** The #bot-logs embed gets a concise, safe
  summary; the on-disk/Loki log gets a full, single-line, faithful dump.
- **Config over constants only where a value is deployment-tunable.**
  `API_HOST` is; the protocol port bounds (0–65535) are not.
- **Fail-fast must actually terminate the process.** Logging loudly from a
  swallowed event handler is not fail-fast.
- **Small, pure, testable units** for message formatting.

## Changes

### 1. Config: API_HOST only

**Files:** `conf/config.yaml`, `main.py`, `lib/utils.py`

- Add `API_HOST: "0.0.0.0"` to `conf/config.yaml`. `main.py` uses
  `host=config.API_HOST`. The default binds all interfaces (required so the
  kubelet can reach the pod for liveness/readiness probes); the `API_HOST`
  env var overrides it via the config system. Remove the now-unused
  `# noqa: S104` from `main.py` (the literal leaves the code, so the directive
  would trip ruff `RUF100`).
- **`PORT_MIN`/`PORT_MAX` stay module constants** in `lib/utils.py`. They are
  protocol invariants, not deployment config; making them env-overridable adds
  a footgun (a bad range would reject valid ports) with no upside. Drop the
  TODO and add a one-line clarifying comment.

### 2. Robust message formatting (new)

**File:** `lib/message_format.py` (new), consumed by `lib/bot.py`

Two pure functions over `discord.Message`.

`summarize_message(message, max_length=None) -> str` — concise, safe summary
for the #bot-logs embed. Always returns a non-empty string so the embed field
is never suppressed. Includes: text content (stripped); attachment filenames
(no URLs); sticker names; embed count; poll and forwarded-message markers.
Falls back to `[no displayable content]`. Truncated to `max_length` (defaults
to `config.EMBED_MAX_LENGTH`).

`describe_message_full(message, max_content=4000) -> str` — full-fidelity,
**single-line** dump for the log file (single-line so Loki/promtail keeps it
as one queryable entry). Captures `id`, `type`, `flags`, `jump_url`, full
`content` (capped, `repr`-escaped so newlines can't fragment the line or be
injected), and every attachment (filename, content_type, size, URL), embed
(`to_dict()`), sticker (name, id), poll, and forwarded snapshot. `poll` and
`message_snapshots` are read via `getattr` for version tolerance.

**Content-type coverage** (all empty-`content` vectors): attachments,
stickers, embeds, polls, and forwarded message snapshots.

### 3. Use summarize_message for the moderation embed

**File:** `lib/bot.py` (`log_moderation_action`)

Replace the inline 500-char snippet with `summarize_message(message)`, so the
embed always shows a meaningful Message field, truncated to
`EMBED_MAX_LENGTH` (Discord's field-value limit). While here, fix a
pre-existing bug at the `extra_embed_fields` loop: the debug log passes the
imported `field` function instead of the loop variable `embed_field`.

### 4. Thread-aware ban handling

**Files:** `lib/bot.py` (`on_message`, `ban_spammer`,
`log_moderation_action`), `lib/bot_log_context.py`

The ban path only fires from `on_message` when the message is in
`#mousetrap`. A message in a **thread** under #mousetrap has
`channel.id == <thread id>`, not the mousetrap id — so the existing gate never
catches thread spammers, and widening only `ban_spammer` would be dead code.
Widen the `on_message` gate to also match a `discord.Thread` whose
`parent_id == config.CHANNELS.MOUSETRAP`, and widen the `ban_spammer` channel
guard to `discord.TextChannel | discord.Thread`. Propagate the type through
`ban_spammer`'s local `channel`, `log_moderation_action`'s `channel`
parameter, and `LogContext.channel`. `LogContext.log_channel` stays
`TextChannel` (#bot-logs is a text channel).

### 5. Capture full payload on every ban

**File:** `lib/bot.py` (`ban_spammer`, `on_message`)

- Log `describe_message_full(message)` at **INFO** (a moderation record, not
  an anomaly; INFO avoids polluting warning-rate metrics on every ban and
  every privileged-user false trigger) at the **very top** of `ban_spammer`,
  before the guard returns — so no early-exit path is blind.
- Collapse the `on_message` mousetrap logging (empty-content line +
  `Message object: <repr>`) into a single concise breadcrumb; the full dump
  now lives in `ban_spammer`.
- Drop the `# TODO: also log to #general-chat` comment (public ban
  announcements are not wanted).

Attachment CDN URLs are kept in the full dump (they expire ~24h; useful for
immediate triage — a conscious trade-off, not a durable link).

### 6. Fail-fast startup (process-level)

**Files:** `lib/bot.py` (`setup_hook`, `on_ready`), `lib/api.py` (lifespan)

Move cog loading and command sync out of `on_ready` (a discord.py event
handler whose exceptions are swallowed by the dispatcher) into `setup_hook`,
which runs once during login; exceptions there propagate out of
`bot.start()`. Neither needs the connection cache, so the move is safe. The
LOG_CHANNEL resolution and the "Bot Startup" event stay in `on_ready` (they
need the cache).

- **Cog load fails hard**: a bot that cannot load its cogs is broken — let it
  propagate and crash.
- **Command sync tolerates transient failures**: `tree.sync()` hits Discord's
  global rate limits; catch `discord.HTTPException`, log, and continue rather
  than crash-loop on a 429.

Wire the process exit in `lib/api.py`: the bot runs as a fire-and-forget
`asyncio.create_task`, so a raised exception would sit unretrieved. Attach a
done-callback that, if the bot task ended with an exception, logs it and
raises `SIGTERM`, so uvicorn shuts down gracefully and the pod restarts
(visible `CrashLoopBackOff`) instead of serving a half-dead bot.

### 7. tasks.py refactor + fragility fix

**File:** `lib/cogs/tasks.py`

Extract a `_bootstrap_tasks()` helper from `__init__`, and initialize
`self.youtube_feeds = {}` and `self.github_monitor = None` **unconditionally**
(outside the `is_running()` guards) so `cog_unload` can never `AttributeError`
on abnormal re-init (a latent bug noted in the KB).

## Non-goals

- No public ban announcements (#general-chat dropped).
- No change to spam-*detection* logic; only capture, display, and startup
  robustness.
- `_load_cogs` keeps its per-cog tolerance (one bad cog does not crash the
  bot); only a catastrophic load failure crashes.

## Testing & release

- 100% branch coverage maintained; run `uv run invoke check` and
  `uv run invoke test`.
- Bump `version` in `pyproject.toml` to `0.13.0` and the image tag in
  `kubernetes/discordbot.yaml` to `v0.13.0`. Deploy is merge-to-main (no git
  tag); CI builds/pushes the image and an in-cluster `check-image-exists`
  PreSync job gates the ArgoCD rollout until the image lands.

## Plan closeout (for the implementation plan's final task)

- `docs/TODO.md`: the six inline TODOs are code comments, not checklist
  entries; add any follow-up discovered.
- `CLAUDE.md`: fold in the surfaced conventions — event-handler exceptions are
  swallowed (do startup validation in `setup_hook`, not `on_ready`); a module
  reading `config` at call time must be added to the `mock_config` patch list
  in `tests/conftest.py`; widening a channel type to include `discord.Thread`
  also requires widening `LogContext.channel` and `log_moderation_action`.
- KB (`~/code/kb`): update the `Jim's Garage Discord Bot` project note (close
  the `github_monitor`/`youtube_feeds` init-fragility thread; record the
  two-tier message-capture design and the fail-fast/`setup_hook` finding) and
  today's daily note, per `/kb-update`.
