"""Unit tests for the tasks.py - Consolidated version"""

import datetime
import importlib
import logging
import sys
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import discord
import feedparser
import pytest
from feedparser import FeedParserDict

from lib.cogs.tasks import Tasks
from lib.github import GitHubActivityEvent
from tests.utils import async_test

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from lib.bot import DiscordBot


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
        cog.monitor_github_activity.start = MagicMock()
        cog.monitor_github_activity.cancel = MagicMock()
        cog.monitor_github_activity.is_running = MagicMock(return_value=False)
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


class TestFormatKickedUsersList:
    """Test cases for the _format_kicked_users_list helper function."""

    def test_format_kicked_users_list_empty(self) -> None:
        """Test that an empty set returns 'None'"""
        result = Tasks._format_kicked_users_list(set())
        assert result == "None"

    def test_format_kicked_users_list_single_user(self) -> None:
        """Test single user formats correctly with all fields"""
        member = create_test_member(
            "JohnDoe",
            12345,
            joined_at=datetime.datetime(2025, 12, 15, 10, 30, 0, tzinfo=datetime.UTC),
        )

        result = Tasks._format_kicked_users_list({member})

        assert result == "• JohnDoe (JohnDoe#12345) - Joined: 2025-12-15"

    def test_format_kicked_users_list_multiple_users_sorted(self) -> None:
        """Test multiple users are sorted by join date (oldest first)"""
        # Create members with different join dates
        member1 = create_test_member(
            "NewMember",
            1111,
            joined_at=datetime.datetime(2025, 12, 15, tzinfo=datetime.UTC),  # Newest
        )
        member2 = create_test_member(
            "OldMember",
            2222,
            joined_at=datetime.datetime(2025, 12, 10, tzinfo=datetime.UTC),  # Oldest
        )
        member3 = create_test_member(
            "MidMember",
            3333,
            joined_at=datetime.datetime(2025, 12, 12, tzinfo=datetime.UTC),  # Middle
        )

        result = Tasks._format_kicked_users_list({member1, member2, member3})

        lines = result.split("\n")
        assert len(lines) == 3
        # Verify oldest is first
        assert "OldMember" in lines[0]
        assert "2025-12-10" in lines[0]
        # Verify middle is second
        assert "MidMember" in lines[1]
        assert "2025-12-12" in lines[1]
        # Verify newest is last
        assert "NewMember" in lines[2]
        assert "2025-12-15" in lines[2]

    def test_format_kicked_users_list_none_joined_at(self) -> None:
        """Test user with None joined_at shows 'Unknown'"""
        member = create_test_member("NoDateMember", 9999, joined_at=None)

        result = Tasks._format_kicked_users_list({member})

        assert "NoDateMember" in result
        assert "Joined: Unknown" in result

    def test_format_kicked_users_list_none_joined_at_sorted_last(self) -> None:
        """Test users with None joined_at are sorted to the end"""
        member_with_date = create_test_member(
            "HasDate",
            1111,
            joined_at=datetime.datetime(2025, 12, 10, tzinfo=datetime.UTC),
        )
        member_no_date = create_test_member("NoDate", 2222, joined_at=None)

        result = Tasks._format_kicked_users_list({member_with_date, member_no_date})

        lines = result.split("\n")
        assert len(lines) == 2
        # Member with date should be first
        assert "HasDate" in lines[0]
        assert "2025-12-10" in lines[0]
        # Member without a date should be last
        assert "NoDate" in lines[1]
        assert "Unknown" in lines[1]

    def test_format_kicked_users_list_truncation(self) -> None:
        """Test a long list (25+ users) truncates correctly"""
        # Create 30 members with sequential dates
        members = set()
        for i in range(30):
            member = create_test_member(
                f"Member{i:02d}",
                10000 + i,
                joined_at=datetime.datetime(2025, 12, 1, 0, 0, 0, tzinfo=datetime.UTC)
                + datetime.timedelta(days=i),
            )
            members.add(member)

        result = Tasks._format_kicked_users_list(members)

        # Should be truncated
        assert "...and" in result
        assert "more" in result
        # Should not exceed 1024 chars
        assert len(result) <= 1024
        # Should still have the oldest members at the top
        assert "Member00" in result
        assert "2025-12-01" in result

    def test_format_kicked_users_list_respects_1024_limit(self) -> None:
        """Test output never exceeds the 1024-character limit"""
        # Create members with very long display names to stress the truncation
        members = set()
        for i in range(50):
            member = create_test_member(
                f"VeryLongDisplayNameForMember{i:02d}WithExtraCharacters",
                20000 + i,
                joined_at=datetime.datetime(2025, 11, 1, 0, 0, 0, tzinfo=datetime.UTC)
                + datetime.timedelta(days=i),
            )
            members.add(member)

        result = Tasks._format_kicked_users_list(members)

        # Must respect the 1024-character limit
        assert len(result) <= 1024
        # Should have a truncation message
        assert "...and" in result
        assert "more" in result

    def test_format_kicked_users_list_single_line_over_limit(self) -> None:
        """Test a single line that exceeds 1024 chars"""
        # Create a member with a very long display name that exceeds 1024 chars
        very_long_name = "X" * 1000  # 1000 char name
        member = create_test_member(
            very_long_name,
            99999,
            joined_at=datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC),
        )

        result = Tasks._format_kicked_users_list({member})

        # Should handle the single long line gracefully
        assert len(result) <= 1024
        # Should contain truncation since a single line is > 1024
        assert "...and" in result or len(result) <= 1024

    def test_format_kicked_users_list_truncation_doesnt_fit(self) -> None:
        """Test edge case where a truncation message itself doesn't fit"""
        # Create members with names that result in lines close to 51 chars each
        # Goal: get to ~1020 chars with accumulated lines, so truncation won't
        # fit
        members = set()
        # Create 1000 members - this will cause a truncation message like
        # "...and 980 more" which is long enough that it might not fit if
        # we're close to the limit
        for i in range(1000):
            # Use a name length that gets us close to the limit
            name = f"Member{i:04d}X" * 10  # Creates ~110 char names
            member = create_test_member(
                name,
                10000 + i,
                joined_at=datetime.datetime(2025, 11, 1, tzinfo=datetime.UTC)
                + datetime.timedelta(days=i % 365),
            )
            members.add(member)

        result = Tasks._format_kicked_users_list(members)

        # Should not exceed 1024 chars
        assert len(result) <= 1024
        # Should either have truncation or be cut off before it
        # (either way, should be <= 1024)
        assert len(result) > 0


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
            assert mock_start.call_count == 3

    @async_test
    async def test_cog_unload_safe_when_tasks_preempted(
        self,
        mocker: MockerFixture,
    ) -> None:
        """cog_unload does not AttributeError when loops were already running."""
        bot = mocker.MagicMock()
        with patch("discord.ext.tasks.Loop.start"):
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
                field_name = "Kicked Users"
                log_prefix = ""
        else:
            with (
                patch("lib.cogs.tasks.asyncio.sleep") as mock_sleep,
                caplog.at_level(logging.INFO),
            ):
                await tasks_cog.clean_channel_members_task_dry_run()
                event_name = "Task - 🧹 Member Cleanup (DRY_RUN)"
                field_name = "Kicked Users (DRY_RUN)"
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

        # Verify log_bot_event was called with the correct parameters
        mock_log_bot_event.assert_called_once()
        call_kwargs = mock_log_bot_event.call_args.kwargs

        # Verify basic parameters
        assert call_kwargs["event"] == event_name
        assert f"{member_count} members" in call_kwargs["details"]

        # Verify extra_embed_fields parameter
        assert "extra_embed_fields" in call_kwargs
        extra_fields = call_kwargs["extra_embed_fields"]
        assert len(extra_fields) == 1

        field = extra_fields[0]
        assert field["name"] == field_name
        assert field["inline"] is False

        # Verify field value contains a formatted user list
        if member_count == 0:
            assert field["value"] == "None"
        else:
            # Should contain member information
            for member in members:
                assert member.display_name in field["value"]

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
        mocker: MockerFixture,
    ) -> None:
        """Test that logging for a member with no join date shows 'Unknown'"""
        mock_sunday = datetime.datetime(
            2023, 1, 8, 17, 0, 0, tzinfo=mock_config.TIMEZONE
        )

        # Create a member with no joined_at date
        member = create_test_member("MemberNoDate", 1234, joined_at=None)

        tasks_cog._get_channel_members_to_kick = AsyncMock(return_value={member})
        mock_log_bot_event = mocker.patch.object(
            tasks_cog.bot, "log_bot_event", new=AsyncMock()
        )

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

        # Verify "Unknown" appears in the embed field
        mock_log_bot_event.assert_called_once()
        call_kwargs = mock_log_bot_event.call_args.kwargs
        assert "extra_embed_fields" in call_kwargs
        field_value = call_kwargs["extra_embed_fields"][0]["value"]
        assert "MemberNoDate" in field_value
        assert "Unknown" in field_value

    @async_test
    async def test_clean_channel_members_task_dry_run_member_no_join_date_logging(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
        mocker: MockerFixture,
    ) -> None:
        """Test dry run logging for a member with no join date shows 'Unknown'"""
        # Create a member with no joined_at date
        member = create_test_member("DryRunMemberNoDate", 1234, joined_at=None)

        tasks_cog._get_channel_members_to_kick = AsyncMock(return_value={member})
        mock_log_bot_event = mocker.patch.object(
            tasks_cog.bot, "log_bot_event", new=AsyncMock()
        )

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

        # Verify "Unknown" appears in the embed field
        mock_log_bot_event.assert_called_once()
        call_kwargs = mock_log_bot_event.call_args.kwargs
        assert "extra_embed_fields" in call_kwargs
        field_value = call_kwargs["extra_embed_fields"][0]["value"]
        assert "DryRunMemberNoDate" in field_value
        assert "Unknown" in field_value

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

        # noinspection SpellCheckingInspection
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

        # Verify channel send was called with an unwrapped @everyone mention
        mock_channel.send.assert_called_once_with(content="@everyone", embed=ANY)

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

        # Mock a channel as a wrong type (VoiceChannel)
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


class TestMonitorYoutubeVideosInitializationRetry:
    """Test cases for monitor_youtube_videos initialization retry logic"""

    @async_test
    async def test_monitor_youtube_videos_feed_not_initialized_retry_success(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test uninitialized feed with successful retry posts videos"""
        # Mock feed parser that starts uninitialized, then succeeds on retry
        video1 = FeedParserDict(
            {
                "id": "yt:video:abcdef123",
                "link": "https://www.youtube.com/watch?v=abcdef123",
                "yt_videoid": "abcdef123",
                "title": "Test Video",
                "author": "Test Author",
                "published": "2025-10-20T12:00:00+00:00",
                "summary": "Test Summary\nOther stuff",
            }
        )

        mock_feed_parser = MagicMock()
        # Mock property that changes from False to True after retry
        mock_feed_parser.is_initialized = False

        def mock_retry() -> bool:
            mock_feed_parser.is_initialized = True
            return True

        mock_feed_parser.retry_initialization = mock_retry
        mock_feed_parser.get_new_videos.return_value = [video1]
        mock_feed_parser.get_thumbnail_from_entry.return_value = (
            "https://example.com/thumb.jpg"
        )

        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        mock_channel = MagicMock(spec=discord.TextChannel)
        tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.INFO):
            await tasks_cog.monitor_youtube_videos()

        # Verify retry was attempted (can't assert_called_once - it's a function)
        # The fact that the video was posted means retry succeeded

        # Verify videos were posted
        mock_channel.send.assert_called_once()

        # Verify logging
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "Feed test_feed is not initialized, retrying initialization" in r.message
            for r in warning_records
        )
        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert any(
            "Feed test_feed initialization succeeded" in r.message for r in info_records
        )

    @async_test
    async def test_monitor_youtube_videos_feed_not_initialized_retry_fails(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test uninitialized feed with failed retry skips posting"""
        # Mock feed parser that is uninitialized and retry fails
        mock_feed_parser = MagicMock()
        mock_feed_parser.is_initialized = False
        mock_feed_parser.retry_initialization.return_value = False

        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}

        mock_channel = MagicMock(spec=discord.TextChannel)
        tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        # Verify retry was attempted
        mock_feed_parser.retry_initialization.assert_called_once()

        # Verify get_new_videos was NOT called
        mock_feed_parser.get_new_videos.assert_not_called()

        # Verify nothing was posted
        mock_channel.send.assert_not_called()

        # Verify logging
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "Feed test_feed is not initialized, retrying initialization" in r.message
            for r in warning_records
        )
        assert any(
            "Feed test_feed initialization failed, skipping this run" in r.message
            for r in warning_records
        )

    @async_test
    async def test_monitor_youtube_videos_feed_not_initialized_retry_success_logs(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test correct warning and info logs during successful retry"""
        mock_feed_parser = MagicMock()
        mock_feed_parser.is_initialized = False

        def mock_retry() -> bool:
            mock_feed_parser.is_initialized = True
            return True

        mock_feed_parser.retry_initialization = mock_retry
        mock_feed_parser.get_new_videos.return_value = []

        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}
        tasks_cog.bot.get_channel = MagicMock()
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.INFO):
            await tasks_cog.monitor_youtube_videos()

        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert (
            "Feed test_feed is not initialized, retrying initialization"
            in warning_records[0].message
        )

        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert any(
            "Feed test_feed initialization succeeded" in r.message for r in info_records
        )

    @async_test
    async def test_monitor_youtube_videos_feed_not_initialized_retry_fails_logs(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test correct warning logs when retry fails"""
        mock_feed_parser = MagicMock()
        mock_feed_parser.is_initialized = False
        mock_feed_parser.retry_initialization.return_value = False

        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}
        tasks_cog.bot.get_channel = MagicMock()
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 2
        assert (
            "Feed test_feed is not initialized, retrying initialization"
            in warning_records[0].message
        )
        assert (
            "Feed test_feed initialization failed, skipping this run"
            in warning_records[1].message
        )

    @async_test
    async def test_monitor_youtube_videos_multiple_feeds_one_uninitialized(
        self,
        caplog: pytest.LogCaptureFixture,
        tasks_cog: Tasks,
    ) -> None:
        """Test multiple feeds where one is uninitialized"""
        # Initialized feed with videos
        video1 = FeedParserDict(
            {
                "id": "yt:video:initialized_video",
                "link": "https://www.youtube.com/watch?v=init",
                "yt_videoid": "init",
                "title": "Initialized Video",
                "author": "Test Author",
                "published": "2025-10-20T12:00:00+00:00",
                "summary": "Test Summary",
            }
        )
        mock_feed_initialized = MagicMock()
        mock_feed_initialized.is_initialized = True
        mock_feed_initialized.get_new_videos.return_value = [video1]
        mock_feed_initialized.get_thumbnail_from_entry.return_value = (
            "https://example.com/thumb.jpg"
        )

        # Uninitialized feed
        mock_feed_uninitialized = MagicMock()
        mock_feed_uninitialized.is_initialized = False
        mock_feed_uninitialized.retry_initialization.return_value = False

        tasks_cog.youtube_feeds = {
            "initialized_feed": mock_feed_initialized,
            "uninitialized_feed": mock_feed_uninitialized,
        }

        mock_channel = MagicMock(spec=discord.TextChannel)
        tasks_cog.bot.get_channel = MagicMock(return_value=mock_channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_youtube_videos()

        # Initialized feed should post video
        mock_feed_initialized.get_new_videos.assert_called_once()
        mock_channel.send.assert_called_once()

        # Uninitialized feed should retry and skip
        mock_feed_uninitialized.retry_initialization.assert_called_once()
        mock_feed_uninitialized.get_new_videos.assert_not_called()

    @async_test
    async def test_monitor_youtube_videos_feed_initialized_skips_retry(
        self,
        tasks_cog: Tasks,
    ) -> None:
        """Test initialized feed skips retry logic"""
        mock_feed_parser = MagicMock()
        mock_feed_parser.is_initialized = True
        mock_feed_parser.get_new_videos.return_value = []

        tasks_cog.youtube_feeds = {"test_feed": mock_feed_parser}
        tasks_cog.bot.get_channel = MagicMock()
        tasks_cog.bot.log_bot_event = AsyncMock()

        await tasks_cog.monitor_youtube_videos()

        # Verify retry_initialization was never called
        mock_feed_parser.retry_initialization.assert_not_called()

        # Verify get_new_videos was called
        mock_feed_parser.get_new_videos.assert_called_once()


def _gh_event(
    kind: str = "PR_MERGED",
    number: int = 42,
    *,
    title: str = "Fix things",
    url: str = "https://github.com/JamesTurland/JimsGarage/pull/42",
    author_login: str = "octocat",
    author_avatar_url: str = "https://avatars/1",
    is_pr: bool = True,
    closer_login: str = "",
    closer_avatar_url: str = "",
    linked_issues: tuple[GitHubActivityEvent, ...] = (),
) -> GitHubActivityEvent:
    """Build a GitHubActivityEvent for cog/embed tests."""
    return GitHubActivityEvent(
        key=f"{kind}:{number}",
        kind=kind,
        number=number,
        title=title,
        url=url,
        author_login=author_login,
        author_avatar_url=author_avatar_url,
        is_pr=is_pr,
        closer_login=closer_login,
        closer_avatar_url=closer_avatar_url,
        linked_issues=linked_issues,
    )


class TestGitHubMonitor:
    """Tests for the monitor_github_activity task."""

    @async_test
    async def test_posts_to_github_channel(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        mock_config.DRY_RUN_GITHUB = False
        monitor = MagicMock()
        monitor.get_new_events = AsyncMock(return_value=[_gh_event()])
        tasks_cog.github_monitor = monitor
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        tasks_cog.bot.get_channel = MagicMock(return_value=channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        await tasks_cog.monitor_github_activity()

        tasks_cog.bot.get_channel.assert_called_with(mock_config.CHANNELS.GITHUB)
        channel.send.assert_called_once()
        assert "embed" in channel.send.call_args.kwargs
        assert "content" not in channel.send.call_args.kwargs

    @async_test
    async def test_dry_run_posts_to_playground(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        mock_config.DRY_RUN_GITHUB = True
        monitor = MagicMock()
        monitor.get_new_events = AsyncMock(return_value=[_gh_event()])
        tasks_cog.github_monitor = monitor
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        tasks_cog.bot.get_channel = MagicMock(return_value=channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        await tasks_cog.monitor_github_activity()

        tasks_cog.bot.get_channel.assert_called_with(
            mock_config.CHANNELS.BOT_PLAYGROUND
        )

    @async_test
    async def test_no_events_skips(self, tasks_cog: Tasks) -> None:
        monitor = MagicMock()
        monitor.get_new_events = AsyncMock(return_value=[])
        tasks_cog.github_monitor = monitor
        tasks_cog.bot.get_channel = MagicMock()

        await tasks_cog.monitor_github_activity()

        tasks_cog.bot.get_channel.assert_not_called()

    @async_test
    async def test_monitor_none_skips(
        self, tasks_cog: Tasks, caplog: pytest.LogCaptureFixture
    ) -> None:
        tasks_cog.github_monitor = None
        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_github_activity()
        assert any("not initialized" in r.message for r in caplog.records)

    @async_test
    async def test_channel_missing_logs_warning(
        self, tasks_cog: Tasks, caplog: pytest.LogCaptureFixture
    ) -> None:
        monitor = MagicMock()
        monitor.get_new_events = AsyncMock(return_value=[_gh_event()])
        tasks_cog.github_monitor = monitor
        tasks_cog.bot.get_channel = MagicMock(return_value=None)
        tasks_cog.bot.log_bot_event = AsyncMock()
        with caplog.at_level(logging.WARNING):
            await tasks_cog.monitor_github_activity()
        assert any("not found" in r.message for r in caplog.records)

    def test_build_embed_plain(self, tasks_cog: Tasks) -> None:
        embed = tasks_cog._build_github_embed(_gh_event())
        assert embed.title == "🟣 PR merged #42"
        assert embed.color is not None
        assert embed.color.value == 0x9B59B6

    def test_build_embed_with_linked_issues(self, tasks_cog: Tasks) -> None:
        linked = _gh_event(
            kind="ISSUE_COMPLETED",
            number=40,
            title="Broken",
            url="https://github.com/JamesTurland/JimsGarage/issues/40",
            is_pr=False,
        )
        event = _gh_event(linked_issues=(linked,))
        embed = tasks_cog._build_github_embed(event)
        assert any(f.name == "Closed issues" for f in embed.fields)

    def test_build_embed_no_avatar(self, tasks_cog: Tasks) -> None:
        embed = tasks_cog._build_github_embed(_gh_event(author_avatar_url=""))
        assert embed.thumbnail.url is None

    def test_build_embed_close_shows_handoff(self, tasks_cog: Tasks) -> None:
        event = _gh_event(
            author_login="opener",
            closer_login="closer",
            closer_avatar_url="https://avatars/2",
        )
        embed = tasks_cog._build_github_embed(event)
        assert embed.author.name == "opener → closer"
        assert embed.thumbnail.url == "https://avatars/2"

    def test_build_embed_open_unchanged(self, tasks_cog: Tasks) -> None:
        event = _gh_event(
            kind="ISSUE_OPENED",
            is_pr=False,
            author_login="opener",
            author_avatar_url="https://avatars/1",
        )
        embed = tasks_cog._build_github_embed(event)
        assert embed.author.name == "opener"
        assert embed.thumbnail.url == "https://avatars/1"

    def test_build_embed_self_close(self, tasks_cog: Tasks) -> None:
        event = _gh_event(author_login="cyberops7", closer_login="cyberops7")
        embed = tasks_cog._build_github_embed(event)
        assert embed.author.name == "cyberops7 → cyberops7"

    def test_build_embed_unknown_closer_falls_back(self, tasks_cog: Tasks) -> None:
        event = _gh_event(
            author_login="opener",
            author_avatar_url="https://avatars/1",
            closer_login="",
            closer_avatar_url="",
        )
        embed = tasks_cog._build_github_embed(event)
        assert embed.author.name == "opener → unknown"
        assert embed.thumbnail.url == "https://avatars/1"

    def test_build_embed_bot_closer_rendered_as_is(self, tasks_cog: Tasks) -> None:
        event = _gh_event(author_login="opener", closer_login="github-actions[bot]")
        embed = tasks_cog._build_github_embed(event)
        assert embed.author.name == "opener → github-actions[bot]"

    def test_build_embed_deleted_opener(self, tasks_cog: Tasks) -> None:
        event = _gh_event(author_login="", closer_login="closer")
        embed = tasks_cog._build_github_embed(event)
        assert embed.author.name == "unknown → closer"

    @async_test
    async def test_before_loop_initializes_and_smoke_posts(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        mock_config.DRY_RUN_GITHUB = True
        fake_monitor = MagicMock()
        fake_monitor.start_session = AsyncMock()
        fake_monitor.get_latest_activity = AsyncMock(return_value=_gh_event())
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        tasks_cog.bot.get_channel = MagicMock(return_value=channel)
        tasks_cog.bot.wait_until_ready = AsyncMock()
        tasks_cog.monitor_github_activity.change_interval = MagicMock()

        with patch("lib.github.GitHubMonitor", return_value=fake_monitor):
            await tasks_cog.before_monitor_github_activity()

        fake_monitor.start_session.assert_awaited_once()
        tasks_cog.monitor_github_activity.change_interval.assert_called_once_with(
            minutes=mock_config.GITHUB.POLL_MINUTES
        )
        channel.send.assert_called_once()

    @async_test
    async def test_before_loop_smoke_post_no_activity(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        mock_config.DRY_RUN_GITHUB = True
        fake_monitor = MagicMock()
        fake_monitor.start_session = AsyncMock()
        fake_monitor.get_latest_activity = AsyncMock(return_value=None)
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        tasks_cog.bot.get_channel = MagicMock(return_value=channel)
        tasks_cog.bot.wait_until_ready = AsyncMock()
        tasks_cog.monitor_github_activity.change_interval = MagicMock()

        with patch("lib.github.GitHubMonitor", return_value=fake_monitor):
            await tasks_cog.before_monitor_github_activity()

        channel.send.assert_not_called()

    def test_already_running_warns(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        with patch("discord.ext.tasks.Loop.start"), caplog.at_level(logging.WARNING):
            cog = Tasks(discord_bot)
            with patch.object(cog, "monitor_github_activity") as mock_task:
                mock_task.is_running.return_value = True
                Tasks.__init__(cog, discord_bot)
        assert any(
            "monitor_github_activity task is already running" in r.message
            for r in caplog.records
        )

    @async_test
    async def test_cog_unload_closes_github_session(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
    ) -> None:
        """Test cog_unload closes the github_monitor session when not None."""
        mock_config.DRY_RUN = False
        mock_monitor = MagicMock()
        mock_monitor.close_session = AsyncMock()
        tasks_cog.github_monitor = mock_monitor

        await tasks_cog.cog_unload()

        tasks_cog.monitor_github_activity.cancel.assert_called_once()  # pyrefly: ignore
        mock_monitor.close_session.assert_awaited_once()

    @async_test
    async def test_before_loop_no_dry_run(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        """Test before_monitor_github_activity when DRY_RUN_GITHUB=False."""
        mock_config.DRY_RUN_GITHUB = False
        fake_monitor = MagicMock()
        fake_monitor.start_session = AsyncMock()
        tasks_cog.bot.get_channel = MagicMock()
        tasks_cog.bot.wait_until_ready = AsyncMock()
        tasks_cog.monitor_github_activity.change_interval = MagicMock()

        with patch("lib.github.GitHubMonitor", return_value=fake_monitor):
            await tasks_cog.before_monitor_github_activity()

        fake_monitor.start_session.assert_awaited_once()
        # No channel posting in non-dry-run mode
        tasks_cog.bot.get_channel.assert_not_called()

    @async_test
    async def test_before_loop_dry_run_invalid_channel(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        """Test before_monitor_github_activity when channel is not TextChannel."""
        mock_config.DRY_RUN_GITHUB = True
        fake_monitor = MagicMock()
        fake_monitor.start_session = AsyncMock()
        fake_monitor.get_latest_activity = AsyncMock(return_value=_gh_event())
        # Return a non-TextChannel (plain MagicMock has no TextChannel spec)
        tasks_cog.bot.get_channel = MagicMock(return_value=MagicMock())
        tasks_cog.bot.wait_until_ready = AsyncMock()
        tasks_cog.monitor_github_activity.change_interval = MagicMock()

        with patch("lib.github.GitHubMonitor", return_value=fake_monitor):
            await tasks_cog.before_monitor_github_activity()

        # get_latest_activity should NOT be called when channel is invalid
        fake_monitor.get_latest_activity.assert_not_called()

    def test_build_embed_linked_issues_truncated(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        """Verify the Closed issues field is capped at EMBED_MAX_LENGTH chars."""
        long_title = "A" * 200
        linked_issues = tuple(
            _gh_event(
                kind="ISSUE_COMPLETED",
                number=i,
                title=long_title,
                url=f"https://github.com/JamesTurland/JimsGarage/issues/{i}",
                is_pr=False,
            )
            for i in range(1, 7)
        )
        event = _gh_event(linked_issues=linked_issues)
        embed = tasks_cog._build_github_embed(event)
        field = next(f for f in embed.fields if f.name == "Closed issues")
        assert field.value is not None
        assert len(field.value) <= mock_config.EMBED_MAX_LENGTH
        assert "more" in field.value

    def test_build_embed_linked_issues_tail_no_fit(
        self, tasks_cog: Tasks, mock_config: MagicMock
    ) -> None:
        """Verify graceful truncation when even the tail line doesn't fit."""
        # Construct a first issue whose single formatted line is exactly
        # EMBED_MAX_LENGTH chars, so the tail cannot be appended when the
        # second issue would overflow.
        url = "https://github.com/JamesTurland/JimsGarage/issues/1"
        prefix_len = len(f"• [#1]({url}) ")
        title = "B" * (mock_config.EMBED_MAX_LENGTH - prefix_len)
        issue1 = _gh_event(
            kind="ISSUE_COMPLETED", number=1, title=title, url=url, is_pr=False
        )
        issue2 = _gh_event(
            kind="ISSUE_COMPLETED",
            number=2,
            title="Short",
            url="https://github.com/JamesTurland/JimsGarage/issues/2",
            is_pr=False,
        )
        event = _gh_event(linked_issues=(issue1, issue2))
        embed = tasks_cog._build_github_embed(event)
        field = next(f for f in embed.fields if f.name == "Closed issues")
        # Field must still respect the length limit even without a tail
        assert field.value is not None
        assert len(field.value) <= mock_config.EMBED_MAX_LENGTH
        assert "more" not in field.value

    @async_test
    async def test_monitor_github_activity_send_failure_logs_and_continues(
        self,
        tasks_cog: Tasks,
        mock_config: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A discord.HTTPException during send is caught, logged, and skipped."""
        mock_config.DRY_RUN_GITHUB = False
        monitor = MagicMock()
        monitor.get_new_events = AsyncMock(return_value=[_gh_event()])
        tasks_cog.github_monitor = monitor
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))
        tasks_cog.bot.get_channel = MagicMock(return_value=channel)
        tasks_cog.bot.log_bot_event = AsyncMock()

        with caplog.at_level(logging.ERROR):
            await tasks_cog.monitor_github_activity()

        error_records = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any(
            "Failed to send GitHub embed for #42" in r.message for r in error_records
        )
