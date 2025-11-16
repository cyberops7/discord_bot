"""Unit tests for the youtube.py module"""

import socket
import urllib.error
from collections.abc import Generator
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest
from feedparser.util import FeedParserDict

from lib.youtube import YoutubeFeedParser


@pytest.fixture
def mock_feed_url() -> str:
    """Mock YouTube RSS feed URL"""
    return "https://www.youtube.com/feeds/videos.xml?channel_id=TEST_CHANNEL_ID"


@pytest.fixture
def mock_feed_name() -> str:
    """Mock feed name"""
    return "Test Channel"


@pytest.fixture
def mock_feed_entry() -> FeedParserDict:
    """Mock feedparser entry"""
    entry = FeedParserDict()
    entry.id = "yt:video:abcdef123"
    entry.yt_videoid = ("abcdef123",)
    entry.link = "https://www.youtube.com/watch?v=TEST_VIDEO_ID"
    entry.title = "Test Video Title"
    entry.published = "2025-01-01T00:00:00+00:00"
    entry.published_parsed = (2025, 1, 1, 0, 0, 0, 0, 1, 0)
    entry.summary = "Test video summary"
    entry.author = "Test Author"
    return entry


@pytest.fixture
def mock_feed_with_entries(mock_feed_entry: FeedParserDict) -> MagicMock:
    """Mock feedparser feed with entries"""
    feed = MagicMock()
    feed.bozo = False
    feed.entries = [mock_feed_entry]
    return feed


@pytest.fixture
def mock_empty_feed() -> MagicMock:
    """Mock empty feedparser feed"""
    feed = MagicMock()
    feed.bozo = False
    feed.entries = []
    return feed


@pytest.fixture
def youtube_parser_no_init(
    mock_feed_name: str, mock_feed_url: str
) -> Generator[YoutubeFeedParser, None, None]:  # noqa: UP043 unnecessary default type args
    """YoutubeFeedParser fixture with initialization mocked"""
    with patch.object(YoutubeFeedParser, "_initialize_seen_videos", return_value=set()):
        parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
        yield parser


class TestYoutubeFeedParserInit:
    """Tests for YoutubeFeedParser initialization"""

    def test_init_stores_feed_name_and_url(
        self,
        mock_feed_name: str,
        mock_feed_url: str,
        youtube_parser_no_init: YoutubeFeedParser,
    ) -> None:
        """Test that __init__ stores feed_name and feed_url"""
        assert youtube_parser_no_init.feed_name == mock_feed_name
        assert youtube_parser_no_init.feed_url == mock_feed_url

    def test_init_initializes_seen_videos(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
    ) -> None:
        """Test that __init__ initializes seen_videos set"""
        assert isinstance(youtube_parser_no_init.seen_videos, set)

    def test_init_calls_initialize_seen_videos(
        self, mock_feed_name: str, mock_feed_url: str
    ) -> None:
        """Test that __init__ calls _initialize_seen_videos"""
        with patch.object(
            YoutubeFeedParser,
            "_initialize_seen_videos",
            return_value={"video1", "video2"},
        ) as mock_init:
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            mock_init.assert_called_once()
            assert parser.seen_videos == {"video1", "video2"}


class TestGetThumbnailFromEntry:
    """Tests for the get_thumbnail_from_entry method"""

    def test_get_thumbnail_from_entry(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_entry: FeedParserDict,
    ) -> None:
        """Test getting thumbnail from entry"""
        result = youtube_parser_no_init.get_thumbnail_from_entry(mock_feed_entry)
        assert (
            result
            == f"https://img.youtube.com/vi/{mock_feed_entry.yt_videoid}/maxresdefault.jpg"
        )

    def test_get_thumbnail_from_entry_missing_video_id(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
    ) -> None:
        """Test failed thumbnail generation"""
        # Create a fresh entry without yt_videoid to avoid fixture pollution
        entry = FeedParserDict()
        entry.id = "yt:video:abcdef123"
        entry.link = "https://www.youtube.com/watch?v=TEST_VIDEO_ID"
        entry.title = "Test Video Title"
        entry.published = "2025-01-01T00:00:00+00:00"
        entry.published_parsed = (2025, 1, 1, 0, 0, 0, 0, 1, 0)
        entry.summary = "Test video summary"
        entry.author = "Test Author"
        # Deliberately not setting yt_videoid

        # Mock the logger to capture the warning call directly
        with patch("lib.youtube.logger") as mock_logger:
            result = youtube_parser_no_init.get_thumbnail_from_entry(entry)

            # Verify the method was called and the warning was logged
            assert result is None
            mock_logger.warning.assert_called_once()

            # Get the call arguments to verify the message
            call_args = mock_logger.warning.call_args
            assert "Could not extract video ID from entry" in call_args[0][0]


class TestInitializeSeenVideos:
    """Tests for _initialize_seen_videos method"""

    def test_initialize_seen_videos_real_config(self) -> None:
        """Test initialization with a real config file"""
        from lib.config import config  # noqa: PLC0415 imports at the top of the file

        for feed_name, feed_url in config.YOUTUBE_FEEDS.items():
            parser = YoutubeFeedParser(feed_name, feed_url)
            assert len(parser.seen_videos) > 0

    def test_initialize_seen_videos_success(
        self,
        mock_feed_name: str,
        mock_feed_url: str,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test successful initialization of seen videos"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert mock_feed_with_entries.entries[0].id in parser.seen_videos
            assert len(parser.seen_videos) == 1

    def test_initialize_seen_videos_empty_feed(
        self, mock_feed_name: str, mock_feed_url: str, mock_empty_feed: MagicMock
    ) -> None:
        """Test initialization with an empty feed"""
        with patch("feedparser.parse", return_value=mock_empty_feed):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0

    def test_initialize_seen_videos_bozo_feed(
        self, mock_feed_name: str, mock_feed_url: str, mock_empty_feed: MagicMock
    ) -> None:
        """Test initialization with a malformed feed (bozo=True)"""
        mock_empty_feed.bozo = True
        mock_empty_feed.bozo_exception = Exception("Feed parse error")
        with patch("feedparser.parse", return_value=mock_empty_feed):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0

    def test_initialize_seen_videos_url_error(
        self, mock_feed_name: str, mock_feed_url: str
    ) -> None:
        """Test initialization handles URLError"""
        with patch(
            "feedparser.parse", side_effect=urllib.error.URLError("Network error")
        ):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0

    def test_initialize_seen_videos_http_error(
        self, mock_feed_name: str, mock_feed_url: str
    ) -> None:
        """Test initialization handles HTTPError"""
        with patch(
            "feedparser.parse",
            side_effect=urllib.error.HTTPError(
                "url", 404, "Not Found", EmailMessage(), None
            ),
        ):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0

    def test_initialize_seen_videos_timeout_error(
        self, mock_feed_name: str, mock_feed_url: str
    ) -> None:
        """Test initialization handles TimeoutError"""
        with patch("feedparser.parse", side_effect=TimeoutError("Timeout")):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0

    def test_initialize_seen_videos_socket_gaierror(
        self, mock_feed_name: str, mock_feed_url: str
    ) -> None:
        """Test initialization handles socket.gaierror"""
        with patch("feedparser.parse", side_effect=socket.gaierror("DNS error")):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0

    def test_initialize_seen_videos_connection_reset(
        self, mock_feed_name: str, mock_feed_url: str
    ) -> None:
        """Test initialization handles ConnectionResetError"""
        with patch(
            "feedparser.parse", side_effect=ConnectionResetError("Connection reset")
        ):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert len(parser.seen_videos) == 0


class TestGetLatestVideo:
    """Tests for get_latest_video method"""

    def test_get_latest_video(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test getting the latest video from feed"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_latest_video()
            assert result == mock_feed_with_entries.entries[0]


class TestGetNewVideos:
    """Tests for get_new_videos method"""

    def test_get_new_videos_new_video(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test parsing feed with new video"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result.id == mock_feed_with_entries.entries[0].id
            assert video_result.title == mock_feed_with_entries.entries[0].title
            assert video_result.link == mock_feed_with_entries.entries[0].link
            assert video_result.published == mock_feed_with_entries.entries[0].published
            assert video_result.summary == mock_feed_with_entries.entries[0].summary
            assert video_result.author == mock_feed_with_entries.entries[0].author
            assert (
                mock_feed_with_entries.entries[0].id
                in youtube_parser_no_init.seen_videos
            )

    def test_get_new_videos_already_seen_video(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test parsing feed with already seen video"""
        youtube_parser_no_init.seen_videos.add("yt:video:abcdef123")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_empty(
        self, youtube_parser_no_init: YoutubeFeedParser, mock_empty_feed: MagicMock
    ) -> None:
        """Test parsing empty feed"""
        with patch("feedparser.parse", return_value=mock_empty_feed):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_bozo(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test parsing feed with the bozo flag set"""
        mock_feed_with_entries.bozo = True
        mock_feed_with_entries.bozo_exception = Exception("Parse error")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 1  # Still processes entries despite bozo

    def test_get_new_videos_entry_without_summary(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
        mock_feed_entry: FeedParserDict,
    ) -> None:
        """Test parsing entry without `summary` attribute"""
        delattr(mock_feed_entry, "summary")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert getattr(video_result, "summary", "") == ""

    def test_get_new_videos_entry_without_author(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
        mock_feed_entry: FeedParserDict,
    ) -> None:
        """Test parsing entry without `author` attribute"""
        delattr(mock_feed_entry, "author")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert getattr(video_result, "author", "") == ""

    def test_get_new_videos_url_error(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test get_new_videos handles URLError"""
        with patch(
            "feedparser.parse", side_effect=urllib.error.URLError("Network error")
        ):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_http_error(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test get_new_videos handles HTTPError"""
        with patch(
            "feedparser.parse",
            side_effect=urllib.error.HTTPError(
                "url", 404, "Not Found", EmailMessage(), None
            ),
        ):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_timeout_error(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test get_new_videos handles TimeoutError"""
        with patch("feedparser.parse", side_effect=TimeoutError("Timeout")):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_socket_gaierror(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test get_new_videos handles socket.gaierror"""
        with patch("feedparser.parse", side_effect=socket.gaierror("DNS error")):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_connection_reset(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test get_new_videos handles ConnectionResetError"""
        with patch(
            "feedparser.parse", side_effect=ConnectionResetError("Connection reset")
        ):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0

    def test_get_new_videos_multiple_videos(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parsing feed with multiple new videos"""
        entry1 = FeedParserDict()
        entry1.id = "VIDEO_1"
        entry1.link = "https://www.youtube.com/watch?v=VIDEO_1"
        entry1.title = "Video 1"
        entry1.published = "2025-01-01T00:00:00+00:00"
        entry1.published_parsed = (2025, 1, 1, 0, 0, 0, 0, 1, 0)

        entry2 = FeedParserDict()
        entry2.id = "VIDEO_2"
        entry2.link = "https://www.youtube.com/watch?v=VIDEO_2"
        entry2.title = "Video 2"
        entry2.published = "2025-01-02T00:00:00+00:00"
        entry2.published_parsed = (2025, 1, 2, 0, 0, 0, 0, 1, 0)

        feed = MagicMock(spec=FeedParserDict)
        feed.bozo = False
        feed.entries = [entry1, entry2]

        with patch("feedparser.parse", return_value=feed):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 2
            video_result = result[0]
            assert video_result is not None
            assert video_result.id == "VIDEO_1"
            video_result = result[1]
            assert video_result is not None
            assert video_result.id == "VIDEO_2"
            assert "VIDEO_1" in youtube_parser_no_init.seen_videos
            assert "VIDEO_2" in youtube_parser_no_init.seen_videos

    def test_get_new_videos_includes_published_parsed(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test that get_new_videos includes published_parsed in the result"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result.published_parsed == (
                2025,
                1,
                1,
                0,
                0,
                0,
                0,
                1,
                0,
            )

    def test_get_new_videos_entry_without_id(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
        mock_feed_entry: FeedParserDict,
    ) -> None:
        """Test parsing entry without `id` attribute"""
        delattr(mock_feed_entry, "id")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.get_new_videos()
            assert len(result) == 0
