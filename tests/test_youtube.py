"""Unit tests for the youtube.py module"""

import socket
import urllib.error
from collections.abc import Generator
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import feedparser
import pytest

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
def mock_feed_entry() -> feedparser.FeedParserDict:
    """Mock feedparser entry"""
    entry = feedparser.FeedParserDict()
    entry.link = "https://www.youtube.com/watch?v=TEST_VIDEO_ID"
    entry.title = "Test Video Title"
    entry.published = "2025-01-01T00:00:00+00:00"
    entry.published_parsed = (2025, 1, 1, 0, 0, 0, 0, 1, 0)
    entry.summary = "Test video summary"
    entry.author = "Test Author"
    return entry


@pytest.fixture
def mock_feed_with_entries(mock_feed_entry: feedparser.FeedParserDict) -> MagicMock:
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


class TestExtractVideoIdFromUrl:
    """Tests for extract_video_id_from_url static method"""

    def test_extract_video_id_simple_url(self) -> None:
        """Test extracting video ID from a simple YouTube URL"""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = YoutubeFeedParser.extract_video_id_from_url(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_url_with_parameters(self) -> None:
        """Test extracting video ID from URL with additional parameters"""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share&t=42"
        result = YoutubeFeedParser.extract_video_id_from_url(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_no_watch_param(self) -> None:
        """Test that URL without watch?v= returns the original URL"""
        url = "https://youtu.be/dQw4w9WgXcQ"
        result = YoutubeFeedParser.extract_video_id_from_url(url)
        assert result == url


class TestInitializeSeenVideos:
    """Tests for _initialize_seen_videos method"""

    def test_initialize_seen_videos_success(
        self,
        mock_feed_name: str,
        mock_feed_url: str,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test successful initialization of seen videos"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            parser = YoutubeFeedParser(mock_feed_name, mock_feed_url)
            assert "TEST_VIDEO_ID" in parser.seen_videos
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


class TestGetThumbnailFromEntry:
    """Tests for the get_thumbnail_from_entry method"""

    def test_get_thumbnail_from_media_thumbnail(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test getting thumbnail from media_thumbnail attribute"""
        mock_feed_entry.media_thumbnail = [{"url": "https://example.com/thumbnail.jpg"}]
        result = youtube_parser_no_init.get_thumbnail_from_entry(mock_feed_entry)
        assert result == "https://example.com/thumbnail.jpg"

    def test_get_thumbnail_from_media_content(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test getting thumbnail from media_content attribute"""
        mock_feed_entry.media_content = [
            {"type": "image/jpeg", "url": "https://example.com/image.jpg"}
        ]
        result = youtube_parser_no_init.get_thumbnail_from_entry(mock_feed_entry)
        assert result == "https://example.com/image.jpg"

    def test_get_thumbnail_from_media_content_non_image(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test that media_content with a non-image type falls back to video ID"""
        mock_feed_entry.media_content = [
            {"type": "video/mp4", "url": "https://example.com/video.mp4"}
        ]
        result = youtube_parser_no_init.get_thumbnail_from_entry(mock_feed_entry)
        assert result == "https://img.youtube.com/vi/TEST_VIDEO_ID/maxresdefault.jpg"

    def test_get_thumbnail_from_media_content_no_type(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test media_content without a `type` field falls back to video ID"""
        mock_feed_entry.media_content = [{"url": "https://example.com/content.dat"}]
        result = youtube_parser_no_init.get_thumbnail_from_entry(mock_feed_entry)
        assert result == "https://img.youtube.com/vi/TEST_VIDEO_ID/maxresdefault.jpg"

    def test_get_thumbnail_fallback_to_video_id(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test fallback to constructing thumbnail from video ID"""
        result = youtube_parser_no_init.get_thumbnail_from_entry(mock_feed_entry)
        assert result == "https://img.youtube.com/vi/TEST_VIDEO_ID/maxresdefault.jpg"


class TestParseRssFeed:
    """Tests for parse_rss_feed method"""

    def test_parse_rss_feed_new_video(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test parsing feed with new video"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result["id"] == "TEST_VIDEO_ID"
            assert video_result["title"] == mock_feed_with_entries.entries[0].title
            assert video_result["link"] == mock_feed_with_entries.entries[0].link
            assert (
                video_result["published"] == mock_feed_with_entries.entries[0].published
            )
            assert video_result["summary"] == mock_feed_with_entries.entries[0].summary
            assert video_result["author"] == mock_feed_with_entries.entries[0].author
            assert "TEST_VIDEO_ID" in youtube_parser_no_init.seen_videos

    def test_parse_rss_feed_already_seen_video(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test parsing feed with already seen video"""
        youtube_parser_no_init.seen_videos.add("TEST_VIDEO_ID")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_empty(
        self, youtube_parser_no_init: YoutubeFeedParser, mock_empty_feed: MagicMock
    ) -> None:
        """Test parsing empty feed"""
        with patch("feedparser.parse", return_value=mock_empty_feed):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_bozo(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test parsing feed with the bozo flag set"""
        mock_feed_with_entries.bozo = True
        mock_feed_with_entries.bozo_exception = Exception("Parse error")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 1  # Still processes entries despite bozo

    def test_parse_rss_feed_entry_without_summary(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test parsing entry without `summary` attribute"""
        delattr(mock_feed_entry, "summary")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result["summary"] == ""

    def test_parse_rss_feed_entry_without_author(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test parsing entry without `author` attribute"""
        delattr(mock_feed_entry, "author")
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result["author"] == ""

    def test_parse_rss_feed_url_error(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parse_rss_feed handles URLError"""
        with patch(
            "feedparser.parse", side_effect=urllib.error.URLError("Network error")
        ):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_http_error(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parse_rss_feed handles HTTPError"""
        with patch(
            "feedparser.parse",
            side_effect=urllib.error.HTTPError(
                "url", 404, "Not Found", EmailMessage(), None
            ),
        ):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_timeout_error(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parse_rss_feed handles TimeoutError"""
        with patch("feedparser.parse", side_effect=TimeoutError("Timeout")):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_socket_gaierror(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parse_rss_feed handles socket.gaierror"""
        with patch("feedparser.parse", side_effect=socket.gaierror("DNS error")):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_connection_reset(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parse_rss_feed handles ConnectionResetError"""
        with patch(
            "feedparser.parse", side_effect=ConnectionResetError("Connection reset")
        ):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 0

    def test_parse_rss_feed_multiple_videos(
        self, youtube_parser_no_init: YoutubeFeedParser
    ) -> None:
        """Test parsing feed with multiple new videos"""
        entry1 = feedparser.FeedParserDict()
        entry1.link = "https://www.youtube.com/watch?v=VIDEO_1"
        entry1.title = "Video 1"
        entry1.published = "2025-01-01T00:00:00+00:00"
        entry1.published_parsed = (2025, 1, 1, 0, 0, 0, 0, 1, 0)

        entry2 = feedparser.FeedParserDict()
        entry2.link = "https://www.youtube.com/watch?v=VIDEO_2"
        entry2.title = "Video 2"
        entry2.published = "2025-01-02T00:00:00+00:00"
        entry2.published_parsed = (2025, 1, 2, 0, 0, 0, 0, 1, 0)

        feed = MagicMock()
        feed.bozo = False
        feed.entries = [entry1, entry2]

        with patch("feedparser.parse", return_value=feed):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 2
            video_result = result[0]
            assert video_result is not None
            assert video_result["id"] == "VIDEO_1"
            video_result = result[1]
            assert video_result is not None
            assert video_result["id"] == "VIDEO_2"
            assert "VIDEO_1" in youtube_parser_no_init.seen_videos
            assert "VIDEO_2" in youtube_parser_no_init.seen_videos

    def test_parse_rss_feed_includes_thumbnail(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
        mock_feed_entry: feedparser.FeedParserDict,
    ) -> None:
        """Test that parse_rss_feed includes thumbnail in `result`"""
        mock_feed_entry.media_thumbnail = [{"url": "https://example.com/thumb.jpg"}]
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result["thumbnail"] == "https://example.com/thumb.jpg"

    def test_parse_rss_feed_includes_published_parsed(
        self,
        youtube_parser_no_init: YoutubeFeedParser,
        mock_feed_with_entries: MagicMock,
    ) -> None:
        """Test that parse_rss_feed includes published_parsed in the result"""
        with patch("feedparser.parse", return_value=mock_feed_with_entries):
            result = youtube_parser_no_init.parse_rss_feed()
            assert len(result) == 1
            video_result = result[0]
            assert video_result is not None
            assert video_result["published_parsed"] == (2025, 1, 1, 0, 0, 0, 0, 1, 0)
