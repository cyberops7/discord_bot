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
    assert summarize_message(_make_message(content="hello world")) == ("hello world")


def test_summarize_attachment_only_no_url() -> None:
    result = summarize_message(_make_message(attachments=[_attachment("pic.png")]))
    assert result == "[1 attachment(s): pic.png]"
    assert "https://" not in result


def test_summarize_sticker_only() -> None:
    assert (
        summarize_message(_make_message(stickers=[_sticker("wave")]))
        == "[sticker: wave]"
    )


def test_summarize_embed_only() -> None:
    assert summarize_message(_make_message(embeds=[_embed("spam")])) == "[1 embed(s)]"


def test_summarize_poll_marker() -> None:
    poll = MagicMock()
    assert summarize_message(_make_message(poll=poll)) == "[poll]"


def test_summarize_forwarded_marker() -> None:
    assert (
        summarize_message(_make_message(snapshots=[MagicMock()]))
        == "[1 forwarded message(s)]"
    )


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
    result = describe_message_full(_make_message(content="y" * 5000), max_content=100)
    assert "truncated 5000 chars" in result
    assert "y" * 5000 not in result
