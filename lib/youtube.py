import logging
import socket
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

    def _initialize_seen_videos(self) -> set[str]:
        """
        Initialize seen videos by loading current feed entries
        """
        # Load current feed entries as "already seen"
        logger.debug(
            "Initializing seen videos for %s (%s)", self.feed_name, self.feed_url
        )
        current_videos = set()
        try:
            feed = feedparser.parse(self.feed_url)
            logger.debug("Loaded RSS feed for %s: %s", self.feed_name, feed)
            if feed.bozo:
                logger.warning(
                    "RSS feed may have issues during initialization: %s",
                    feed.bozo_exception,
                )

            for entry in feed.entries:
                logger.debug(
                    "Initializing seen video for %s: %s", feed.feed.title, entry
                )
                video_id = entry.id
                current_videos.add(video_id)

        except (urllib.error.URLError, urllib.error.HTTPError):
            logger.exception("Network error initializing RSS feed seen videos")
        except TimeoutError:
            logger.exception("Timeout error initializing RSS feed seen videos")
        except socket.gaierror:
            logger.exception("DNS resolution initializing RSS feed seen videos")
        except ConnectionResetError:
            logger.exception("Connection reset initializing RSS feed seen videos")

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
