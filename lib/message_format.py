"""Render Discord messages for logging and moderation embeds."""

from typing import TYPE_CHECKING

from lib.config import config

if TYPE_CHECKING:
    import discord


def summarize_message(message: discord.Message, max_length: int | None = None) -> str:
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


def describe_message_full(message: discord.Message, max_content: int = 4000) -> str:
    """
    Build a full-fidelity, single-line description of a message for the log
    file. `content` and payload fields are repr-escaped so attacker-controlled
    newlines cannot fragment the log line (kept single-line for Loki).
    """
    content = message.content
    if len(content) > max_content:
        content = f"{content[:max_content]}... (truncated {len(content)} chars)"

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
            f"size={attachment.size}, url={attachment.url!r})"
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
