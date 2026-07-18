# Inline TODO Cleanup + Robust Spam-Message Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the six `TODO @cyberops7` markers in application code and
add full-fidelity capture of banned spam messages, with no behavior
regressions.

**Architecture:** Deployment-tunable values move into `conf/config.yaml`
behind the `config` singleton. A new pure module `lib/message_format.py`
renders a `discord.Message` two ways: a concise safe summary for the
bot-logs embed and a full-fidelity dump for the on-disk/Loki log. Startup
becomes fail-fast, and ban handling becomes thread-aware.

**Tech Stack:** Python 3.13, discord.py, FastAPI/uvicorn, pytest +
pytest-mock + pytest-asyncio, uv, ruff, pyrefly.

## Global Constraints

- 100% branch coverage required; every task ends green under
  `uv run invoke test`.
- All linters/type checks must pass: `uv run invoke check` (ruff, bandit,
  pyrefly, hadolint, markdownlint, yamllint, shellcheck).
- Configuration values live in `conf/config.yaml`, accessed via the `config`
  singleton; env vars override them.
- Use `logger`, never `print()`.
- Version bump every PR: `pyproject.toml` `0.12.1` → `0.13.0`, and the image
  tag in `kubernetes/discordbot.yaml` `v0.12.1` → `v0.13.0`.
- Run `uv run ruff format` before every commit.
- Any module that reads `config` at call time must be added to the
  `mock_config` patch list in `tests/conftest.py`, or its tests will hit the
  real singleton.

---

### Task 1: Route API_HOST and PORT_MIN/PORT_MAX through config

**Files:**

- Modify: `conf/config.yaml`
- Modify: `lib/utils.py:5-7`
- Modify: `main.py:32-38`
- Modify: `tests/conftest.py` (mock_config values + patch list)
- Test: `tests/test_main.py`, `tests/test_utils.py`

**Interfaces:**

- Produces: `config.API_HOST: str`, `config.PORT_MIN: int`,
  `config.PORT_MAX: int` available on the config singleton.

- [ ] **Step 1: Add config keys**

In `conf/config.yaml`, add these top-level keys (keep the file alphabetical
where it already is — `API_HOST` above `API_PORT`, the `PORT_*` keys in the
`P` position):

```yaml
API_HOST: "0.0.0.0"
```

(place directly above the existing `API_PORT: 8080`), and:

```yaml
PORT_MAX: 65535
PORT_MIN: 0
```

(place them alphabetically, e.g. between `LOG_LEVEL_STDOUT` and `ROLES`).

- [ ] **Step 2: Extend the mock config fixture**

In `tests/conftest.py`, inside `mock_config`, after the
`mock_cfg.EMBED_MAX_LENGTH = 1024` line add:

```python
    mock_cfg.API_HOST = "0.0.0.0"  # noqa: S104
    mock_cfg.PORT_MIN = 0
    mock_cfg.PORT_MAX = 65535
```

Then extend the `with (...)` patch block to also patch the utils module (add
this line alongside the other `patch("lib.*.config", mock_cfg)` lines):

```python
        patch("lib.utils.config", mock_cfg),
```

- [ ] **Step 3: Update the failing test for main.py host**

In `tests/test_main.py`, in `test_main_successful_run`, add a host attribute
to the config instance (after `mock_config_instance.API_PORT = 8000`):

```python
    mock_config_instance.API_HOST = "0.0.0.0"  # noqa: S104
```

Leave the existing assertion `host="0.0.0.0"` as-is. Apply the SAME
`API_HOST` attribute line to `test_default_port` (after its
`mock_config_instance.API_PORT = 8080`), `test_main_dry_run_mode`, and
`test_main_dry_run_disabled` (after each `API_PORT = 8000`). Do NOT touch
`test_invalid_port` (it raises before uvicorn is called).

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `uvicorn.run` called with `host=<Mock ...>` (a Mock, not
`"0.0.0.0"`), because `main.py` still hardcodes the host and the config
attribute is now consulted only by the test, not the code.

- [ ] **Step 5: Point main.py at config.API_HOST**

In `main.py`, replace the TODO comment and the hardcoded host:

```python
    # Start the FastAPI app using Uvicorn. This also starts the bot.
    logger.info("Starting FastAPI server...")
    uvicorn.run(
        app,
        host=config.API_HOST,  # Bind address; default 0.0.0.0 # noqa: S104
        port=api_port,
        log_config=None,
    )
```

Note `main.py` already builds `config = Config()` locally in `main()`; use
that `config` variable (it is in scope). No new import needed.

- [ ] **Step 6: Point utils.py at config**

In `lib/utils.py`, remove the TODO and the two module constants, and read
from config instead:

```python
import logging
import sys
from logging import Logger

from lib.config import config

logger: Logger = logging.getLogger(__name__)


def ensure_valid_port(port: int) -> int:
    """Raise TypeError or ValueError if a port is invalid."""
    # noinspection PyUnreachableCode
    if not isinstance(port, int):
        msg = f"Port must be an integer, but got {type(port).__name__}: {port}"
        raise TypeError(msg)
    if not (config.PORT_MIN <= port <= config.PORT_MAX):
        msg = (
            f"Port {port} is not in the valid range "
            f"{config.PORT_MIN}-{config.PORT_MAX}"
        )
        raise ValueError(msg)
    return port
```

Leave `validate_port` unchanged below it.

- [ ] **Step 7: Run the full suite for the touched files**

Run: `uv run pytest tests/test_main.py tests/test_utils.py -v`
Expected: PASS. `test_utils` assertions (`... valid range 0-65535`) still hold
because the mock config supplies `PORT_MIN=0`, `PORT_MAX=65535`.

- [ ] **Step 8: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add conf/config.yaml lib/utils.py main.py tests/conftest.py \
  tests/test_main.py
git commit -m "feat(config): route API_HOST and port bounds through config"
```

---

### Task 2: Add the message-format module

**Files:**

- Create: `lib/message_format.py`
- Create: `tests/test_message_format.py`
- Modify: `tests/conftest.py` (patch list + mock_message fixture)

**Interfaces:**

- Produces:
   - `summarize_message(message: discord.Message, max_length: int | None =
     None) -> str` — concise, always non-empty, no attachment URLs, truncated
     to `max_length` (defaults to `config.EMBED_MAX_LENGTH`).
   - `describe_message_full(message: discord.Message, max_content: int = 4000)
     -> str` — full multi-line dump: id/type/flags/jump_url, full content
     (capped at `max_content`), and every attachment (filename, content_type,
     size, url), embed (`to_dict()`), and sticker (name, id).

- [ ] **Step 1: Extend conftest for the new module and message payloads**

In `tests/conftest.py`, add to the `with (...)` patch block:

```python
        patch("lib.message_format.config", mock_cfg),
```

And in the `mock_message` fixture, after `message.content = "test message"`,
add empty payload collections so the summarizer/describer see no
attachments/embeds/stickers by default:

```python
    message.attachments = []
    message.embeds = []
    message.stickers = []
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_message_format.py`:

```python
"""Unit tests for lib.message_format."""

from unittest.mock import MagicMock

import discord

from lib.message_format import describe_message_full, summarize_message


def _make_message(
    content: str = "",
    attachments: list[MagicMock] | None = None,
    embeds: list[MagicMock] | None = None,
    stickers: list[MagicMock] | None = None,
) -> MagicMock:
    """Build a mock discord.Message with the given payloads."""
    message = MagicMock(spec=discord.Message)
    message.content = content
    message.attachments = attachments or []
    message.embeds = embeds or []
    message.stickers = stickers or []
    message.id = 123
    message.jump_url = "https://discord.com/channels/1/2/3"
    message.type = discord.MessageType.default
    message.flags = MagicMock()
    return message


def _attachment(filename: str) -> MagicMock:
    attachment = MagicMock()
    attachment.filename = filename
    attachment.content_type = "image/png"
    attachment.size = 1234
    attachment.url = f"https://cdn.example/{filename}"
    return attachment


def _sticker(name: str) -> MagicMock:
    sticker = MagicMock()
    sticker.name = name
    sticker.id = 999
    return sticker


def _embed(title: str) -> MagicMock:
    embed = MagicMock()
    embed.to_dict.return_value = {"title": title}
    return embed


def test_summarize_text_only() -> None:
    message = _make_message(content="hello world")
    assert summarize_message(message) == "hello world"


def test_summarize_attachment_only_no_url() -> None:
    message = _make_message(attachments=[_attachment("pic.png")])
    result = summarize_message(message)
    assert result == "[1 attachment(s): pic.png]"
    assert "https://" not in result


def test_summarize_sticker_only() -> None:
    message = _make_message(stickers=[_sticker("wave")])
    assert summarize_message(message) == "[sticker: wave]"


def test_summarize_embed_only() -> None:
    message = _make_message(embeds=[_embed("spam")])
    assert summarize_message(message) == "[1 embed(s)]"


def test_summarize_combined() -> None:
    message = _make_message(
        content="look", attachments=[_attachment("a.jpg")]
    )
    assert summarize_message(message) == "look\n[1 attachment(s): a.jpg]"


def test_summarize_empty() -> None:
    message = _make_message()
    assert summarize_message(message) == "[no displayable content]"


def test_summarize_truncates_to_max_length() -> None:
    message = _make_message(content="x" * 100)
    result = summarize_message(message, max_length=10)
    assert len(result) == 10
    assert result.endswith("...")


def test_describe_full_includes_all_payloads() -> None:
    message = _make_message(
        content="payload",
        attachments=[_attachment("evil.exe")],
        embeds=[_embed("phish")],
        stickers=[_sticker("boom")],
    )
    result = describe_message_full(message)
    assert "content='payload'" in result
    assert "filename='evil.exe'" in result
    assert "https://cdn.example/evil.exe" in result
    assert "size=1234" in result
    assert "{'title': 'phish'}" in result
    assert "name='boom'" in result
    assert "id=123" in result


def test_describe_full_caps_content() -> None:
    message = _make_message(content="y" * 5000)
    result = describe_message_full(message, max_content=100)
    assert "truncated 5000 chars" in result
    assert "y" * 5000 not in result
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_message_format.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.message_format'`.

- [ ] **Step 4: Implement the module**

Create `lib/message_format.py`:

```python
"""Render Discord messages for logging and moderation embeds."""

import logging

import discord

from lib.config import config

logger: logging.Logger = logging.getLogger(__name__)


def summarize_message(
    message: discord.Message, max_length: int | None = None
) -> str:
    """
    Build a concise, safe one-field summary of a message for a log embed.

    Always returns a non-empty string so the embed field is never suppressed.
    Attachment URLs are intentionally omitted (the message is deleted within a
    day, and the link should not be clickable in the log channel).
    """
    limit = max_length if max_length is not None else config.EMBED_MAX_LENGTH
    parts: list[str] = []

    content = message.content.strip()
    if content:
        parts.append(content)

    if message.attachments:
        names = ", ".join(a.filename for a in message.attachments)
        parts.append(f"[{len(message.attachments)} attachment(s): {names}]")

    if message.stickers:
        names = ", ".join(s.name for s in message.stickers)
        parts.append(f"[sticker: {names}]")

    if message.embeds:
        parts.append(f"[{len(message.embeds)} embed(s)]")

    summary = "\n".join(parts) if parts else "[no displayable content]"

    if len(summary) > limit:
        summary = f"{summary[: limit - 3]}..."
    return summary


def describe_message_full(
    message: discord.Message, max_content: int = 4000
) -> str:
    """
    Build a full-fidelity, multi-line description of a message for the log
    file. Captures every payload type so nothing is lost for later review.
    """
    content = message.content
    if len(content) > max_content:
        content = (
            f"{content[:max_content]}... (truncated {len(content)} chars)"
        )

    lines: list[str] = [
        f"id={message.id}",
        f"type={message.type!r}",
        f"flags={message.flags!r}",
        f"jump_url={message.jump_url}",
        f"content={content!r}",
    ]

    for i, attachment in enumerate(message.attachments):
        lines.append(
            f"attachment[{i}]: filename={attachment.filename!r} "
            f"content_type={attachment.content_type!r} "
            f"size={attachment.size} url={attachment.url}"
        )

    for i, embed in enumerate(message.embeds):
        lines.append(f"embed[{i}]={embed.to_dict()}")

    for i, sticker in enumerate(message.stickers):
        lines.append(f"sticker[{i}]: name={sticker.name!r} id={sticker.id}")

    return "\n".join(lines)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_message_format.py -v`
Expected: PASS (all 9 tests).

- [ ] **Step 6: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/message_format.py tests/test_message_format.py tests/conftest.py
git commit -m "feat(logging): add message-format helpers for moderation"
```

---

### Task 3: Use summarize_message for the moderation embed

**Files:**

- Modify: `lib/bot.py` (imports + `log_moderation_action` message field)
- Test: `tests/test_bot.py`
  (`test_log_moderation_action_with_message`)

**Interfaces:**

- Consumes: `summarize_message` from Task 2.

- [ ] **Step 1: Update the failing test**

In `tests/test_bot.py`, rewrite the long-message section of
`test_log_moderation_action_with_message` (currently asserting a 500-char
truncation) to reflect the summarizer's `EMBED_MAX_LENGTH` (1024) limit. The
mock config sets `EMBED_MAX_LENGTH = 1024`, so a 600-char message is NOT
truncated. Replace the block starting at
`# Test with a long message (more than max_msg_length)` through the end of the
method with:

```python
        # Reset mock for the next test
        mock_log_to_channel.reset_mock()

        # A 600-char message is under EMBED_MAX_LENGTH (1024), so it is
        # summarized in full with no ellipsis.
        long_message = "x" * 600
        mock_message.content = long_message

        result = await discord_bot.log_moderation_action(
            moderator=mock_mod,
            target=mock_user,
            action=action,
            reason=reason,
            message=mock_message,
        )

        assert result == "event_message"
        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]

        message_field = context.extra_embed_fields[0]
        assert message_field["name"] == "Message"
        assert message_field["value"] == long_message
        assert "..." not in message_field["value"]
        assert message_field["inline"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_bot.py -k log_moderation_action_with_message -v`
Expected: FAIL — value still truncated to 503 chars with `...`, because
`log_moderation_action` still uses the inline 500-char snippet.

- [ ] **Step 3: Wire in the summarizer**

In `lib/bot.py`, add the import near the other `from lib.*` imports:

```python
from lib.message_format import describe_message_full, summarize_message
```

(The `describe_message_full` import is consumed in Task 5; import both now.)

Then in `log_moderation_action`, replace the `message_snippet` block and the
`extra_embed_fields` value. Delete these lines:

```python
        message_snippet = None
        if message:
            max_msg_length = 500
            message_snippet = (
                f"{message.content[:max_msg_length]}"
                f"{'...' if len(message.content) > max_msg_length else ''}"
            )

        extra_embed_fields: list[EmbedFieldDict] = [
            {
                "name": "Message",
                "value": message_snippet if message else None,
                "inline": False,
            },
        ]
```

Replace with:

```python
        extra_embed_fields: list[EmbedFieldDict] = [
            {
                "name": "Message",
                "value": summarize_message(message) if message else None,
                "inline": False,
            },
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_bot.py -k log_moderation_action_with_message -v`
Expected: PASS.

- [ ] **Step 5: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py tests/test_bot.py
git commit -m "feat(moderation): summarize triggering message in ban embed"
```

---

### Task 4: Make ban handling thread-aware

**Files:**

- Modify: `lib/bot.py` (`ban_spammer` channel guard + annotation,
  `log_moderation_action` signature)
- Modify: `lib/bot_log_context.py` (`LogContext.channel` type)
- Test: `tests/test_bot.py` (update not-text-channel test, add thread test)

**Interfaces:**

- Produces: `ban_spammer` accepts messages whose channel is a
  `discord.TextChannel` or `discord.Thread`.

- [ ] **Step 1: Update / add the failing tests**

In `tests/test_bot.py`, update `test_ban_spammer_not_text_channel`'s
assertion string to the new wording:

```python
        assert caplog.records[0].message == (
            "Message channel is not a TextChannel or Thread, "
            "skipping `ban_spammer`"
        )
```

Then add a new test directly after it that a thread channel IS processed:

```python
    @async_test
    async def test_ban_spammer_thread_channel(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """A message posted in a thread is still processed for banning."""
        thread = mocker.MagicMock(spec=discord.Thread)
        thread.id = 555
        thread.name = "spam-thread"
        thread.mention = "<#555>"
        mock_message.channel = thread
        mock_message.author = mock_user

        mocker.patch(
            "lib.bot.DiscordBot._has_privileged_role", return_value=False
        )
        mocked_ban = mocker.patch.object(
            mock_user, "ban", new_callable=AsyncMock
        )
        mocked_log = mocker.patch(
            "lib.bot.DiscordBot.log_moderation_action"
        )

        await discord_bot.ban_spammer("Test ban reason", mock_message)

        mocked_ban.assert_called_once()
        mocked_log.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_bot.py -k "not_text_channel or thread_channel" -v
```

Expected: FAIL — `test_ban_spammer_thread_channel` skips (channel not a
`TextChannel`), and `not_text_channel` fails on the new assertion string.

- [ ] **Step 3: Widen the channel guard and annotations**

In `lib/bot.py` `ban_spammer`, replace the TODO + guard:

```python
        if not isinstance(
            message.channel, discord.TextChannel | discord.Thread
        ):
            logger.warning(
                "Message channel is not a TextChannel or Thread, "
                "skipping `ban_spammer`"
            )
            return

        user: discord.Member = message.author
        channel: discord.TextChannel | discord.Thread = message.channel
```

In `log_moderation_action`'s signature, widen the `channel` parameter:

```python
        channel: discord.TextChannel | discord.Thread | None = None,
```

- [ ] **Step 4: Widen LogContext.channel**

In `lib/bot_log_context.py`, widen the field type:

```python
    channel: discord.TextChannel | discord.Thread | None = None
```

- [ ] **Step 5: Run tests + type check to verify pass**

Run: `uv run pytest tests/test_bot.py -k ban_spammer -v && uv run pyrefly check`
Expected: PASS and no type errors. (`_send_log_embed` uses only
`channel.mention` and `channel.id`, both present on `Thread`.)

- [ ] **Step 6: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py lib/bot_log_context.py tests/test_bot.py
git commit -m "feat(moderation): ban spammers posting in threads"
```

---

### Task 5: Capture full payload on every ban + trim on_message

**Files:**

- Modify: `lib/bot.py` (`ban_spammer` verbose dump, drop #general-chat TODO,
  `on_message` breadcrumb)
- Test: `tests/test_bot.py` (ban_spammer log-count tests, on_message test)

**Interfaces:**

- Consumes: `describe_message_full` from Task 2 (imported in Task 3).

- [ ] **Step 1: Update the failing tests (ban_spammer log counts)**

The verbose dump adds one leading `WARNING` record to every ban_spammer path
that reaches processing. Update these four tests in `tests/test_bot.py`:

`test_ban_spammer_privileged_role`: change count to 3 and insert a leading
assertion; shift the existing records to indices 1 and 2:

```python
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "WARNING"
        assert caplog.records[0].message.startswith("Full message payload:")
        assert caplog.records[1].levelname == "INFO"
        assert (
            caplog.records[1].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "INFO"
        assert (
            caplog.records[2].message
            == f"User {mock_user.display_name} ({mock_user}) has privileged "
            f"role, not banning"
        )
```

`test_ban_spammer_success`: change count to 4, insert leading payload
assertion at index 0, and shift the three existing assertions to indices
1, 2, 3 (same messages, `+1` index each).

`test_ban_spammer_forbidden` and `test_ban_spammer_http_exception`: change
count to 4, insert the leading payload assertion at index 0, and shift the
three existing assertions to indices 1, 2, 3.

For all four, the inserted assertion is:

```python
        assert caplog.records[0].levelname == "WARNING"
        assert caplog.records[0].message.startswith("Full message payload:")
```

- [ ] **Step 2: Update the on_message mousetrap test**

Replace the body assertions of `test_on_message_mousetrap` (the collapsed
breadcrumb yields exactly one record):

```python
        mocked_ban_spammer.assert_called_once()
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"
        assert (
            record.message
            == f"Message received in #mousetrap from {mock_user.display_name} "
            f"({mock_user}), processing for ban"
        )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_bot.py -k "ban_spammer or on_message_mousetrap" -v
```

Expected: FAIL — record counts still at the old values; no
"Full message payload:" line; old mousetrap wording.

- [ ] **Step 4: Add the verbose dump in ban_spammer**

In `lib/bot.py` `ban_spammer`, immediately after the
`channel: ... = message.channel` line and before the
`logger.info("Processing potential spam ...")` call, add:

```python
        logger.warning(
            "Full message payload:\n%s", describe_message_full(message)
        )
```

- [ ] **Step 5: Drop the #general-chat TODO**

In `ban_spammer`, remove the line:

```python
            # TODO @cyberops7: also log to #general-chat
```

(Leave the `log_moderation_action(...)` call that follows it unchanged.)

- [ ] **Step 6: Collapse the on_message mousetrap logging**

In `lib/bot.py` `on_message`, replace the two log lines (the
`"Received message from ..."` warning and the `"Message object: %s"` warning)
with a single breadcrumb:

```python
        if message.channel.id == config.CHANNELS.MOUSETRAP:
            logger.warning(
                "Message received in #mousetrap from %s (%s), "
                "processing for ban",
                message.author.display_name,
                message.author,
            )
            ban_reason = "Message detected in #mousetrap."
            await self.ban_spammer(ban_reason, message)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_bot.py -k "ban_spammer or on_message" -v`
Expected: PASS.

- [ ] **Step 8: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py tests/test_bot.py
git commit -m "feat(moderation): log full spam payload on every ban"
```

---

### Task 6: Fail-fast startup for cog load and command sync

**Files:**

- Modify: `lib/bot.py` (`on_ready` cog-load + tree-sync wrapping)
- Test: `tests/test_bot.py` (two new tests)

**Interfaces:**

- Produces: `on_ready` re-raises after logging if `_load_cogs()` or
  `self.tree.sync()` fails.

- [ ] **Step 1: Write the failing tests**

Add two tests to `tests/test_bot.py` near the other `on_ready` tests:

```python
    @async_test
    async def test_on_ready_cog_load_failure_raises(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """on_ready re-raises and logs if cog loading fails."""
        mocker.patch.object(
            discord_bot, "_get_log_channel", return_value=mock_config.LOG_CHANNEL
        )
        mocker.patch("lib.bot.DiscordBot.log_bot_event")
        mocker.patch.object(
            discord_bot, "_load_cogs", side_effect=RuntimeError("boom")
        )

        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            await discord_bot.on_ready()

        assert any(
            "Failed to load cogs" in record.message
            for record in caplog.records
        )

    @async_test
    async def test_on_ready_sync_failure_raises(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """on_ready re-raises and logs if command sync fails."""
        mocker.patch.object(
            discord_bot, "_get_log_channel", return_value=mock_config.LOG_CHANNEL
        )
        mocker.patch("lib.bot.DiscordBot.log_bot_event")
        mocker.patch.object(discord_bot, "_load_cogs")
        mocker.patch.object(
            discord_bot.tree, "sync", side_effect=RuntimeError("sync boom")
        )

        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            await discord_bot.on_ready()

        assert any(
            "Failed to sync commands" in record.message
            for record in caplog.records
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_bot.py -k "cog_load_failure or sync_failure" -v`
Expected: FAIL — the exception propagates without the expected log message
(no `try/except` yet), so the `any(...)` assertion fails.

- [ ] **Step 3: Wrap the two startup calls**

In `lib/bot.py` `on_ready`, replace the two TODO comments and their calls.
For cog loading:

```python
        # Dynamically load all cogs
        try:
            await self._load_cogs()
        except Exception:
            logger.exception("Failed to load cogs during startup")
            raise
```

For command sync:

```python
        # Sync commands
        logger.info("Syncing commands...")
        try:
            synced_commands = await self.tree.sync()
        except Exception:
            logger.exception("Failed to sync commands during startup")
            raise
        logger.info(
            "Synced %d commands: %s",
            len(synced_commands),
            ",".join(command.name for command in synced_commands),
        )
```

If ruff flags `BLE001` (blind-except) on either block, append
`# noqa: BLE001` to the `except Exception:` line — the re-raise makes the
broad catch safe (it logs context, then propagates).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_bot.py -k "on_ready" -v`
Expected: PASS. The existing happy-path `on_ready` tests are unaffected
(no new log lines on success).

- [ ] **Step 5: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py tests/test_bot.py
git commit -m "feat(bot): fail fast when cog load or command sync errors"
```

---

### Task 7: Refactor tasks.py bootstrap + fix init fragility

**Files:**

- Modify: `lib/cogs/tasks.py` (`__init__` → `_bootstrap_tasks`, unconditional
  attribute init)
- Test: `tests/cogs/test_tasks.py` (add cog_unload-safety test)

**Interfaces:**

- Produces: `Tasks.__init__` always sets `self.youtube_feeds` and
  `self.github_monitor`, so `cog_unload` never raises `AttributeError`.

- [ ] **Step 1: Write the failing test**

In `tests/cogs/test_tasks.py`, add a test that `cog_unload` is safe even when
the loop guards short-circuited (attributes were never set in the old code).
Model it on the existing task tests in that file for fixture/mocking style;
the key assertions:

```python
    @async_test
    async def test_cog_unload_safe_without_bootstrap(
        self,
        mocker: MockerFixture,
        mock_config: MagicMock,
    ) -> None:
        """cog_unload does not AttributeError when tasks were preempted."""
        # Force every is_running() guard True so the bootstrap branches that
        # used to set youtube_feeds / github_monitor are skipped.
        mocker.patch.object(
            Tasks.clean_channel_members_task, "is_running", return_value=True
        )
        mocker.patch.object(
            Tasks.monitor_youtube_videos, "is_running", return_value=True
        )
        mocker.patch.object(
            Tasks.monitor_github_activity, "is_running", return_value=True
        )
        for task_name in (
            "clean_channel_members_task",
            "clean_channel_members_task_dry_run",
            "monitor_youtube_videos",
            "monitor_github_activity",
        ):
            mocker.patch.object(getattr(Tasks, task_name), "cancel")

        bot = mocker.MagicMock()
        cog = Tasks(bot)

        # Must not raise AttributeError on github_monitor / youtube_feeds.
        await cog.cog_unload()

        assert cog.github_monitor is None
        assert cog.youtube_feeds == {}
```

Ensure `Tasks` and `async_test`/`MockerFixture` are imported at the top of the
file (follow the existing imports there).

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/cogs/test_tasks.py -k cog_unload_safe -v`
Expected: FAIL — `AttributeError: 'Tasks' object has no attribute
'github_monitor'` (only set inside the skipped `if not is_running()`
branch).

- [ ] **Step 3: Refactor __init__ and init attributes unconditionally**

In `lib/cogs/tasks.py`, replace the body of `__init__` (the TODO comment
through the GitHub bootstrap block) with a call to a new helper, and set the
stateful attributes unconditionally:

```python
    def __init__(self, bot: DiscordBot) -> None:
        self.bot = bot
        # Initialize task state unconditionally so cog_unload is always safe,
        # even if a task was already running when the cog re-initialized.
        self.youtube_feeds: dict[str, youtube.YoutubeFeedParser] = {}
        self.github_monitor: github.GitHubMonitor | None = None
        self._bootstrap_tasks()

    def _bootstrap_tasks(self) -> None:
        """Start each background task if it is not already running."""
        # Bootstrap task: Clean Channel Members
        if config.DRY_RUN:
            if not self.clean_channel_members_task_dry_run.is_running():
                self.clean_channel_members_task_dry_run.start()
            else:
                logger.warning(
                    "clean_channel_members_task_dry_run task is already running"
                )
        elif not self.clean_channel_members_task.is_running():
            self.clean_channel_members_task.start()
        else:
            logger.warning("clean_channel_members_task task is already running")

        # Bootstrap task: YouTube Video Monitor
        if not self.monitor_youtube_videos.is_running():
            self.monitor_youtube_videos.start()
        else:
            logger.warning("monitor_youtube_videos task is already running")

        # Bootstrap task: GitHub Activity Monitor
        if not self.monitor_github_activity.is_running():
            self.monitor_github_activity.start()
        else:
            logger.warning("monitor_github_activity task is already running")
```

Note the `self.youtube_feeds = {}` and `self.github_monitor = None`
assignments that previously lived inside the `if not is_running()` branches
are removed from `_bootstrap_tasks` (they now live unconditionally in
`__init__`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/cogs/test_tasks.py -v`
Expected: PASS (new test plus all existing task tests).

- [ ] **Step 5: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/cogs/tasks.py tests/cogs/test_tasks.py
git commit -m "refactor(tasks): extract bootstrap, harden cog_unload"
```

---

### Task 8: Version bump, full verification, and closeout

**Files:**

- Modify: `pyproject.toml`
- Modify: `kubernetes/discordbot.yaml`
- Modify: `docs/TODO.md`, `CLAUDE.md`
- Update: KB vault (`~/code/kb`)

- [ ] **Step 1: Bump the version and image tag**

In `pyproject.toml`, set `version = "0.13.0"`. In
`kubernetes/discordbot.yaml`, set the image to
`ghcr.io/cyberops7/discord_bot:v0.13.0`.

- [ ] **Step 2: Run the full check + test suite**

Run: `uv run invoke check && uv run invoke test`
Expected: all checks pass; pytest reports 100% coverage (including branch
coverage). If coverage dips, add the missing case to the relevant test file
before proceeding.

- [ ] **Step 3: Commit the version bump**

```bash
git add pyproject.toml kubernetes/discordbot.yaml
git commit -m "chore: bump version to 0.13.0"
```

- [ ] **Step 4: Record learnings**

- `docs/TODO.md`: the six inline TODOs were code comments, not checklist
  entries — nothing to check off. If any follow-up surfaced during
  implementation, add it under the relevant section.
- `CLAUDE.md`: add a short note under the testing/config guidance that a
  module reading `config` at call time must be added to the `mock_config`
  patch list in `tests/conftest.py`, and that widening a channel type to
  include `discord.Thread` also requires widening `LogContext.channel` and
  `log_moderation_action`'s `channel` parameter.
- KB (`~/code/kb`): update the `Jim's Garage Discord Bot` project note — close
  the `github_monitor`/`youtube_feeds` init-fragility open thread, and record
  the two-tier message-capture improvement (concise embed vs. full log dump)
  and the 2026-07-12 investigation that motivated it. Update today's daily
  note per the `/kb-update` conventions.

- [ ] **Step 5: Commit doc/closeout changes**

```bash
git add docs/TODO.md CLAUDE.md
git commit -m "docs: record inline-cleanup learnings and conventions"
```

---

## Self-Review

**Spec coverage:**

- Config routing (API_HOST, PORT_MIN/MAX) → Task 1. ✅
- Fail-fast startup exceptions → Task 6. ✅
- Thread-aware ban handling → Task 4. ✅
- Drop #general-chat TODO → Task 5, Step 5. ✅
- tasks.py refactor + fragility fix → Task 7. ✅
- `summarize_message` (embed) → Tasks 2, 3. ✅
- `describe_message_full` (log, every ban path, 4000 cap) → Tasks 2, 5. ✅
- on_message breadcrumb collapse → Task 5, Step 6. ✅
- Version bump + closeout (TODO/CLAUDE/KB) → Task 8. ✅

**Type consistency:** `summarize_message(message, max_length=None)` and
`describe_message_full(message, max_content=4000)` are used with the same
names/signatures in Tasks 3 and 5. Channel type
`discord.TextChannel | discord.Thread` is applied consistently in
`ban_spammer`, `log_moderation_action`, and `LogContext.channel` (Task 4).

**Placeholder scan:** No TBD/TODO-in-plan; every code step shows full code;
every test step shows the assertion and the expected run result.
