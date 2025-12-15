"""Unit tests for the tasks.py - Consolidated version"""

import datetime
import importlib
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import feedparser
import pytest
from feedparser import FeedParserDict
from pytest_mock import MockerFixture

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
        cog.clean_channel_members_task.start = MagicMock()
        cog.clean_channel_members_task.cancel = MagicMock()
        cog.clean_channel_members_task.is_running = MagicMock(return_value=False)
        cog.clean_channel_members_task_dry_run.start = MagicMock()
        cog.clean_channel_members_task_dry_run.cancel = MagicMock()
        cog.clean_channel_members_task_dry_run.is_running = MagicMock(
            return_value=False
        )
        cog.monitor_youtube_videos.start = MagicMock()
        cog.monitor_youtube_videos.cancel = MagicMock()
        cog.monitor_youtube_videos.is_running = MagicMock(return_value=False)
        return cog


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
def mock_member_old_kickable() -> MagicMock:
    """
    Mock a member who joined over a week ago and does not have
    the Garage Member role - should be kicked
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
def mock_member_garage(mock_config: MagicMock) -> MagicMock:
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


def create_test_member(
    name: str,
    member_id: int,
    joined_at: datetime.datetime | None = None,
    roles: list[discord.Role] | None = None,
) -> MagicMock:
    """Helper function to create test members"""
    member = MagicMock(spec=discord.Member)
    member.display_name = name
    member.id = member_id
    member.__str__ = MagicMock(return_value=f"{name}#{member_id}")
    member.joined_at = joined_at
    member.roles = roles or [MagicMock()]
    member.send = AsyncMock()
    member.kick = AsyncMock()
    return member


class TestTasks:
    """Test cases for the Tasks cog."""

    def test_clean_members_task_already_running_normal(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """
        Test initialization when the clean_channel_members_task
        is already running (line 34)
        """
        mock_config.DRY_RUN = False

        with patch("discord.ext.tasks.Loop.start"), caplog.at_level(logging.WARNING):
            # Create a Tasks instance first
            cog = Tasks(discord_bot)

            # Mock the task as running and re-initialize to trigger the warning
            with patch.object(cog, "clean_channel_members_task") as mock_task:
                mock_task.is_running.return_value = True

                # Call __init__ again to trigger the already running logic
                Tasks.__init__(cog, discord_bot)

            # Verify the warning was logged
            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert len(warning_records) >= 1
            assert any(
                "clean_channel_members_task task is already running" in record.message
                for record in warning_records
            )

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_cog_initialization(
        self, discord_bot: DiscordBot, mock_config: MagicMock, dry_run: bool
    ) -> None:
        """Test that the Tasks cog initializes correctly in both modes"""
        mock_config.DRY_RUN = dry_run

        with patch("discord.ext.tasks.Loop.start") as mock_start:
            cog = Tasks(discord_bot)
            assert cog is not None
            assert isinstance(cog, Tasks)
            assert mock_start.call_count == 2

    @pytest.mark.parametrize("dry_run", [True, False])
    @async_test
    async def test_cog_unload(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mocker: MockerFixture,
        dry_run: bool,
    ) -> None:
        """Test that cog_unload cancels the correct task"""
        mock_config.DRY_RUN = dry_run

        # Spy on the cancel methods to track calls
        dry_run_cancel_spy = mocker.spy(
            tasks_cog.clean_channel_members_task_dry_run, "cancel"
        )
        normal_cancel_spy = mocker.spy(tasks_cog.clean_channel_members_task, "cancel")

        await tasks_cog.cog_unload()

        if dry_run:
            dry_run_cancel_spy.assert_called_once()
            normal_cancel_spy.assert_not_called()
        else:
            normal_cancel_spy.assert_called_once()
            dry_run_cancel_spy.assert_not_called()

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

    @pytest.mark.parametrize(
        ("is_sunday", "should_run"),
        [
            (False, False),  # Monday - shouldn't run
            (True, True),  # Sunday - should run
        ],
    )
    @async_test
    async def test_clean_channel_members_task_weekday_logic(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        is_sunday: bool,
        should_run: bool,
    ) -> None:
        """Test that clean_channel_members_task only runs on Sunday"""
        # Mock the appropriate day
        mock_day = datetime.datetime(
            2023, 1, 8 if is_sunday else 2, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )  # Sunday vs Monday

        with patch("lib.cogs.tasks.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = mock_day

            # Mock the _get_channel_members_to_kick method
            tasks_cog._get_channel_members_to_kick = AsyncMock(return_value=set())
            tasks_cog.bot.log_bot_event = AsyncMock()

            await tasks_cog.clean_channel_members_task()

            if should_run:
                tasks_cog._get_channel_members_to_kick.assert_called_once()
            else:
                tasks_cog._get_channel_members_to_kick.assert_not_called()

    @async_test
    async def test_clean_channel_members_task_dry_run_always_runs(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test that dry_run task always runs regardless of day"""
        # Mock it to be Monday
        mock_monday = datetime.datetime(
            2023, 1, 2, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        tasks_cog._get_channel_members_to_kick = AsyncMock(return_value=set())
        tasks_cog.bot.log_bot_event = AsyncMock()

        with patch("lib.cogs.tasks.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = mock_monday

            await tasks_cog.clean_channel_members_task_dry_run()

        # Should run even on Monday
        tasks_cog._get_channel_members_to_kick.assert_called_once()

    @async_test
    async def test_get_channel_members_to_kick_guild_not_found(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """
        Test that _get_channel_members_to_kick raises ValueError when guild not found
        """
        tasks_cog.bot.get_guild = MagicMock(return_value=None)

        with pytest.raises(
            ValueError,
            match=f"Guild with ID {mock_config.GUILDS.JIMS_GARAGE} not found",
        ):
            await tasks_cog._get_channel_members_to_kick()

    @pytest.mark.parametrize(
        ("member_fixture_name", "should_be_kicked"),
        [
            ("mock_member_new", False),  # Recent member - safe
            ("mock_member_bot", False),  # Bot member - safe
            ("mock_member_garage", False),  # Has garage role - safe
            (
                "mock_member_old_kickable",
                True,
            ),  # Old member without garage role - kicked
        ],
    )
    @async_test
    async def test_get_channel_members_to_kick_member_filtering(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_guild: MagicMock,
        request: pytest.FixtureRequest,
        member_fixture_name: str,
        should_be_kicked: bool,
    ) -> None:
        """Test member filtering logic using existing fixtures"""
        member = request.getfixturevalue(member_fixture_name)
        mock_guild.members = [member]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.INFO):
            kick_list = await tasks_cog._get_channel_members_to_kick()

        assert isinstance(kick_list, set)
        if should_be_kicked:
            assert len(kick_list) == 1
            assert member in kick_list
        else:
            assert len(kick_list) == 0
            assert member not in kick_list

    @async_test
    async def test_get_channel_members_to_kick_member_no_joined_time(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_guild: MagicMock,
    ) -> None:
        """Test _get_channel_members_to_kick skips members with no joined_at time"""
        member_no_join = MagicMock(spec=discord.Member)
        member_no_join.joined_at = None

        mock_guild.members = [member_no_join]
        tasks_cog.bot.get_guild = MagicMock(return_value=mock_guild)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            kick_list = await tasks_cog._get_channel_members_to_kick()

        assert len(kick_list) == 0
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "has no `joined_at` timestamp" in warning_records[0].message

    @pytest.mark.parametrize(
        ("member_count", "dry_run"),
        [
            (0, False),  # No members to kick - normal mode
            (0, True),  # No members to kick - dry run mode
            (1, False),  # Single member - normal mode
            (1, True),  # Single member - dry run mode
            (2, False),  # Multiple members - normal mode
            (2, True),  # Multiple members - dry run mode
        ],
    )
    @async_test
    async def test_clean_channel_members_task_execution(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_member_old_kickable: MagicMock,
        member_count: int,
        dry_run: bool,
    ) -> None:
        """Test task execution with various member counts and modes"""
        # Mock it to be Sunday for normal mode
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Create test members
        members = set()
        if member_count > 0:
            members.add(mock_member_old_kickable)
        if member_count > 1:
            member2 = create_test_member(
                "Member2", 67890, datetime.datetime(2023, 1, 2, tzinfo=datetime.UTC)
            )
            members.add(member2)

        tasks_cog._get_channel_members_to_kick = AsyncMock(return_value=members)
        mock_log_bot_event = mocker.patch.object(
            tasks_cog.bot, "log_bot_event", new=AsyncMock()
        )

        if not dry_run:
            with (
                patch("lib.cogs.tasks.asyncio.sleep") as mock_sleep,
                patch("lib.cogs.tasks.datetime.datetime") as mock_dt,
                caplog.at_level(logging.INFO),
            ):
                mock_dt.now.return_value = mock_sunday
                await tasks_cog.clean_channel_members_task()
                event_name = "Task - 🧹 Member Cleanup"
                log_prefix = ""
        else:
            with (
                patch("lib.cogs.tasks.asyncio.sleep") as mock_sleep,
                caplog.at_level(logging.INFO),
            ):
                await tasks_cog.clean_channel_members_task_dry_run()
                event_name = "Task - 🧹 Member Cleanup (DRY_RUN)"
                log_prefix = "DRY_RUN: Would have "

        # Verify sleep called for each member
        assert mock_sleep.call_count == member_count

        # Verify member actions
        for member in members:
            if dry_run:
                member.send.assert_not_called()
                member.kick.assert_not_called()
            elif member_count > 0:
                member.send.assert_called_once()
                member.kick.assert_called_once()

        # Verify logging
        if member_count > 0:
            log_messages = [r.message for r in caplog.records]
            expected_cleaned_msg = (
                f"{log_prefix}cleaned {member_count} members"
                if log_prefix
                else f"Cleaned {member_count} members"
            )
            assert any(
                expected_cleaned_msg.lower() in msg.lower() for msg in log_messages
            )

        # Verify bot event logging
        mock_log_bot_event.assert_called_with(
            event=event_name,
            details=f"{'Would have c' if dry_run else 'C'}"
            f"leaned {member_count} members.",
        )

    @pytest.mark.parametrize(
        "exception_type",
        [
            discord.Forbidden,
            discord.HTTPException,
        ],
    )
    @async_test
    async def test_clean_channel_members_task_dm_exceptions(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        mock_member_old_kickable: MagicMock,
        exception_type: type[Exception],
    ) -> None:
        """Test DM sending failure handling"""
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Set up the exception
        if exception_type == discord.Forbidden:
            mock_member_old_kickable.send.side_effect = discord.Forbidden(
                MagicMock(), "Cannot send messages to this user"
            )
            expected_log = "Could not send DM to OldMember"
        else:  # HTTPException
            mock_member_old_kickable.send.side_effect = discord.HTTPException(
                MagicMock(), "HTTP error"
            )
            expected_log = "Failed to send DM to OldMember:"

        tasks_cog._get_channel_members_to_kick = AsyncMock(
            return_value={mock_member_old_kickable}
        )
        tasks_cog.bot.log_bot_event = AsyncMock()

        with (
            patch("lib.cogs.tasks.datetime.datetime") as mock_dt,
            patch("lib.cogs.tasks.asyncio.sleep"),
            caplog.at_level(logging.WARNING),
        ):
            mock_dt.now.return_value = mock_sunday
            await tasks_cog.clean_channel_members_task()

        # Verify member was still kicked despite DM failure
        mock_member_old_kickable.kick.assert_called_once()

        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert expected_log in warning_records[0].message

    @async_test
    async def test_clean_channel_members_task_member_no_join_date_logging(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test logging for a member with no join date shows 'Unknown'"""
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Create a member with no joined_at date
        member = create_test_member("MemberNoDate", 1234, joined_at=None)

        tasks_cog._get_channel_members_to_kick = AsyncMock(return_value={member})
        tasks_cog.bot.log_bot_event = AsyncMock()

        with (
            patch("lib.cogs.tasks.datetime.datetime") as mock_dt,
            patch("lib.cogs.tasks.asyncio.sleep"),
            caplog.at_level(logging.INFO),
        ):
            mock_dt.now.return_value = mock_sunday
            await tasks_cog.clean_channel_members_task()

        # Verify logging shows "Unknown" for join date
        log_messages = [r.message for r in caplog.records]
        assert any(
            "Kicked MemberNoDate" in msg and "Unknown" in msg for msg in log_messages
        )

    @async_test
    async def test_clean_channel_members_task_dry_run_member_no_join_date_logging(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test dry run logging for a member with no join date shows 'Unknown'"""
        # Create a member with no joined_at date
        member = create_test_member("DryRunMemberNoDate", 1234, joined_at=None)

        tasks_cog._get_channel_members_to_kick = AsyncMock(return_value={member})
        tasks_cog.bot.log_bot_event = AsyncMock()

        with (
            patch("lib.cogs.tasks.asyncio.sleep"),
            caplog.at_level(logging.INFO),
        ):
            await tasks_cog.clean_channel_members_task_dry_run()

        # Verify DRY_RUN logging shows "Unknown" for join date
        log_messages = [r.message for r in caplog.records]
        assert any(
            "DRY_RUN: Would have kicked DryRunMemberNoDate" in msg and "Unknown" in msg
            for msg in log_messages
        )

    def test_type_checking_import_coverage(self) -> None:
        """Test to ensure TYPE_CHECKING import block is covered"""
        # Remove the module from sys.modules to force reimport
        module_name = "lib.cogs.tasks"
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Mock TYPE_CHECKING to be True to force execution of the import block
        with patch("typing.TYPE_CHECKING", new=True):
            # Reimport the module which will now execute the TYPE_CHECKING block
            import lib.cogs.tasks as tasks_module  # noqa: PLC0415

            importlib.reload(tasks_module)

            # Verify the module is properly loaded
            assert hasattr(tasks_module, "Tasks")

    def test_clean_members_task_already_running_dry_run(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """
        Test initialization when clean_channel_members_task_dry_run
        is already running (line 28)
        """
        mock_config.DRY_RUN = True

        with patch("discord.ext.tasks.Loop.start"), caplog.at_level(logging.WARNING):
            # Create a Tasks instance first
            cog = Tasks(discord_bot)

            # Mock the task as running and re-initialize to trigger the warning
            with patch.object(cog, "clean_channel_members_task_dry_run") as mock_task:
                mock_task.is_running.return_value = True

                # Call __init__ again to trigger the already running logic
                Tasks.__init__(cog, discord_bot)

            # Verify the warning was logged
            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert len(warning_records) >= 1
            assert any(
                "clean_channel_members_task_dry_run task is already running"
                in record.message
                for record in warning_records
            )

    def test_monitor_youtube_videos_task_already_running(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """
        Test initialization when `monitor_youtube_videos task` is already running
        """
        mock_config.DRY_RUN = False

        with patch("discord.ext.tasks.Loop.start"), caplog.at_level(logging.WARNING):
            # Create a Tasks instance first
            cog = Tasks(discord_bot)

            # Mock the task as running and re-initialize to trigger the warning
            with patch.object(cog, "monitor_youtube_videos") as mock_task:
                mock_task.is_running.return_value = True

                # Call __init__ again to trigger the already running logic
                Tasks.__init__(cog, discord_bot)

            # Verify the warning was logged
            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert len(warning_records) >= 1
            assert any(
                "monitor_youtube_videos task is already running" in record.message
                for record in warning_records
            )

    @async_test
    async def test_monitor_youtube_videos_with_new_videos(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test the monitor_youtube_videos method when new videos are found"""
        # Mock feed parser with new videos
        video1 = FeedParserDict(
            {
                "id": "yt:video:abcdef123",
                "link": "https://www.youtube.com/watch?v=abcdef123",
                "yt_videoid": "abcdef123",
                "title": "Test Video 1",
                "author": "Test Author 1",
                "published": "2025-10-20T12:00:00+00:00",
                "summary": "Test Summary 1\nOther summary stuff",
            }
        )

        video2 = FeedParserDict(
            {
                "id": "yt:video:ghijkl456",
                "link": "https://www.youtube.com/watch?v=abcdef123",
                "yt_videoid": "abcdef123",
                "title": "Test Video 2",
                "author": "Test Author 2",
                "published": "2025-10-20T12:00:00+00:00",
                "summary": "Test Summary 2\nOther summary stuff",
            }
        )

        mock_feed_parser = MagicMock()
        mock_feed_parser.get_new_videos.return_value = [video1, video2]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        # Mock channel
        mock_channel = MagicMock(spec=discord.TextChannel)
        tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)

        # Mock bot event logging
        mock_log_bot_event = mocker.patch.object(
            tasks_cog.bot, "log_bot_event", new=AsyncMock()
        )

        with caplog.at_level(logging.INFO):
            await tasks_cog.monitor_youtube_videos()

        # Verify logging
        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert any(
            f"New videos found for test_feed: [{video1}, {video2}]" in record.message
            for record in info_records
        )

        # Verify bot event was logged
        mock_log_bot_event.assert_called_with(
            event="Task - YouTube Video Monitor",
            details=f"New videos found for test_feed: [{video1}, {video2}]",
        )

        # Verify channel send was called
        assert mock_channel.send.call_count == 2

    @async_test
    async def test_monitor_youtube_videos_with_invalid_entries(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test the monitor_youtube_videos method when invalid entries are found"""
        mock_feed_parser = MagicMock()
        mock_feed_parser.get_new_videos.return_value = [
            {},
            None,
            "",
            [],
        ]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        mock_channel = MagicMock(spec=discord.TextChannel)
        tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        assert len(caplog.records) == len(mock_feed_parser.get_new_videos.return_value)

    @async_test
    async def test_monitor_youtube_videos_with_new_videos_announcements_channel(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """
        Test monitor_youtube_videos method uses the ANNOUNCEMENTS channel
        when DRY_RUN=False (line 192)
        """
        mock_config.DRY_RUN_YOUTUBE = False

        # Mock feed parser with new videos
        video1 = FeedParserDict(
            {
                "id": "yt:video:abcdef123",
                "link": "https://www.youtube.com/watch?v=abcdef123",
                "yt_videoid": "abcdef123",
                "title": "Test Video 1",
                "author": "Test Author",
                "published": "2025-10-20T12:00:00+00:00",
                "summary": "Test Summary\nOther summary stuff",
            }
        )
        mock_feed_parser = MagicMock()
        mock_feed_parser.get_new_videos.return_value = [video1]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        # Mock channel
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_get_channel = MagicMock(return_value=mock_channel)
        tasks_cog.bot.get_channel = mock_get_channel
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.INFO):
            await tasks_cog.monitor_youtube_videos()

        # Verify the ANNOUNCEMENTS channel was requested (line 192)
        mock_get_channel.assert_called_with(987)

        # Verify channel send was called
        mock_channel.send.assert_called_once()

    @async_test
    async def test_monitor_youtube_videos_no_new_videos(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test the monitor_youtube_videos method when no new videos are found"""
        # Mock feed parser with no new videos
        mock_feed_parser = MagicMock()
        mock_feed_parser.get_new_videos.return_value = []
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        tasks_cog.bot.get_channel = MagicMock()
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.DEBUG):
            await tasks_cog.monitor_youtube_videos()

        # Verify logging
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert any(
            "Checking test_feed for new videos" in record.message
            for record in debug_records
        )
        assert any("No new videos found" in record.message for record in debug_records)

        # Verify `channel` was not accessed due to there being no new videos
        tasks_cog.bot.get_channel.assert_not_called()

    # @pytest.mark.no_mock_config
    @async_test
    async def test_monitor_youtube_videos_channel_selection(
        self,
        tasks_cog: Tasks,
    ) -> None:
        """Test monitor_youtube_videos method channel selection based on DRY_RUN"""
        # Mock feed parser with new videos
        mock_feed_parser = MagicMock()
        mock_feed_parser.parse_rss_feed.return_value = ["video1"]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        # Mock channel
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_get_channel = MagicMock(return_value=mock_channel)
        tasks_cog.bot.get_channel = mock_get_channel
        tasks_cog.bot.log_bot_event = AsyncMock()

        # Test DRY_RUN = True
        with (
            patch("lib.cogs.tasks.config.DRY_RUN_YOUTUBE", new=True),
            patch("lib.cogs.tasks.config.CHANNELS") as mock_channels,
        ):
            mock_channels.BOT_PLAYGROUND = 123
            await tasks_cog.monitor_youtube_videos()
            mock_get_channel.assert_called_with(123)

        # Reset mock
        mock_get_channel.reset_mock()

        # Test DRY_RUN = False
        with (
            patch("lib.cogs.tasks.config.DRY_RUN_YOUTUBE", new=False),
            patch("lib.cogs.tasks.config.CHANNELS") as mock_channels,
        ):
            mock_channels.ANNOUNCEMENTS = 987
            await tasks_cog.monitor_youtube_videos()
            mock_get_channel.assert_called_with(987)

    @async_test
    async def test_monitor_youtube_videos_channel_not_found(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test monitor_youtube_videos method when the channel is not found"""
        mock_config.DRY_RUN = False

        # Mock feed parser with new videos
        mock_feed_parser = MagicMock()
        mock_feed_parser.parse_rss_feed.return_value = ["video1"]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        # Mock channel as None (not found)
        tasks_cog.bot.get_channel = MagicMock(return_value=None)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "Could not find channel with ID" in warning_records[0].message
        assert "or it is not a TextChannel" in warning_records[0].message

    @async_test
    async def test_monitor_youtube_videos_channel_wrong_type(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test monitor_youtube_videos method when the channel is not TextChannel"""
        mock_config.DRY_RUN = False

        # Mock feed parser with new videos
        mock_feed_parser = MagicMock()
        mock_feed_parser.parse_rss_feed.return_value = ["video1"]
        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        # Mock channel as a wrong type (VoiceChannel)
        mock_channel = MagicMock(spec=discord.VoiceChannel)
        tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "Could not find channel with ID" in warning_records[0].message
        assert "or it is not a TextChannel" in warning_records[0].message

    @async_test
    async def test_before_monitor_youtube_videos(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_config: MagicMock,
        tasks_cog: Tasks,
    ) -> None:
        """Test before_monitor_youtube_videos method"""
        # Mock YouTube feed parser
        with patch("lib.cogs.tasks.youtube.YoutubeFeedParser") as mock_parser_class:
            mock_parser_instance = MagicMock()
            mock_parser_class.return_value = mock_parser_instance
            tasks_cog.bot.wait_until_ready = AsyncMock()

            mock_config.DRY_RUN_YOUTUBE = False

            with caplog.at_level(logging.INFO):
                await tasks_cog.before_monitor_youtube_videos()

        # Verify logging
        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert any(
            "monitor_youtube_videos task is starting up..." in record.message
            for record in info_records
        )
        assert any(
            "Initialized YouTube feed parser for JIMS_GARAGE" in record.message
            for record in info_records
        )
        assert any(
            "Initialized YouTube feed parser for TECH_BENCH" in record.message
            for record in info_records
        )
        assert any(
            "Initialized 2 YouTube video monitors" in record.message
            for record in info_records
        )

        # Verify YouTube feed parsers were created with correct feeds from mock config
        assert mock_parser_class.call_count == 2
        mock_parser_class.assert_any_call(
            "jims_garage",
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCUUTdohVElFLSP4NBnlPEwA",
        )
        mock_parser_class.assert_any_call(
            "tech_bench",
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCT5B7jBug46N7abnl_izt5w",
        )

        # Verify feeds were stored with correct names
        assert "JIMS_GARAGE" in tasks_cog.youtube_feeds
        assert "TECH_BENCH" in tasks_cog.youtube_feeds

        # Verify bot wait_until_ready was called
        tasks_cog.bot.wait_until_ready.assert_called_once()

    @async_test
    async def test_before_monitor_youtube_videos_dry_run(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_config: MagicMock,
        tasks_cog: Tasks,
    ) -> None:
        """
        Test before_monitor_youtube_videos method with
        DRY_RUN_YOUTUBE=True
        """
        # Create a mock video entry that supports attribute access
        video1 = MagicMock(spec=feedparser.FeedParserDict)
        video1.id = "yt:video:abcdef123"
        video1.link = "https://www.youtube.com/watch?v=abcdef123"
        video1.yt_videoid = "abcdef123"
        video1.title = "Test Video 1"
        video1.author = "Test Author"
        video1.published = "2025-10-20T12:00:00+00:00"
        video1.summary = "Test Summary\nOther summary stuff"

        with patch("lib.cogs.tasks.youtube.YoutubeFeedParser") as mock_parser_class:
            mock_parser_instance = MagicMock()
            mock_parser_class.return_value = mock_parser_instance
            mock_parser_instance.get_latest_video.return_value = video1
            tasks_cog.bot.wait_until_ready = AsyncMock()

            mock_config.DRY_RUN_YOUTUBE = True

            mock_channel = MagicMock(spec=discord.TextChannel)
            tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)

            with caplog.at_level(logging.INFO):
                await tasks_cog.before_monitor_youtube_videos()

            info_records = [r for r in caplog.records if r.levelname == "INFO"]
            assert any(
                "Sending embed log message to" in record.message
                for record in info_records
            )

            # Should be called twice - once for each feed in mock_config.YOUTUBE_FEEDS
            assert mock_channel.send.call_count == 2

    @async_test
    async def test_before_monitor_youtube_videos_dry_run_invalid_channel(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_config: MagicMock,
        tasks_cog: Tasks,
    ) -> None:
        """
        Test before_monitor_youtube_videos method with
        DRY_RUN_YOUTUBE=True and an invalid channel
        """
        with patch("lib.cogs.tasks.youtube.YoutubeFeedParser") as mock_parser_class:
            mock_parser_instance = MagicMock()
            mock_parser_class.return_value = mock_parser_instance
            tasks_cog.bot.wait_until_ready = AsyncMock()

            mock_config.DRY_RUN_YOUTUBE = True

            with caplog.at_level(logging.ERROR):
                await tasks_cog.before_monitor_youtube_videos()

            assert (
                "Invalid channel specified in DRY_RUN_YOUTUBE mode:"
                in caplog.records[-1].message
            )
