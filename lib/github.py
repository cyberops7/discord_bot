"""GitHub issue/PR monitor: REST polling, GraphQL linkage, event derivation."""

import datetime
import logging
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from lib.config import config  # noqa: F401

logger: logging.Logger = logging.getLogger(__name__)

GITHUB_API_URL: str = "https://api.github.com"
GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"

# kind -> (emoji, embed color hex, title verb)
EVENT_RENDER: dict[str, tuple[str, int, str]] = {
    "ISSUE_OPENED": ("🟢", 0x2ECC71, "New issue"),
    "ISSUE_COMPLETED": ("🟣", 0x9B59B6, "Issue closed as completed"),
    "ISSUE_NOT_PLANNED": ("⚪", 0x95A5A6, "Issue closed as not planned"),
    "PR_OPENED": ("🟢", 0x2ECC71, "New PR"),
    "PR_MERGED": ("🟣", 0x9B59B6, "PR merged"),
    "PR_CLOSED": ("🔴", 0xE74C3C, "PR closed"),
}

_ISSUE_CLOSE_KINDS: frozenset[str] = frozenset({"ISSUE_COMPLETED", "ISSUE_NOT_PLANNED"})
_PR_CLOSE_KINDS: frozenset[str] = frozenset({"PR_MERGED", "PR_CLOSED"})


class GitHubUser(TypedDict):
    """Subset of the GitHub user object we consume."""

    login: str
    avatar_url: str


class PullRequestRef(TypedDict):
    """The `pull_request` sub-object present on PR items in the issues list."""

    merged_at: NotRequired[str | None]


class GitHubIssue(TypedDict):
    """Subset of the GitHub issue/PR object we consume."""

    number: int
    title: str
    html_url: str
    state: str
    created_at: str
    user: NotRequired[GitHubUser | None]
    closed_at: NotRequired[str | None]
    state_reason: NotRequired[str | None]
    pull_request: NotRequired[PullRequestRef]


@dataclass(frozen=True)
class GitHubActivityEvent:
    """A single postable GitHub activity event."""

    key: str
    kind: str
    number: int
    title: str
    url: str
    author_login: str
    author_avatar_url: str
    is_pr: bool
    linked_issues: tuple["GitHubActivityEvent", ...] = ()


def _parse_dt(value: str | None) -> datetime.datetime | None:
    """Parse a GitHub ISO-8601 timestamp (with `Z`) into an aware datetime."""
    if not value:
        return None
    return datetime.datetime.fromisoformat(value)


class GitHubMonitor:
    """Polls a GitHub repo for issue/PR activity and derives postable events."""

    def __init__(self, repo: str, token: str, started_at: datetime.datetime) -> None:
        self._repo = repo
        self._token = token
        self._started_at = started_at
        self._last_checked = started_at
        self._seen: set[str] = set()

    @staticmethod
    def _open_kind(is_pr: bool) -> str:
        return "PR_OPENED" if is_pr else "ISSUE_OPENED"

    @staticmethod
    def _close_kind(issue: GitHubIssue, is_pr: bool) -> str:
        if is_pr:
            pr_ref = issue.get("pull_request")
            merged = pr_ref.get("merged_at") if pr_ref else None
            return "PR_MERGED" if merged else "PR_CLOSED"
        reason = issue.get("state_reason")
        if reason in ("not_planned", "duplicate"):
            return "ISSUE_NOT_PLANNED"
        return "ISSUE_COMPLETED"

    @staticmethod
    def _make_event(kind: str, issue: GitHubIssue) -> GitHubActivityEvent:
        author = issue.get("user")
        number = issue["number"]
        return GitHubActivityEvent(
            key=f"{kind}:{number}",
            kind=kind,
            number=number,
            title=issue["title"],
            url=issue["html_url"],
            author_login=author["login"] if author else "",
            author_avatar_url=author["avatar_url"] if author else "",
            is_pr="pull_request" in issue,
        )

    def _derive_events(self, issues: list[GitHubIssue]) -> list[GitHubActivityEvent]:
        """Derive candidate events, keeping only those after startup time."""
        events: list[GitHubActivityEvent] = []
        for issue in issues:
            is_pr = "pull_request" in issue
            created = _parse_dt(issue.get("created_at"))
            if created and created > self._started_at:
                events.append(self._make_event(self._open_kind(is_pr), issue))
            if issue.get("state") == "closed":
                closed = _parse_dt(issue.get("closed_at"))
                if closed and closed > self._started_at:
                    events.append(
                        self._make_event(self._close_kind(issue, is_pr), issue)
                    )
        return events
