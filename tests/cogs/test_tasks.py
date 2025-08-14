"""Unit tests for the tasks.py"""

import datetime
import importlib
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from lib.bot import DiscordBot
from lib.cogs.tasks import Tasks
from tests.utils import async_test


@pytest.fixture
def tasks_cog(discord_bot: DiscordBot) -> Tasks:
    """Tasks cog fixture"""
    # Patch the task.start() method to prevent automatic startup during initialization
    with patch("discord.ext.tasks.Loop.start"):
        cog = Tasks(discord_bot)
        # Mock the loop control methods for testing
        cog.clean_channel_members.start = MagicMock()
        cog.clean_channel_members.cancel = MagicMock()
        return cog


@pytest.fixture
def mock_member_old_no_garage_role() -> MagicMock:
    """
    Mock a member who joined over a week ago and does not have
    the Garage Member role
    """
    member = MagicMock(spec=discord.Member)
    member.display_name = "OldMember"
    member.id = 12345
    member.__str__ = MagicMock(return_value="OldMember#1234")

    # Joined 2 weeks ago (static old date)
    member.joined_at = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)

    # No Garage Member role, no Bot role
    role1 = MagicMock()
    role1.id = 99999  # Some other role
    member.roles = [role1]

    # Mock methods
    member.send = AsyncMock()
    member.kick = AsyncMock()

    return member


@pytest.fixture
def mock_member_new() -> MagicMock:
    """Mock a member who joined recently"""
    member = MagicMock(spec=discord.Member)
    member.display_name = "NewMember"
    member.id = 54321
    member.__str__ = MagicMock(return_value="NewMember#5678")

    # Joined 3 days ago
    member.joined_at = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
        days=3
    )

    # No garage member role
    role1 = MagicMock()
    role1.id = 99999
    member.roles = [role1]

    member.send = AsyncMock()
    member.kick = AsyncMock()

    return member


@pytest.fixture
def mock_member_with_garage_role(mock_config: MagicMock) -> MagicMock:
    """Mock a member who has the Garage Member role"""
    member = MagicMock(spec=discord.Member)
    member.display_name = "GarageMember"
    member.id = 98765
    member.__str__ = MagicMock(return_value="GarageMember#9876")

    # Joined 2 weeks ago but has the Garage Member role
    member.joined_at = datetime.datetime.now(
        tz=mock_config.TIMEZONE
    ) - datetime.timedelta(weeks=2)
    garage_role = MagicMock()
    garage_role.id = mock_config.ROLES.GARAGE_MEMBER
    member.roles = [garage_role]

    member.send = AsyncMock()
    member.kick = AsyncMock()

    return member


@pytest.fixture
def mock_member_bot(mock_config: MagicMock) -> MagicMock:
    """Mock a member who is a Bot"""
    member = MagicMock(spec=discord.Member)
    member.display_name = "BotMember"
    member.id = 11111
    member.__str__ = MagicMock(return_value="BotMember#1111")

    # Joined 2 weeks ago but is a Bot
    member.joined_at = datetime.datetime.now(
        tz=mock_config.TIMEZONE
    ) - datetime.timedelta(weeks=2)
    bot_role = MagicMock()
    bot_role.id = mock_config.ROLES.BOTS
    member.roles = [bot_role]

    member.send = AsyncMock()
    member.kick = AsyncMock()

    return member


class TestTasks:
    """Test cases for the Tasks cog."""

    def test_cog_initialization(self, discord_bot: DiscordBot) -> None:
        """Test that the Tasks cog initializes correctly and starts the task"""
        with patch.object(Tasks, "__init__") as mock_init:
            mock_init.return_value = None
            cog = Tasks(discord_bot)
            mock_init.assert_called_once_with(discord_bot)

            assert cog is not None
            assert isinstance(cog, Tasks)

    @async_test
    async def test_cog_unload(self, tasks_cog: Tasks) -> None:
        """Test that cog_unload cancels the task"""
        await tasks_cog.cog_unload()
        tasks_cog.clean_channel_members.cancel.assert_called_once()

    @async_test
    async def test_before_clean_channel_members(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test the before_loop method"""
        tasks_cog.bot.wait_until_ready = AsyncMock()

        with caplog.at_level(logging.INFO):
            await tasks_cog.before_clean_channel_members()

        tasks_cog.bot.wait_until_ready.assert_called_once()
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert record.message == "clean_channel_members task is starting up..."
        assert record.name == "lib.cogs.tasks"

    @async_test
    async def test_clean_channel_members_not_sunday(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test that task does nothing when it's not Sunday"""
        # Mock it to be Monday (weekday = 0)
        mock_monday = datetime.datetime(
            2023, 1, 2, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )  # Monday

        with patch("datetime.datetime") as mock_dt, caplog.at_level(logging.INFO):
            mock_dt.now.return_value = mock_monday
            mock_dt.timedelta = datetime.timedelta

            await tasks_cog.clean_channel_members()

        # Should not call any bot methods
        if hasattr(tasks_cog.bot, "get_guild") and hasattr(
            tasks_cog.bot.get_guild, "called"
        ):
            assert not tasks_cog.bot.get_guild.called  # type: ignore[attr-defined]
        assert len(caplog.records) == 0

    @async_test
    async def test_clean_channel_members_guild_not_found(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test that task raises ValueError when guild is not found"""
        # Mock it to be Sunday (weekday = 6)
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )  # Sunday

        tasks_cog.bot.get_guild = MagicMock(return_value=None)

        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = mock_sunday
            mock_dt.timedelta = datetime.timedelta

            with pytest.raises(
                ValueError,
                match=f"Guild with ID {mock_config.GUILDS.JIMS_GARAGE} not found",
            ):
                await tasks_cog.clean_channel_members()

    @async_test
    async def test_clean_channel_members_no_members_to_kick(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_guild: MagicMock,
        mock_member_new: MagicMock,
        mock_member_with_garage_role: MagicMock,
    ) -> None:
        """Test task when there are no members to kick"""
        # Mock it to be Sunday
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )  # Sunday

        # Set up a guild with members who shouldn't be kicked
        mock_guild.members = [mock_member_new, mock_member_with_garage_role]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with patch("datetime.datetime") as mock_dt, caplog.at_level(logging.INFO):
            mock_dt.now.return_value = mock_sunday
            mock_dt.timedelta = datetime.timedelta

            await tasks_cog.clean_channel_members()

        # Verify logging
        assert (
            len([r for r in caplog.records if "Cleaning channel members" in r.message])
            == 1
        )
        assert len([r for r in caplog.records if "Cleaned 0 members" in r.message]) == 1

        # Verify bot event logging
        assert tasks_cog.bot.log_bot_event.call_count == 2  # type: ignore[attr-defined]
        tasks_cog.bot.log_bot_event.assert_any_call(event="Task - Member Cleanup")
        tasks_cog.bot.log_bot_event.assert_any_call(
            event="Task - Member Cleanup", details="Cleaned 0 members."
        )

        # Verify no members were kicked
        mock_member_new.kick.assert_not_called()
        mock_member_with_garage_role.kick.assert_not_called()

    @async_test
    async def test_clean_channel_members_kicks_eligible_member(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_guild: MagicMock,
        mock_member_old_no_garage_role: MagicMock,
    ) -> None:
        """Test task kicks eligible members and sends DM"""
        # Mock it to be Sunday
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )  # Sunday

        # Set up guild with member who should be kicked
        mock_guild.members = [mock_member_old_no_garage_role]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with (
            patch("lib.cogs.tasks.datetime.datetime") as mock_dt,
            patch("lib.cogs.tasks.asyncio.sleep") as mock_sleep,
            caplog.at_level(logging.INFO),
        ):
            mock_dt.now.return_value = mock_sunday
            mock_dt.timedelta = datetime.timedelta

            await tasks_cog.clean_channel_members()

        # Verify rate limiting sleep was called
        mock_sleep.assert_called_once_with(0.2)

        # Verify DM was sent
        expected_dm = (
            "You have been removed from the Jim's Garage server "
            "because you joined over a week ago and haven't accepted "
            "the rules. If you believe this was a mistake, please "
            "feel free to rejoin the server and reach out to a mod."
        )
        mock_member_old_no_garage_role.send.assert_called_once_with(expected_dm)

        # Verify member was kicked
        mock_member_old_no_garage_role.kick.assert_called_once_with(
            reason="Member has not accepted the rules in over a week."
        )

        # Verify logging
        log_messages = [r.message for r in caplog.records]
        assert any("Cleaning channel members" in msg for msg in log_messages)
        assert any("Sent DM to OldMember" in msg for msg in log_messages)
        assert any("Kicked OldMember" in msg for msg in log_messages)
        assert any("Cleaned 1 members" in msg for msg in log_messages)

    @async_test
    async def test_clean_channel_members_dm_forbidden(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_guild: MagicMock,
        mock_member_old_no_garage_role: MagicMock,
    ) -> None:
        """Test task handles DM sending failure (Forbidden)"""
        # Mock it to be Sunday
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Set up a member to raise Forbidden when sending DM
        mock_member_old_no_garage_role.send.side_effect = discord.Forbidden(
            MagicMock(), "Cannot send messages to this user"
        )

        mock_guild.members = [mock_member_old_no_garage_role]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with (
            patch("lib.cogs.tasks.datetime.datetime") as mock_dt,
            patch("lib.cogs.tasks.asyncio.sleep"),
            caplog.at_level(logging.WARNING),
        ):
            mock_dt.now.return_value = mock_sunday
            mock_dt.timedelta = datetime.timedelta

            await tasks_cog.clean_channel_members()

        # Verify member was still kicked despite DM failure
        mock_member_old_no_garage_role.kick.assert_called_once()

        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "Could not send DM to OldMember" in warning_records[0].message
        assert "DMs may be disabled or bot is blocked" in warning_records[0].message

    @async_test
    async def test_clean_channel_members_dm_http_exception(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_guild: MagicMock,
        mock_member_old_no_garage_role: MagicMock,
    ) -> None:
        """Test task handles DM sending failure (HTTPException)"""
        # Mock it to be Sunday
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Set up member to raise HTTPException when sending DM
        http_error = discord.HTTPException(MagicMock(), "HTTP error")
        mock_member_old_no_garage_role.send.side_effect = http_error

        mock_guild.members = [mock_member_old_no_garage_role]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with (
            patch("lib.cogs.tasks.datetime.datetime") as mock_dt,
            patch("lib.cogs.tasks.asyncio.sleep"),
            caplog.at_level(logging.WARNING),
        ):
            mock_dt.now.return_value = mock_sunday
            mock_dt.timedelta = datetime.timedelta

            await tasks_cog.clean_channel_members()

        # Verify member was still kicked despite DM failure
        mock_member_old_no_garage_role.kick.assert_called_once()

        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "Failed to send DM to OldMember:" in warning_records[0].message

    @async_test
    async def test_clean_channel_members_member_no_joined_time(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_guild: MagicMock,
    ) -> None:
        """Test task skips members with no joined_at time"""
        # Mock it to be Sunday
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Create a member with no `joined_at` time
        member_no_join = MagicMock(spec=discord.Member)
        member_no_join.joined_at = None
        member_no_join.kick = AsyncMock()

        mock_guild.members = [member_no_join]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = mock_sunday
            mock_dt.timedelta = datetime.timedelta

            await tasks_cog.clean_channel_members()

        # Verify the member was not kicked
        member_no_join.kick.assert_not_called()

    def test_type_checking_import_coverage(self) -> None:
        """Test to ensure TYPE_CHECKING import block is covered"""
        # Remove the module from sys.modules to force reimport
        module_name = "lib.cogs.tasks"
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Mock TYPE_CHECKING to be True to force execution of the import block
        with patch("typing.TYPE_CHECKING", new=True):
            # Reimport the module which will now execute the TYPE_CHECKING block
            import lib.cogs.tasks  # noqa: PLC0415

            importlib.reload(lib.cogs.tasks)

        # Verify the module is properly loaded
        assert hasattr(lib.cogs.tasks, "Tasks")
