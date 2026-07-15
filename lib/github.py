"""GitHub issue/PR monitor: REST polling, GraphQL linkage, event derivation."""

import datetime
import logging
from dataclasses import dataclass, replace
from typing import NotRequired, TypedDict

import aiohttp

from lib.config import config

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
CLOSE_KINDS: frozenset[str] = _ISSUE_CLOSE_KINDS | _PR_CLOSE_KINDS
_CLOSED_ACTOR_FRAGMENT: str = (
    "timelineItems(itemTypes:[CLOSED_EVENT],last:1)"
    "{nodes{... on ClosedEvent{actor{login avatarUrl}}}}"
)


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
    closer_login: str = ""
    closer_avatar_url: str = ""
    linked_issues: tuple[GitHubActivityEvent, ...] = ()


@dataclass(frozen=True)
class _PRCloseDetails:
    """Linked issue numbers and the closing actor for a PR-close event."""

    linked_issue_numbers: tuple[int, ...]
    closer_login: str
    closer_avatar_url: str


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
        self._session: aiohttp.ClientSession | None = None

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
    def _closer_from_actor(actor: object) -> tuple[str, str]:
        """Extract (login, avatar_url) from a GraphQL actor node; empty if absent."""
        if not isinstance(actor, dict):
            return "", ""
        login = actor.get("login")
        avatar = actor.get("avatarUrl")
        return (
            login if isinstance(login, str) else "",
            avatar if isinstance(avatar, str) else "",
        )

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
            created = _parse_dt(issue["created_at"])
            if created and created > self._started_at:
                events.append(self._make_event(self._open_kind(is_pr), issue))
            if issue.get("state") == "closed":
                closed = _parse_dt(issue.get("closed_at"))
                if closed and closed > self._started_at:
                    events.append(
                        self._make_event(self._close_kind(issue, is_pr), issue)
                    )
        return events

    async def start_session(self) -> None:
        """Open the aiohttp session with GitHub auth + version headers."""
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "jims-garage-discord-bot",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._session = aiohttp.ClientSession(headers=headers)

    async def close_session(self) -> None:
        """Close the aiohttp session if open."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _fetch_updated_issues(
        self,
        *,
        since: datetime.datetime | None,
        max_pages: int = 5,
        per_page: int = 100,
    ) -> list[GitHubIssue] | None:
        """Fetch issues+PRs updated since `since`, following pagination."""
        if self._session is None:
            return None
        url = f"{GITHUB_API_URL}/repos/{self._repo}/issues"
        results: list[GitHubIssue] = []
        for page in range(1, max_pages + 1):
            params = {
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": str(per_page),
                "page": str(page),
            }
            if since is not None:
                params["since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                async with self._session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    page_items: list[GitHubIssue] = await resp.json()
            except aiohttp.ClientError:
                logger.exception("GitHub REST request failed (page %d)", page)
                return None
            if not page_items:
                break
            results.extend(page_items)
            if len(page_items) < per_page:
                break
        else:
            logger.warning("GitHub REST pagination hit max_pages=%d cap", max_pages)
        return results

    async def get_latest_activity(self) -> GitHubActivityEvent | None:
        """Return an event for the single most-recently-updated item (no gate)."""
        issues = await self._fetch_updated_issues(since=None, max_pages=1, per_page=1)
        if not issues:
            return None
        issue = issues[0]
        is_pr = "pull_request" in issue
        if issue.get("state") == "closed":
            kind = self._close_kind(issue, is_pr)
        else:
            kind = self._open_kind(is_pr)
        event = self._make_event(kind, issue)
        if kind in CLOSE_KINDS:
            closer_login, closer_avatar_url = await self._resolve_closer(event)
            event = replace(
                event,
                closer_login=closer_login,
                closer_avatar_url=closer_avatar_url,
            )
        return event

    def _toggle_on(self, kind: str) -> bool:
        """Return True if the config toggle for this event kind is enabled."""
        return bool(getattr(config.GITHUB.EVENTS, kind))

    async def _resolve_pr_close_details(
        self, pr_number: int, *, is_merge: bool
    ) -> _PRCloseDetails:
        """Return linked issue numbers and the closer for a PR-close event.

        A merge is attributed via `mergedBy`; a non-merge close via the last
        `CLOSED_EVENT` actor. (A merge emits both a MergedEvent and a ClosedEvent,
        so `timelineItems` is intentionally ignored for merges.)
        """
        empty = _PRCloseDetails((), "", "")
        if not self._token or self._session is None:
            return empty
        owner, _, name = self._repo.partition("/")
        query = (
            "query($owner:String!,$name:String!,$number:Int!){"
            "repository(owner:$owner,name:$name){"
            "pullRequest(number:$number){"
            "mergedBy{login avatarUrl}"
            "closingIssuesReferences(first:20){nodes{number}}"
            f"{_CLOSED_ACTOR_FRAGMENT}"
            "}}}"
        )
        payload = {
            "query": query,
            "variables": {"owner": owner, "name": name, "number": pr_number},
        }
        try:
            async with self._session.post(GITHUB_GRAPHQL_URL, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError:
            logger.exception("GraphQL request failed for PR #%d", pr_number)
            return empty
        if data and data.get("errors"):
            logger.warning(
                "GraphQL errors resolving PR #%d: %s", pr_number, data["errors"]
            )
        pull_request = (((data or {}).get("data") or {}).get("repository") or {}).get(
            "pullRequest"
        ) or {}
        refs = pull_request.get("closingIssuesReferences") or {}
        nodes = refs.get("nodes") or []
        linked = tuple(n["number"] for n in nodes if "number" in n)
        if is_merge:
            actor = pull_request.get("mergedBy")
        else:
            timeline = pull_request.get("timelineItems") or {}
            tnodes = timeline.get("nodes") or []
            actor = tnodes[-1].get("actor") if tnodes else None
        closer_login, closer_avatar_url = self._closer_from_actor(actor)
        return _PRCloseDetails(linked, closer_login, closer_avatar_url)

    async def _resolve_issue_closers(
        self, numbers: list[int]
    ) -> dict[int, tuple[str, str]]:
        """Batch-resolve closers for standalone issue closes via one aliased query.

        Holds closer resolution to a single GraphQL call per poll regardless of how
        many issues closed, avoiding secondary-rate-limit risk on mass closes.
        """
        if not numbers or not self._token or self._session is None:
            return {}
        owner, _, name = self._repo.partition("/")
        fields = "".join(
            f"i{n}:issue(number:{n}){{{_CLOSED_ACTOR_FRAGMENT}}}" for n in numbers
        )
        query = (
            "query($owner:String!,$name:String!){"
            "repository(owner:$owner,name:$name){"
            f"{fields}"
            "}}"
        )
        payload = {"query": query, "variables": {"owner": owner, "name": name}}
        try:
            async with self._session.post(GITHUB_GRAPHQL_URL, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError:
            logger.exception("GraphQL request failed for issue closers")
            return {}
        if data and data.get("errors"):
            logger.warning("GraphQL errors resolving issue closers: %s", data["errors"])
        repository = ((data or {}).get("data") or {}).get("repository") or {}
        result: dict[int, tuple[str, str]] = {}
        for number in numbers:
            node = repository.get(f"i{number}") or {}
            timeline = node.get("timelineItems") or {}
            tnodes = timeline.get("nodes") or []
            actor = tnodes[-1].get("actor") if tnodes else None
            result[number] = self._closer_from_actor(actor)
        return result

    async def _resolve_closer(self, event: GitHubActivityEvent) -> tuple[str, str]:
        """Resolve (login, avatar_url) of who closed this event; empty if none."""
        if event.is_pr and event.kind in _PR_CLOSE_KINDS:
            details = await self._resolve_pr_close_details(
                event.number, is_merge=event.kind == "PR_MERGED"
            )
            return details.closer_login, details.closer_avatar_url
        if event.kind in _ISSUE_CLOSE_KINDS:
            closers = await self._resolve_issue_closers([event.number])
            return closers.get(event.number, ("", ""))
        return "", ""

    async def get_new_events(self) -> list[GitHubActivityEvent]:
        """Poll, derive, gate, combine linked closes, and return postables."""
        poll_time = datetime.datetime.now(tz=datetime.UTC)
        issues = await self._fetch_updated_issues(since=self._last_checked)
        if issues is None:
            logger.warning(
                "GitHub fetch failed; leaving poll cursor at %s for retry",
                self._last_checked,
            )
            return []
        derived = self._derive_events(issues)
        fresh = [e for e in derived if e.key not in self._seen]
        for event in fresh:
            self._seen.add(event.key)
        self._last_checked = poll_time

        issue_closes = {
            e.number: e for e in fresh if not e.is_pr and e.kind in _ISSUE_CLOSE_KINDS
        }
        combined_numbers: set[int] = set()
        plan: list[GitHubActivityEvent] = []

        for event in fresh:
            if event.is_pr and event.kind in _PR_CLOSE_KINDS:
                if not self._toggle_on(event.kind):
                    continue
                # Resolve PR details directly (not via _resolve_closer) for batching.
                details = await self._resolve_pr_close_details(
                    event.number, is_merge=event.kind == "PR_MERGED"
                )
                linked = [
                    issue_closes[n]
                    for n in details.linked_issue_numbers
                    if n in issue_closes
                ]
                combined_numbers.update(i.number for i in linked)
                plan.append(
                    replace(
                        event,
                        linked_issues=tuple(linked),
                        closer_login=details.closer_login,
                        closer_avatar_url=details.closer_avatar_url,
                    )
                )

        await self._enqueue_non_pr_events(fresh, combined_numbers, plan)
        plan.sort(key=lambda e: (e.number, e.kind))
        return plan

    async def _enqueue_non_pr_events(
        self,
        fresh: list[GitHubActivityEvent],
        combined_numbers: set[int],
        plan: list[GitHubActivityEvent],
    ) -> None:
        """Add toggled-on, non-PR-close events to plan, resolving issue closers."""
        standalone_issue_closes: list[GitHubActivityEvent] = []
        for event in fresh:
            if event.is_pr and event.kind in _PR_CLOSE_KINDS:
                continue
            if event.number in combined_numbers and event.kind in _ISSUE_CLOSE_KINDS:
                continue
            if not self._toggle_on(event.kind):
                continue
            if event.kind in _ISSUE_CLOSE_KINDS:
                standalone_issue_closes.append(event)
            else:
                plan.append(event)

        if standalone_issue_closes:
            closers = await self._resolve_issue_closers(
                [e.number for e in standalone_issue_closes]
            )
            for event in standalone_issue_closes:
                login, avatar = closers.get(event.number, ("", ""))
                plan.append(
                    replace(event, closer_login=login, closer_avatar_url=avatar)
                )
