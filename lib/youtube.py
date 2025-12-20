import logging
import socket
import time
import urllib.error

import feedparser
from feedparser import FeedParserDict

logger: logging.Logger = logging.getLogger(__name__)


class YoutubeFeedParser:
    def __init__(self, feed_name: str, feed_url: str) -> None:
        self.feed_name: str = feed_name
        self.feed_url: str = feed_url
        self.seen_videos: set[str] = self._initialize_seen_videos()

    @staticmethod
    def get_thumbnail_from_entry(entry: FeedParserDict) -> str | None:
        """Extract thumbnail URL from RSS entry"""
        if video_id := getattr(entry, "yt_videoid", ""):
            url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            logger.debug("Generated thumbnail URL: %s", url)
        else:
            url = None
            logger.warning("Could not extract video ID from entry: %s", entry)
        return url

    @staticmethod
    def _process_feed_entries(feed: FeedParserDict, current_videos: set[str]) -> None:
        """
        Process feed entries and add video IDs to the current_videos set.

        Args:
            feed: The parsed feed
            current_videos: Set to add video IDs to (modified in place)
        """
        for entry in feed.entries:
            logger.debug("Initializing seen video for %s: %s", feed.feed.title, entry)
            video_id = entry.id
            current_videos.add(video_id)

    @staticmethod
    def _should_retry_bozo_feed(
        feed: FeedParserDict,
        attempt: int,
        max_retries: int,
        retry_delay: int,
    ) -> bool:
        """
        Check if bozo feed should be retried.

        Args:
            feed: The parsed feed
            attempt: Current attempt number (0-indexed)
            max_retries: Maximum number of retry attempts
            retry_delay: Current retry delay in seconds

        Returns:
            True if the method should retry (bozo with no entries and retries remain)
        """
        if not (feed.bozo and not feed.entries):
            return False

        if attempt < max_retries - 1:
            logger.warning(
                "RSS feed has issues (attempt %d/%d): %s - retrying in %ds",
                attempt + 1,
                max_retries,
                getattr(feed, "bozo_exception", "unknown"),
                retry_delay,
            )
            time.sleep(retry_delay)
            return True

        logger.warning(
            "RSS feed may have issues during initialization: %s",
            getattr(feed, "bozo_exception", "unknown"),
        )
        return False

    def _attempt_feed_fetch(
        self,
        attempt: int,
        max_retries: int,
        retry_delay: int,
        current_videos: set[str],
    ) -> tuple[bool, int]:
        """
        Attempt to fetch and process feed entries.

        Args:
            attempt: Current attempt number (0-indexed)
            max_retries: Maximum number of retry attempts
            retry_delay: Current retry delay in seconds
            current_videos: Set to add video IDs to

        Returns:
            Tuple of (success, new_retry_delay)
            - success: True if the feed was processed successfully
            - new_retry_delay: Updated retry delay (doubled if retry needed)
        """
        try:
            feed = feedparser.parse(self.feed_url)
            logger.debug("Loaded RSS feed for %s: %s", self.feed_name, feed)

            # If bozo and no entries, it might be a transient issue - retry
            if YoutubeFeedParser._should_retry_bozo_feed(
                feed, attempt, max_retries, retry_delay
            ):
                return False, retry_delay * 2
            YoutubeFeedParser._process_feed_entries(feed, current_videos)
            return True, retry_delay  # noqa: TRY300

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            socket.gaierror,
            ConnectionResetError,
        ) as e:
            # Determine error type for logging
            error_type = {
                urllib.error.URLError: "Network error",
                urllib.error.HTTPError: "Network error",
                TimeoutError: "Timeout error",
                socket.gaierror: "DNS resolution error",
                ConnectionResetError: "Connection reset",
            }.get(type(e), "Unknown error")

            if YoutubeFeedParser._handle_feed_fetch_error(
                error_type, attempt, max_retries, retry_delay
            ):
                return False, retry_delay * 2
            return False, retry_delay

    @staticmethod
    def _handle_feed_fetch_error(
        error_type: str,
        attempt: int,
        max_retries: int,
        retry_delay: int,
    ) -> bool:
        """
        Handle feed fetch errors with retry logic.

        Args:
            error_type: Human-readable error type for logging
            attempt: Current attempt number (0-indexed)
            max_retries: Maximum number of retry attempts
            retry_delay: Current retry delay in seconds

        Returns:
            True if the method should retry, False if retries are exhausted
        """
        if attempt < max_retries - 1:
            logger.warning(
                "%s (attempt %d/%d) - retrying in %ds",
                error_type,
                attempt + 1,
                max_retries,
                retry_delay,
            )
            time.sleep(retry_delay)
            return True

        logger.exception("%s initializing RSS feed seen videos", error_type)
        return False

    def _initialize_seen_videos(self) -> set[str]:
        """
        Initialize seen videos by loading current feed entries with retry logic
        """
        # Load current feed entries as "already seen"
        logger.debug(
            "Initializing seen videos for %s (%s)", self.feed_name, self.feed_url
        )
        current_videos = set()
        max_retries = 3
        retry_delay = 1  # seconds

        for attempt in range(max_retries):
            success, retry_delay = self._attempt_feed_fetch(
                attempt, max_retries, retry_delay, current_videos
            )
            if success:
                break

        logger.info(
            "Initialized with %d existing videos marked as seen",
            len(current_videos),
        )
        logger.debug("Initialized seen videos: %s", current_videos)

        return current_videos

    def get_latest_video(self) -> FeedParserDict:
        """Get the latest video from the feed"""
        return feedparser.parse(self.feed_url).entries[0]

    def get_new_videos(self) -> list[FeedParserDict]:
        """Parse the YouTube RSS feed and return new videos"""
        new_videos: list[FeedParserDict] = []
        try:
            # Parse the RSS feed
            feed = feedparser.parse(self.feed_url)

            if feed.bozo:
                logger.warning("RSS feed may have issues: %s", feed.bozo_exception)

            # Process entries (videos)
            for entry in feed.entries:
                if not (video_id := getattr(entry, "id", "")):
                    continue

                # Check if we've already seen this video
                if video_id not in self.seen_videos:
                    new_videos.append(entry)

                    # Add to seen videos
                    self.seen_videos.add(video_id)

        except (urllib.error.URLError, urllib.error.HTTPError):
            logger.exception("Network error parsing RSS feed")
        except TimeoutError:
            logger.exception("Timeout error parsing RSS feed")
        except socket.gaierror:
            logger.exception("DNS resolution error parsing RSS feed")
        except ConnectionResetError:
            logger.exception("Connection reset error parsing RSS feed")

        return new_videos
