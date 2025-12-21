from typing import Any

class FeedParserDict(dict[str, Any]):
    # Common feed entry attributes
    id: str
    title: str
    link: str
    author: str
    published: str
    published_parsed: tuple[int, int, int, int, int, int, int, int, int]
    summary: str
    yt_videoid: str | tuple[str, ...]

    def __getattr__(self, name: str) -> Any: ...  # noqa: ANN401 - Dynamic attribute access
    def __setattr__(self, name: str, value: Any) -> None: ...  # noqa: ANN401 - Dynamic attribute access
    def __delattr__(self, name: str) -> None: ...

class _Feed(FeedParserDict):
    title: str
    link: str

class _ParsedFeed(FeedParserDict):
    bozo: bool
    bozo_exception: Exception | None
    entries: list[FeedParserDict]
    feed: _Feed

def parse(url: str) -> _ParsedFeed: ...
