# Inline TODO Cleanup + Robust Spam-Message Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the six `TODO @cyberops7` markers in application code, add
full-fidelity capture of banned spam messages, and make startup validation
actually fail-fast — with no behavior regressions.

**Architecture:** Deployment-tunable `API_HOST` moves into `conf/config.yaml`
behind the `config` singleton. A new pure module `lib/message_format.py`
renders a `discord.Message` two ways: a concise safe summary for the bot-logs
embed and a full single-line dump for the on-disk/Loki log. Cog loading and
command sync move from the swallowed `on_ready` handler into `setup_hook`,
wired through the FastAPI lifespan to terminate the process on fatal startup
errors. Ban handling becomes thread-aware.

**Tech Stack:** Python 3.13, discord.py, FastAPI/uvicorn, pytest +
pytest-mock + pytest-asyncio, uv, ruff (`select = ["ALL"]`), pyrefly.

## Global Constraints

- 100% branch coverage required; every task ends green under
  `uv run invoke test`.
- Every commit must pass `uv run invoke check` (ruff, bandit, pyrefly,
  hadolint, markdownlint, yamllint, shellcheck) — no commit may leave a
  blocking check red.
- Deployment-tunable values live in `conf/config.yaml` via the `config`
  singleton; protocol invariants stay module constants.
- Use `logger`, never `print()`.
- Version bump: `pyproject.toml` `0.12.1` → `0.13.0`, and the image tag in
  `kubernetes/discordbot.yaml` `v0.12.1` → `v0.13.0`.
- Run `uv run ruff format` before every commit.
- Any module that reads `config` at call time must be added to the
  `mock_config` patch list in `tests/conftest.py`, or its tests hit the real
  singleton.

---

### Task 1: Route API_HOST through config; keep port bounds constant

**Files:**

- Modify: `conf/config.yaml`
- Modify: `main.py:32-38`
- Modify: `lib/utils.py:5-7`
- Modify: `tests/conftest.py` (mock_config value)
- Test: `tests/test_main.py`

**Interfaces:**

- Produces: `config.API_HOST: str` on the config singleton. Port bounds stay
  as `lib.utils.PORT_MIN` / `lib.utils.PORT_MAX` module constants.

- [ ] **Step 1: Add the config key**

In `conf/config.yaml`, add `API_HOST` directly above the existing
`API_PORT: 8080`:

```yaml
API_HOST: "0.0.0.0"
```

- [ ] **Step 2: Add API_HOST to the mock config fixture**

In `tests/conftest.py`, inside `mock_config`, after
`mock_cfg.EMBED_MAX_LENGTH = 1024` add:

```python
    mock_cfg.API_HOST = "0.0.0.0"  # noqa: S104
```

(No `lib.utils.config` patch is needed — `utils.py` keeps module constants and
does not import `config`.)

- [ ] **Step 3: Update the tests with a distinct host value**

In `tests/test_main.py`, the tests must prove the host now comes from config,
not a hardcoded literal. In `test_main_successful_run`, after
`mock_config_instance.API_PORT = 8000` add a **distinct** host:

```python
    mock_config_instance.API_HOST = "127.0.0.1"
```

and change that test's `uvicorn.run` assertion from `host="0.0.0.0"` to:

```python
        host="127.0.0.1",
```

Apply the same two edits (`API_HOST = "127.0.0.1"` on the config instance, and
`host="127.0.0.1"` in the assertion) to `test_default_port`,
`test_main_dry_run_mode`, and `test_main_dry_run_disabled`. Do NOT touch
`test_invalid_port` (it raises before uvicorn is called).

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `uvicorn.run` is still called with `host="0.0.0.0"` (the
hardcoded literal), not `"127.0.0.1"`.

- [ ] **Step 5: Point main.py at config.API_HOST**

In `main.py`, replace the TODO comment and the hardcoded host. Note the
`# noqa: S104` is **removed** (no `0.0.0.0` literal remains in the code, so the
directive would trip `RUF100`):

```python
    # Start the FastAPI app using Uvicorn. This also starts the bot.
    logger.info("Starting FastAPI server...")
    uvicorn.run(
        app,
        host=config.API_HOST,  # Bind address; defaults to 0.0.0.0 in config
        port=api_port,
        log_config=None,
    )
```

`main()` already builds `config = Config()` locally; use that variable. No new
import needed.

- [ ] **Step 6: Drop the port-bounds TODO in utils.py**

In `lib/utils.py`, remove the TODO comment and add a clarifying one; the
constants stay:

```python
# Protocol invariants (not deployment config): valid TCP port range.
PORT_MIN = 0
PORT_MAX = 65535
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_main.py tests/test_utils.py -v`
Expected: PASS. `test_utils` is unchanged (constants unchanged).

- [ ] **Step 8: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add conf/config.yaml lib/utils.py main.py tests/conftest.py \
  tests/test_main.py
git commit -m "feat(config): route API_HOST through config"
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
     -> str` — full single-line dump: id/type/flags/jump_url, capped content,
     and every attachment (filename, content_type, size, url), embed
     (`to_dict()`), sticker (name, id), poll, and forwarded snapshot.

- [ ] **Step 1: Extend conftest for the new module and payload attributes**

In `tests/conftest.py`, add to the `with (...)` patch block:

```python
        patch("lib.message_format.config", mock_cfg),
```

And in the `mock_message` fixture, after `message.content = "test message"`,
add empty/None payload attributes so the formatters see no
attachments/embeds/stickers/poll/snapshots by default (a `spec=Message` mock
otherwise returns truthy `MagicMock`s for `poll`/`message_snapshots`):

```python
    message.attachments = []
    message.embeds = []
    message.stickers = []
    message.poll = None
    message.message_snapshots = []
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
    poll: MagicMock | None = None,
    snapshots: list[MagicMock] | None = None,
) -> MagicMock:
    """Build a mock discord.Message with the given payloads."""
    message = MagicMock(spec=discord.Message)
    message.content = content
    message.attachments = attachments or []
    message.embeds = embeds or []
    message.stickers = stickers or []
    message.poll = poll
    message.message_snapshots = snapshots or []
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
    assert summarize_message(_make_message(content="hello world")) == (
        "hello world"
    )


def test_summarize_attachment_only_no_url() -> None:
    result = summarize_message(
        _make_message(attachments=[_attachment("pic.png")])
    )
    assert result == "[1 attachment(s): pic.png]"
    assert "https://" not in result


def test_summarize_sticker_only() -> None:
    assert summarize_message(
        _make_message(stickers=[_sticker("wave")])
    ) == "[sticker: wave]"


def test_summarize_embed_only() -> None:
    assert summarize_message(
        _make_message(embeds=[_embed("spam")])
    ) == "[1 embed(s)]"


def test_summarize_poll_marker() -> None:
    poll = MagicMock()
    assert summarize_message(_make_message(poll=poll)) == "[poll]"


def test_summarize_forwarded_marker() -> None:
    assert summarize_message(
        _make_message(snapshots=[MagicMock()])
    ) == "[1 forwarded message(s)]"


def test_summarize_combined() -> None:
    result = summarize_message(
        _make_message(content="look", attachments=[_attachment("a.jpg")])
    )
    assert result == "look\n[1 attachment(s): a.jpg]"


def test_summarize_empty() -> None:
    assert summarize_message(_make_message()) == "[no displayable content]"


def test_summarize_truncates_to_max_length() -> None:
    result = summarize_message(_make_message(content="x" * 100), max_length=10)
    assert len(result) == 10
    assert result.endswith("...")


def test_describe_full_is_single_line_with_all_payloads() -> None:
    poll = MagicMock()
    poll.question = "vote?"
    result = describe_message_full(
        _make_message(
            content="payload",
            attachments=[_attachment("evil.exe")],
            embeds=[_embed("phish")],
            stickers=[_sticker("boom")],
            poll=poll,
            snapshots=[MagicMock()],
        )
    )
    assert "\n" not in result
    assert "content='payload'" in result
    assert "filename='evil.exe'" in result
    assert "https://cdn.example/evil.exe" in result
    assert "size=1234" in result
    assert "{'title': 'phish'}" in result
    assert "name='boom'" in result
    assert "id=123" in result
    assert "poll='vote?'" in result
    assert "forwarded=1" in result


def test_describe_full_content_repr_escapes_newlines() -> None:
    result = describe_message_full(_make_message(content="a\nb"))
    assert "\n" not in result
    assert "'a\\nb'" in result


def test_describe_full_caps_content() -> None:
    result = describe_message_full(
        _make_message(content="y" * 5000), max_content=100
    )
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

import discord

from lib.config import config


def summarize_message(
    message: discord.Message, max_length: int | None = None
) -> str:
    """
    Build a concise, safe one-field summary of a message for a log embed.

    Always returns a non-empty string so the embed field is never suppressed.
    Attachment URLs are intentionally omitted.
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

    if getattr(message, "poll", None) is not None:
        parts.append("[poll]")

    snapshots = getattr(message, "message_snapshots", None) or []
    if snapshots:
        parts.append(f"[{len(snapshots)} forwarded message(s)]")

    summary = "\n".join(parts) if parts else "[no displayable content]"

    if len(summary) > limit:
        summary = f"{summary[: limit - 3]}..."
    return summary


def describe_message_full(
    message: discord.Message, max_content: int = 4000
) -> str:
    """
    Build a full-fidelity, single-line description of a message for the log
    file. `content` and payload fields are repr-escaped so attacker-controlled
    newlines cannot fragment the log line (kept single-line for Loki).
    """
    content = message.content
    if len(content) > max_content:
        content = (
            f"{content[:max_content]}... (truncated {len(content)} chars)"
        )

    parts: list[str] = [
        f"id={message.id}",
        f"type={message.type!r}",
        f"flags={message.flags!r}",
        f"jump_url={message.jump_url}",
        f"content={content!r}",
    ]

    for i, attachment in enumerate(message.attachments):
        parts.append(
            f"attachment[{i}]=(filename={attachment.filename!r}, "
            f"content_type={attachment.content_type!r}, "
            f"size={attachment.size}, url={attachment.url})"
        )

    for i, embed in enumerate(message.embeds):
        parts.append(f"embed[{i}]={embed.to_dict()}")

    for i, sticker in enumerate(message.stickers):
        parts.append(f"sticker[{i}]=(name={sticker.name!r}, id={sticker.id})")

    poll = getattr(message, "poll", None)
    if poll is not None:
        parts.append(f"poll={getattr(poll, 'question', poll)!r}")

    snapshots = getattr(message, "message_snapshots", None) or []
    if snapshots:
        parts.append(f"forwarded={len(snapshots)}")

    return " | ".join(parts)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_message_format.py -v`
Expected: PASS (all 13 tests).

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

- Modify: `lib/bot.py` (import, `log_moderation_action`, and the pre-existing
  `_send_log_embed` debug-log bug)
- Test: `tests/test_bot.py`
  (`test_log_moderation_action_with_message`)

**Interfaces:**

- Consumes: `summarize_message` from Task 2.

- [ ] **Step 1: Update the failing test**

In `tests/test_bot.py`, rewrite the long-message section of
`test_log_moderation_action_with_message` — the summarizer truncates to
`EMBED_MAX_LENGTH` (1024), so a 600-char message is not truncated. Replace the
block from `# Test with a long message ...` to the end of the method with:

```python
        # Reset mock for the next test
        mock_log_to_channel.reset_mock()

        # A 600-char message is under EMBED_MAX_LENGTH (1024): summarized in
        # full, no ellipsis.
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
Expected: FAIL — value still truncated to 503 chars with `...`.

- [ ] **Step 3: Wire in the summarizer and fix the debug-log bug**

In `lib/bot.py`, add the import near the other `from lib.*` imports (import
only `summarize_message` here; `describe_message_full` is added in Task 5 where
it is first used, to avoid an `F401` unused-import failure):

```python
from lib.message_format import summarize_message
```

In `log_moderation_action`, delete the `message_snippet` block and the
`max_msg_length` logic, and set the field value from the summarizer:

```python
        extra_embed_fields: list[EmbedFieldDict] = [
            {
                "name": "Message",
                "value": summarize_message(message) if message else None,
                "inline": False,
            },
        ]
```

In `_send_log_embed`, fix the pre-existing debug log that passes the imported
`field` function instead of the loop variable:

```python
        for embed_field in context.extra_embed_fields:
            logger.debug("Parsing extra embed field: %s", embed_field)
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

- Modify: `lib/bot.py` (`on_message` gate, `ban_spammer` guard + annotation,
  `log_moderation_action` signature)
- Modify: `lib/bot_log_context.py` (`LogContext.channel` type)
- Test: `tests/test_bot.py`

**Interfaces:**

- Produces: messages in a thread under `#mousetrap` reach `ban_spammer`, which
  accepts a `discord.TextChannel | discord.Thread`.

- [ ] **Step 1: Update / add the failing tests**

In `tests/test_bot.py`, update `test_ban_spammer_not_text_channel`'s assertion
string:

```python
        assert caplog.records[0].message == (
            "Message channel is not a TextChannel or Thread, "
            "skipping `ban_spammer`"
        )
```

Add a test that a thread channel IS processed by `ban_spammer`:

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
        mocked_log = mocker.patch("lib.bot.DiscordBot.log_moderation_action")

        await discord_bot.ban_spammer("Test ban reason", mock_message)

        mocked_ban.assert_called_once()
        mocked_log.assert_called_once()
```

Add a test that a thread under #mousetrap routes through `on_message` to
`ban_spammer`:

```python
    @async_test
    async def test_on_message_mousetrap_thread(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """A message in a thread under #mousetrap triggers ban handling."""
        thread = mocker.MagicMock(spec=discord.Thread)
        thread.id = 777  # not the mousetrap id
        thread.parent_id = mock_config.CHANNELS.MOUSETRAP
        mock_message.channel = thread
        mocked_ban_spammer = mocker.patch(
            "lib.bot.DiscordBot.ban_spammer", AsyncMock(return_value=None)
        )
        mocker.patch("lib.bot.DiscordBot.process_commands")

        await discord_bot.on_message(mock_message)

        mocked_ban_spammer.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_bot.py -k "thread or not_text_channel" -v`
Expected: FAIL — thread messages are skipped and the `not_text_channel`
wording assertion is new.

- [ ] **Step 3: Widen the on_message gate**

In `lib/bot.py` `on_message`, replace the mousetrap gate so it matches the
channel itself or a thread whose parent is #mousetrap:

```python
        # Ban spammers - no one should post in #mousetrap or its threads.
        channel = message.channel
        in_mousetrap = channel.id == config.CHANNELS.MOUSETRAP or (
            isinstance(channel, discord.Thread)
            and channel.parent_id == config.CHANNELS.MOUSETRAP
        )
        if in_mousetrap:
            logger.warning(
                "Message received in #mousetrap from %s (%s), "
                "processing for ban",
                message.author.display_name,
                message.author,
            )
            ban_reason = "Message detected in #mousetrap."
            await self.ban_spammer(ban_reason, message)
```

(This also replaces the old two-line `Received message ... : content` +
`Message object: <repr>` logging with a single breadcrumb; the full payload is
captured in `ban_spammer` in Task 5.)

- [ ] **Step 4: Widen the channel guard and annotations**

In `ban_spammer`, replace the TODO + guard:

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

In `lib/bot_log_context.py`, widen the field:

```python
    channel: discord.TextChannel | discord.Thread | None = None
```

- [ ] **Step 5: Update the mousetrap breadcrumb test**

In `tests/test_bot.py`, replace the assertions in `test_on_message_mousetrap`
(the collapsed breadcrumb is one record):

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

- [ ] **Step 6: Run tests + type check**

Run:

```bash
uv run pytest tests/test_bot.py -k "thread or mousetrap or ban_spammer" -v
uv run pyrefly check
```

Expected: PASS and no type errors (`_send_log_embed`/`_send_log_text` use only
`channel.mention`/`.id`, both on `Thread`).

- [ ] **Step 7: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py lib/bot_log_context.py tests/test_bot.py
git commit -m "feat(moderation): ban spammers posting in mousetrap threads"
```

---

### Task 5: Capture full payload on every ban

**Files:**

- Modify: `lib/bot.py` (`ban_spammer` verbose dump, drop general-chat TODO)
- Test: `tests/test_bot.py` (ban_spammer log-count tests)

**Interfaces:**

- Consumes: `describe_message_full` from Task 2.

- [ ] **Step 1: Update the failing tests (ban_spammer log counts)**

The dump is logged at INFO at the top of `ban_spammer`, before the guards, so
it adds one leading INFO record to **every** ban_spammer path. In
`tests/test_bot.py`, insert this leading assertion (index 0) into each of the
tests below and bump each record count by 1:

```python
        assert caplog.records[0].levelname == "INFO"
        assert caplog.records[0].message.startswith("Spam ban payload")
```

- `test_ban_spammer_not_member_instance`: count `1` → `2`; the existing
  "author is not a Member" assertion shifts to `caplog.records[1]`.
- `test_ban_spammer_not_text_channel`: count `1` → `2`; the "not a
  TextChannel or Thread" assertion shifts to `caplog.records[1]`.
- `test_ban_spammer_privileged_role`: count `2` → `3`; existing records shift
  to indices `1` and `2`.
- `test_ban_spammer_success`: count `3` → `4`; existing records shift to
  indices `1`, `2`, `3`.
- `test_ban_spammer_forbidden`: count `3` → `4`; existing records shift to
  indices `1`, `2`, `3`.
- `test_ban_spammer_http_exception`: count `3` → `4`; existing records shift
  to indices `1`, `2`, `3`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_bot.py -k ban_spammer -v`
Expected: FAIL — no "Spam ban payload" record; counts one short.

- [ ] **Step 3: Add the verbose dump and the import**

In `lib/bot.py`, extend the message-format import from Task 3:

```python
from lib.message_format import describe_message_full, summarize_message
```

At the very top of `ban_spammer` (before the `isinstance(message.author, ...)`
guard), add:

```python
        logger.info(
            "Spam ban payload | %s", describe_message_full(message)
        )
```

- [ ] **Step 4: Drop the general-chat TODO**

In `ban_spammer`, remove the line:

```python
            # TODO @cyberops7: also log to #general-chat
```

(Leave the `log_moderation_action(...)` call unchanged.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_bot.py -k ban_spammer -v`
Expected: PASS.

- [ ] **Step 6: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py tests/test_bot.py
git commit -m "feat(moderation): log full spam payload on every ban"
```

---

### Task 6: Move startup validation into setup_hook

**Files:**

- Modify: `lib/bot.py` (`setup_hook` new, `on_ready` trimmed)
- Test: `tests/test_bot.py`

**Interfaces:**

- Produces: `DiscordBot.setup_hook()` loads cogs (fail-hard) and syncs commands
  (tolerating `discord.HTTPException`). `on_ready` no longer loads cogs or
  syncs.

- [ ] **Step 1: Write the failing setup_hook tests**

Add to `tests/test_bot.py`:

```python
    @async_test
    async def test_setup_hook_loads_cogs_and_syncs(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """setup_hook loads cogs and syncs commands."""
        mock_load = mocker.patch.object(discord_bot, "_load_cogs")
        mock_sync = mocker.patch.object(
            discord_bot.tree, "sync", return_value=[]
        )

        with caplog.at_level(logging.INFO):
            await discord_bot.setup_hook()

        mock_load.assert_called_once()
        mock_sync.assert_called_once()
        assert any("Synced 0 commands" in r.message for r in caplog.records)

    @async_test
    async def test_setup_hook_cog_failure_raises(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """setup_hook re-raises (crashes startup) when cog loading fails."""
        mocker.patch.object(
            discord_bot, "_load_cogs", side_effect=RuntimeError("boom")
        )
        mocker.patch.object(discord_bot.tree, "sync")

        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            await discord_bot.setup_hook()

        assert any(
            "Failed to load cogs" in r.message for r in caplog.records
        )

    @async_test
    async def test_setup_hook_sync_http_error_tolerated(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """A transient command-sync HTTP error is logged, not raised."""
        mocker.patch.object(discord_bot, "_load_cogs")
        mocker.patch.object(
            discord_bot.tree,
            "sync",
            side_effect=discord.HTTPException(MagicMock(), "429"),
        )

        with caplog.at_level(logging.INFO):
            await discord_bot.setup_hook()  # must NOT raise

        assert any(
            "Command sync failed" in r.message for r in caplog.records
        )
```

- [ ] **Step 2: Update the existing on_ready tests**

`on_ready` no longer loads cogs or syncs, so those logs/calls move out.

In `test_on_ready`: remove the `_load_cogs` and `tree.sync` mocks and their
`assert_called_once()` calls, and the "Syncing commands", "Synced 0 commands",
and "Registered commands" record assertions. The remaining records are exactly
three:

```python
        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        assert len(caplog.records) == 3
        assert "Bot is ready" in caplog.records[0].message
        assert "We have logged in as TestBot" in caplog.records[1].message
        assert (
            "Performing initial startup procedures..."
            in caplog.records[2].message
        )
        mock_log_bot_event.assert_called_once()
```

In `test_on_ready_no_default_channel`: remove the `_load_cogs`/`tree.sync`
mocks and their assertions; change the count from `7` to `4`; the
"Could not find log channel" WARNING is now `caplog.records[3]`.

`test_on_ready_no_user` and `test_on_ready_already_started` are unaffected
(they return before the cog/sync code either way; the latter's
`mock_load_cogs.assert_not_called()` / `mock_sync_commands.assert_not_called()`
remain true).

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_bot.py -k "setup_hook or on_ready" -v`
Expected: FAIL — `setup_hook` does not exist yet; `on_ready` still emits the
sync logs.

- [ ] **Step 4: Add setup_hook and trim on_ready**

In `lib/bot.py`, add a `setup_hook` method (place it just before `on_ready`):

```python
    async def setup_hook(self) -> None:
        """Load cogs and sync commands during login.

        Runs once per process before the gateway connection. Raising here
        propagates out of ``bot.start()`` (see lib/api.py), so a fatal startup
        error terminates the process instead of running half-initialized.
        """
        # Fail hard: a bot that cannot load its cogs is broken.
        try:
            await self._load_cogs()
        except Exception:
            logger.exception("Failed to load cogs during startup")
            raise

        # Command sync hits Discord's global rate limits; tolerate a transient
        # failure rather than crash-loop on a 429.
        logger.info("Syncing commands...")
        try:
            synced_commands = await self.tree.sync()
        except discord.HTTPException:
            logger.exception("Command sync failed; continuing without a sync")
            return
        logger.info(
            "Synced %d commands: %s",
            len(synced_commands),
            ",".join(command.name for command in synced_commands),
        )
        logger.info(
            "Registered commands: %s",
            ",".join(cmd.name for cmd in self.commands),
        )
```

Then in `on_ready`, delete the two `_load_cogs()`/`tree.sync()` blocks and the
sync/registered-command logging (everything from the old
`# Dynamically load all cogs` through the `Registered commands` log), leaving
the LOG_CHANNEL resolution and the "Bot Startup" `log_bot_event` in place. The
`if self._initial_startup_complete:` reconnect guard stays.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_bot.py -k "setup_hook or on_ready" -v`
Expected: PASS.

- [ ] **Step 6: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/bot.py tests/test_bot.py
git commit -m "refactor(bot): validate startup in setup_hook, not on_ready"
```

---

### Task 7: Terminate the process on fatal bot-task failure

**Files:**

- Modify: `lib/api.py` (lifespan done-callback)
- Test: `tests/test_api.py`

**Interfaces:**

- Consumes: `setup_hook` from Task 6 (its exception propagates out of
  `bot.start()`).
- Produces: `_handle_bot_task_result(task)` — a done-callback that raises
  `SIGTERM` when the bot task ended with an exception.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py` (import `signal` and `_handle_bot_task_result`):

```python
@async_test
async def test_handle_bot_task_result_signals_on_exception(
    mocker: MockerFixture,
) -> None:
    """A bot task that died with an exception raises SIGTERM."""
    mock_raise = mocker.patch("lib.api.signal.raise_signal")
    mock_logger = mocker.patch("lib.api.logger")

    async def _boom() -> None:
        msg = "bot died"
        raise RuntimeError(msg)

    task = asyncio.ensure_future(_boom())
    await asyncio.gather(task, return_exceptions=True)

    _handle_bot_task_result(task)

    mock_raise.assert_called_once_with(signal.SIGTERM)
    mock_logger.critical.assert_called_once()


@async_test
async def test_handle_bot_task_result_noop_on_success(
    mocker: MockerFixture,
) -> None:
    """A cleanly-finished bot task does not signal."""
    mock_raise = mocker.patch("lib.api.signal.raise_signal")

    async def _ok() -> None:
        return

    task = asyncio.ensure_future(_ok())
    await asyncio.gather(task, return_exceptions=True)

    _handle_bot_task_result(task)

    mock_raise.assert_not_called()


@async_test
async def test_handle_bot_task_result_noop_on_cancel(
    mocker: MockerFixture,
) -> None:
    """A cancelled bot task (normal shutdown) does not signal."""
    mock_raise = mocker.patch("lib.api.signal.raise_signal")

    async def _sleep() -> None:
        await asyncio.sleep(1)

    task = asyncio.ensure_future(_sleep())
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    _handle_bot_task_result(task)

    mock_raise.assert_not_called()
```

Also import `_handle_bot_task_result` in the existing
`from lib.api import (...)` block.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_api.py -k handle_bot_task_result -v`
Expected: FAIL — `ImportError`/`AttributeError`: `_handle_bot_task_result`
does not exist.

- [ ] **Step 3: Implement the callback and wire it in**

In `lib/api.py`, add `import signal` at the top (alphabetical, after
`import logging`). Add the callback at module level (below the imports, above
`lifespan`):

```python
def _handle_bot_task_result(task: "asyncio.Task[None]") -> None:
    """Crash the process if the bot task died, so k8s restarts the pod.

    The bot runs as a fire-and-forget task; without this its exception would
    sit unretrieved and the API would keep serving a dead bot.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    logger.critical(
        "Discord bot terminated unexpectedly; shutting down.", exc_info=exc
    )
    signal.raise_signal(signal.SIGTERM)
```

In `lifespan`, attach it right after creating `bot_task`:

```python
    bot_task = asyncio.create_task(bot.start(config.BOT_TOKEN, reconnect=True))
    bot_task.add_done_callback(_handle_bot_task_result)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS. The existing lifespan tests still pass — their mocked
`bot.start` finishes without exception, so the callback is a no-op.

- [ ] **Step 5: Format, check, commit**

```bash
uv run ruff format
uv run invoke check
git add lib/api.py tests/test_api.py
git commit -m "feat(api): terminate process when the bot task dies"
```

---

### Task 8: Refactor tasks.py bootstrap + fix init fragility

**Files:**

- Modify: `lib/cogs/tasks.py` (`__init__` → `_bootstrap_tasks`, unconditional
  attribute init)
- Test: `tests/cogs/test_tasks.py`

**Interfaces:**

- Produces: `Tasks.__init__` always sets `self.youtube_feeds` and
  `self.github_monitor`, so `cog_unload` never `AttributeError`s.

- [ ] **Step 1: Write the failing test**

In `tests/cogs/test_tasks.py`, add a test that `cog_unload` is safe even when
every task loop was already running (the branch where the old code never set
the attributes). Mirror the existing "already running" tests in this file for
construction style — construct the cog under
`patch("discord.ext.tasks.Loop.start")`, then force each loop's `is_running`
True at the **instance** level so
`_bootstrap_tasks` skips the start branches:

```python
    @async_test
    async def test_cog_unload_safe_when_tasks_preempted(
        self,
        mocker: MockerFixture,
        mock_config: MagicMock,
    ) -> None:
        """cog_unload does not AttributeError when loops were already running."""
        bot = mocker.MagicMock()
        with mocker.patch("discord.ext.tasks.Loop.start"):
            cog = Tasks(bot)

        # Force the guards so a re-bootstrap would skip the (old) attribute
        # assignments, and stub cancel/close for unload.
        for name in (
            "clean_channel_members_task",
            "clean_channel_members_task_dry_run",
            "monitor_youtube_videos",
            "monitor_github_activity",
        ):
            loop = mocker.patch.object(cog, name)
            loop.is_running.return_value = True

        await cog.cog_unload()

        assert cog.github_monitor is None
        assert cog.youtube_feeds == {}
```

Confirm `Tasks`, `async_test`, and `MockerFixture` are imported at the top of
the file (match the existing imports).

- [ ] **Step 2: Run the test to verify it passes against the new intent**

Run: `uv run pytest tests/cogs/test_tasks.py -k cog_unload_safe -v`
Expected: with the current code this test constructs the cog normally (loops
patched), so `github_monitor`/`youtube_feeds` happen to be set — it may PASS
already. The regression value is locking in the unconditional init; proceed to
the refactor and keep it green.

- [ ] **Step 3: Refactor __init__ and init attributes unconditionally**

In `lib/cogs/tasks.py`, replace the `__init__` body (the TODO through the
GitHub bootstrap block) with unconditional state init plus a helper call:

```python
    def __init__(self, bot: DiscordBot) -> None:
        self.bot = bot
        # Initialize task state unconditionally so cog_unload is always safe,
        # even if a loop was already running when the cog re-initialized.
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

The `self.youtube_feeds = {}` and `self.github_monitor = None` assignments that
previously lived inside the `if not is_running()` branches are removed from
`_bootstrap_tasks` (they now live unconditionally in `__init__`).

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

### Task 9: Version bump, full verification, and closeout

**Files:**

- Modify: `pyproject.toml`, `kubernetes/discordbot.yaml`
- Modify: `docs/TODO.md`, `CLAUDE.md`
- Update: KB vault (`~/code/kb`)

- [ ] **Step 1: Bump the version and image tag**

In `pyproject.toml`, set `version = "0.13.0"`. In
`kubernetes/discordbot.yaml`, set the image to
`ghcr.io/cyberops7/discord_bot:v0.13.0`.

- [ ] **Step 2: Run the full check + test suite**

Run: `uv run invoke check && uv run invoke test`
Expected: all checks pass; pytest reports 100% coverage (including branch
coverage). If coverage dips, add the missing case before proceeding.

- [ ] **Step 3: Commit the version bump**

```bash
git add pyproject.toml kubernetes/discordbot.yaml
git commit -m "chore: bump version to 0.13.0"
```

- [ ] **Step 4: Record learnings**

- `docs/TODO.md`: the six inline TODOs were code comments, not checklist
  entries. Add any follow-up discovered (e.g. generalizing thread handling to
  voice/forum channels, if desired).
- `CLAUDE.md`: add short notes that (a) exceptions raised in discord.py event
  handlers like `on_ready` are swallowed by the dispatcher — do startup
  validation in `setup_hook` and surface fatal failures through the FastAPI
  lifespan; (b) a module reading `config` at call time must be added to the
  `mock_config` patch list in `tests/conftest.py`; (c) widening a channel type
  to include `discord.Thread` also requires widening `LogContext.channel` and
  `log_moderation_action`'s `channel` parameter.
- KB (`~/code/kb`): update the `Jim's Garage Discord Bot` project note — close
  the `github_monitor`/`youtube_feeds` init-fragility thread; record the
  two-tier message-capture design, the `setup_hook`/lifespan fail-fast fix, and
  the 2026-07-12 investigation that motivated the capture work. Update today's
  daily note per the `/kb-update` conventions.

- [ ] **Step 5: Commit doc/closeout changes**

```bash
git add docs/TODO.md CLAUDE.md
git commit -m "docs: record inline-cleanup learnings and conventions"
```

---

## Self-Review

**Spec coverage:**

- Config: API_HOST → config, port bounds stay constants → Task 1.
- message_format (summarize + describe, single-line, poll/snapshots) →
  Task 2.
- Embed summary + pre-existing debug-log bug → Task 3.
- Thread-aware bans (on_message gate + guard + type widening) → Task 4.
- Full payload capture (top of ban_spammer, INFO, single-line) + drop
  general-chat TODO → Task 5.
- Fail-fast in setup_hook → Task 6; process-exit wiring → Task 7.
- tasks.py refactor + fragility fix → Task 8.
- Version bump + closeout → Task 9.

**Type consistency:** `summarize_message(message, max_length=None)` and
`describe_message_full(message, max_content=4000)` are used with matching
names/signatures in Tasks 3 and 5. `discord.TextChannel | discord.Thread` is
applied consistently in `on_message`, `ban_spammer`, `log_moderation_action`,
and `LogContext.channel` (Task 4). `_handle_bot_task_result` (Task 7) consumes
the propagating exception from `setup_hook` (Task 6).

**Placeholder scan:** No TBD/placeholder; every code step shows full code;
every test step shows the assertion and the expected run result. Import timing
is explicit (`summarize_message` in Task 3, `describe_message_full` added in
Task 5) to avoid an interim `F401`.
