import logging
import socket
import urllib.error

import feedparser

logger: logging.Logger = logging.getLogger(__name__)


class YoutubeFeedParser:
    def __init__(self, feed_name: str, feed_url: str) -> None:
        self.feed_name: str = feed_name
        self.feed_url: str = feed_url
        self.seen_videos: set[str] = self._initialize_seen_videos()

    @staticmethod
    def extract_video_id_from_url(url: str) -> str:
        """Extract video ID from YouTube URL"""
        # URL format: https://www.youtube.com/watch?v=VIDEO_ID
        if "watch?v=" in url:
            return url.split("watch?v=")[1].split("&")[0]
        return url

    def _initialize_seen_videos(self) -> set[str]:
        """
        Initialize seen videos by loading current feed entries
        """
        # Load current feed entries as "already seen"
        current_videos = set()
        try:
            feed = feedparser.parse(self.feed_url)
            if feed.bozo:
                logger.warning(
                    "RSS feed may have issues during initialization: %s",
                    feed.bozo_exception,
                )

            for entry in feed.entries:
                video_id = self.extract_video_id_from_url(entry.link)
                current_videos.add(video_id)

            logger.info(
                "Initialized with %d existing videos marked as seen",
                len(current_videos),
            )
        except (urllib.error.URLError, urllib.error.HTTPError):
            logger.exception("Network error initializing RSS feed seen videos")
        except TimeoutError:
            logger.exception("Timeout error initializing RSS feed seen videos")
        except socket.gaierror:
            logger.exception("DNS resolution initializing RSS feed seen videos")
        except ConnectionResetError:
            logger.exception("Connection reset initializing RSS feed seen videos")

        return current_videos

    def get_thumbnail_from_entry(self, entry: feedparser.FeedParserDict) -> str | None:
        """Extract thumbnail URL from RSS entry"""
        # Try to get the thumbnail from media_thumbnail
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            return entry.media_thumbnail[0]["url"]

        # Try to get from media_content
        if hasattr(entry, "media_content") and entry.media_content:
            for content in entry.media_content:
                if content.get("type", "").startswith("image/"):
                    return content.get("url")

        # Fallback: construct thumbnail URL from video ID
        video_id = self.extract_video_id_from_url(entry.link)
        return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    def parse_rss_feed(self) -> list[dict[str, str | None] | None]:
        """Parse the YouTube RSS feed and return new videos"""
        new_videos = []
        try:
            # Parse the RSS feed
            feed = feedparser.parse(self.feed_url)

            if feed.bozo:
                logger.warning("RSS feed may have issues: %s", feed.bozo_exception)

            # Process entries (videos)
            for entry in feed.entries:
                video_id = self.extract_video_id_from_url(entry.link)

                # Check if we've already seen this video
                if video_id not in self.seen_videos:
                    new_videos.append(
                        {
                            "id": video_id,
                            "title": entry.title,
                            "link": entry.link,
                            "published": entry.published,
                            "published_parsed": entry.published_parsed,
                            "summary": getattr(entry, "summary", ""),
                            "author": getattr(entry, "author", ""),
                            # Extract thumbnail from media content if available
                            "thumbnail": self.get_thumbnail_from_entry(entry),
                        }
                    )

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
