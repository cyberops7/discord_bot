# GitHub Issue/PR Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a periodic background task that watches
`JamesTurland/JimsGarage` for opened/closed issues and PRs and posts compact
embeds to the `#github` channel, combining a merged PR with any issue it
officially closes.

**Architecture:** A new `GitHubMonitor` class in `lib/github.py` (peer of
`lib/youtube.py`) owns async REST polling, GraphQL linkage resolution, event
derivation, and an in-memory "seen" set. A new `monitor_github_activity`
`@tasks.loop` in the existing `Tasks` cog drives it and builds/sends embeds.
Config lives in the `config` singleton; a `GITHUB_TOKEN` secret authenticates
the API.

**Tech Stack:** Python 3.13, discord.py (`discord.ext.tasks`), `aiohttp`
(already transitive via discord.py; declared explicitly), GitHub REST +
GraphQL APIs, pytest / pytest-asyncio / pytest-mock, uv, ruff, pyrefly, bandit.

## Global Constraints

- Python `>=3.13`; dependency management via `uv` only (never pip/poetry).
- Test coverage: **100% branch coverage** (`--cov=lib --cov=main
  --cov-branch --cov-fail-under=100`). `tests/` is not coverage-measured.
- Lint/format: ruff `ALL` (line-length 88, double quotes, 4-space indent);
  docstrings optional (`D` ignored) but follow existing class/method docstring
  style. Run `uv run ruff format` then `uv run ruff check` before every commit.
- Typing: pyrefly strict — full annotations on every function, method, and
  attribute. Model GitHub JSON with `TypedDict`s, not `dict[str, Any]`. Run
  `uv run pyrefly check` before every commit.
- Security: bandit clean; the GitHub token is read from env/config only and
  never logged; test token literals carry `# noqa: S105`.
- Config: all values via `from lib.config import config`; **no literals** in
  code. Env overrides use nested-underscore (`GITHUB_TOKEN` → `GITHUB.TOKEN`).
- No `@everyone`/`@here` pings — `#github` is a maintainer working channel.
- Version bump `0.9.5` → `0.10.0` in `pyproject.toml`; matching image tag
  `v0.9.5` → `v0.10.0` in `kubernetes/discordbot.yaml`.
- **Each commit must independently pass `uv run invoke check` and keep coverage
  at 100%.** The conftest/config changes (Task 1) land first so later tests can
  reference the new config keys.
- Commit messages: plain imperative, no mention of Claude/AI.

---

## File Structure

**Create:**

- `lib/github.py` — `GitHubMonitor`, `GitHubActivityEvent`, GitHub `TypedDict`s,
  `EVENT_RENDER` map, module constants. All GitHub logic + async I/O. No
  `discord` import (rendering data is plain; the cog builds the embed).
- `tests/test_github.py` — unit tests for `GitHubMonitor` (mocked `aiohttp`).

**Modify:**

- `conf/config.yaml` — add `CHANNELS.GITHUB`, `DRY_RUN_GITHUB`, `GITHUB` block.
- `sample.env` — add `GITHUB_TOKEN=`.
- `tests/conftest.py` — extend the autouse `mock_config` fixture with `GITHUB.*`
  attributes and a `patch("lib.github.config", mock_cfg)` entry.
- `lib/cogs/tasks.py` — add the loop, bootstrap, `before_loop`, `cog_unload`
  wiring, and `_build_github_embed`.
- `tests/cogs/test_tasks.py` — extend `tasks_cog` fixture; add loop tests.
- `pyproject.toml` — version bump + declare `aiohttp` dependency.
- `kubernetes/discordbot.yaml` — image tag, `GITHUB_TOKEN` secret env,
  `DRY_RUN_GITHUB` env.

---

## Task 1: Config keys, sample.env, and test scaffolding

**Files:**

- Modify: `conf/config.yaml`
- Modify: `sample.env`
- Modify: `tests/conftest.py`

**Interfaces:**

- Produces: config keys `config.CHANNELS.GITHUB` (int), `config.DRY_RUN_GITHUB`
  (bool), `config.GITHUB.REPO` (str), `config.GITHUB.TOKEN` (str),
  `config.GITHUB.POLL_MINUTES` (int), `config.GITHUB.EVENTS.<KIND>` (bool for
  each of `ISSUE_OPENED`, `ISSUE_COMPLETED`, `ISSUE_NOT_PLANNED`, `PR_OPENED`,
  `PR_MERGED`, `PR_CLOSED`). Mock equivalents in the `mock_config` fixture.

- [ ] **Step 1: Add config keys to `conf/config.yaml`**

Add `GITHUB: 1522491309003243660` under `CHANNELS:` (keep keys alphabetized),
add `DRY_RUN_GITHUB: false` after `DRY_RUN_YOUTUBE: false`, and add this block
(alphabetized among top-level keys, i.e. after `GUILDS:`):

```yaml
GITHUB:
  REPO: "JamesTurland/JimsGarage"
  TOKEN:                       # overridden by env GITHUB_TOKEN
  POLL_MINUTES: 5
  EVENTS:
    ISSUE_OPENED: true
    ISSUE_COMPLETED: true
    ISSUE_NOT_PLANNED: true
    PR_OPENED: true
    PR_MERGED: true
    PR_CLOSED: true
```

- [ ] **Step 2: Add the token to `sample.env`**

Add this line after `BOT_TOKEN=`:

```dotenv
GITHUB_TOKEN=
```

- [ ] **Step 3: Extend the `mock_config` fixture in `tests/conftest.py`**

Inside the `mock_config` fixture, after the `mock_cfg.YOUTUBE_FEEDS = {...}`
block, add:

```python
    mock_cfg.CHANNELS.GITHUB = 222
    mock_cfg.DRY_RUN_GITHUB = False
    mock_cfg.GITHUB.REPO = "JamesTurland/JimsGarage"
    mock_cfg.GITHUB.TOKEN = "test_github_token"  # noqa: S105
    mock_cfg.GITHUB.POLL_MINUTES = 5
    mock_cfg.GITHUB.EVENTS.ISSUE_OPENED = True
    mock_cfg.GITHUB.EVENTS.ISSUE_COMPLETED = True
    mock_cfg.GITHUB.EVENTS.ISSUE_NOT_PLANNED = True
    mock_cfg.GITHUB.EVENTS.PR_OPENED = True
    mock_cfg.GITHUB.EVENTS.PR_MERGED = True
    mock_cfg.GITHUB.EVENTS.PR_CLOSED = True
```

Then add a `patch("lib.github.config", mock_cfg),` line to the `with (...)`
patch block (alongside the existing `patch("lib.cogs.tasks.config", mock_cfg)`).

- [ ] **Step 4: Verify existing checks still pass**

Run: `uv run invoke check`
Expected: all checks pass (config is data, conftest is test-only — coverage
unaffected).

The new `patch("lib.github.config", ...)` in conftest needs `lib/github.py` to
exist and expose `config`, so first create a placeholder (fleshed out in
Task 2):

```python
"""GitHub monitor module."""

from lib.config import config  # noqa: F401
```

Run: `uv run pytest -q`
Expected: existing suite passes.

- [ ] **Step 5: Commit**

```bash
git add conf/config.yaml sample.env tests/conftest.py lib/github.py
git commit -m "Add GitHub monitor config keys and test scaffolding"
```

---

## Task 2: Data model, constants, and event derivation

**Files:**

- Modify: `lib/github.py`
- Test: `tests/test_github.py`

**Interfaces:**

- Consumes: `config` singleton (`config.GITHUB.*`).
- Produces:
   - `GitHubActivityEvent` frozen dataclass with fields `key: str`,
     `kind: str`, `number: int`, `title: str`, `url: str`,
     `author_login: str`, `author_avatar_url: str`, `is_pr: bool`,
     `linked_issues: tuple[GitHubActivityEvent, ...] = ()`.
   - `GitHubIssue`, `GitHubUser`, `PullRequestRef` `TypedDict`s.
   - `EVENT_RENDER: dict[str, tuple[str, int, str]]` (kind → emoji, hex color,
     verb).
   - Module constants `GITHUB_API_URL`, `GITHUB_GRAPHQL_URL`.
   - `GitHubMonitor.__init__(self, repo: str, token: str, started_at:
     datetime.datetime)`.
   - `GitHubMonitor._derive_events(self, issues: list[GitHubIssue]) ->
     list[GitHubActivityEvent]` (applies the timestamp gate only).
   - Static helpers `_open_kind(is_pr) -> str`, `_close_kind(issue, is_pr) ->
     str`, `_make_event(kind, issue) -> GitHubActivityEvent`, and module
     function `_parse_dt(value: str | None) -> datetime.datetime | None`.

- [ ] **Step 1: Write failing tests for the data model and derivation**

Replace the contents of `tests/test_github.py` with:

Note on typing: assigning a `MagicMock` to a typed attribute (e.g.
`monitor._session = session`) mirrors the existing `tests/cogs/test_tasks.py`
patterns and passes pyrefly; if pyrefly ever flags one, append `# pyrefly:
ignore`. All imports live in the top import block — later tasks add to it, never
mid-file (ruff E402).

```python
"""Unit tests for the github.py module"""

import datetime
from typing import cast

import pytest

from lib.github import (
    EVENT_RENDER,
    GitHubActivityEvent,
    GitHubIssue,
    GitHubMonitor,
    _parse_dt,
)

START = datetime.datetime(2026, 7, 3, 0, 0, 0, tzinfo=datetime.UTC)
AFTER = "2026-07-03T01:00:00Z"
BEFORE = "2026-07-02T23:00:00Z"


def _issue(**overrides: object) -> GitHubIssue:
    """Build a REST issue/PR payload with sensible defaults."""
    base: dict[str, object] = {
        "number": 40,
        "title": "Something broke",
        "html_url": "https://github.com/JamesTurland/JimsGarage/issues/40",
        "state": "open",
        "created_at": AFTER,
        "closed_at": None,
        "user": {"login": "octocat", "avatar_url": "https://avatars/1"},
    }
    base.update(overrides)
    return cast("GitHubIssue", base)


@pytest.fixture
def monitor() -> GitHubMonitor:
    return GitHubMonitor(
        repo="JamesTurland/JimsGarage",
        token="t",  # noqa: S106
        started_at=START,
    )


def test_parse_dt_handles_z_suffix() -> None:
    assert _parse_dt("2026-07-03T01:00:00Z") == datetime.datetime(
        2026, 7, 3, 1, 0, 0, tzinfo=datetime.UTC
    )


def test_parse_dt_none_returns_none() -> None:
    assert _parse_dt(None) is None


def test_derive_new_issue_opened(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events([_issue()])
    assert len(events) == 1
    assert events[0].kind == "ISSUE_OPENED"
    assert events[0].key == "ISSUE_OPENED:40"
    assert events[0].is_pr is False
    assert events[0].author_login == "octocat"


def test_derive_ignores_opened_before_startup(monitor: GitHubMonitor) -> None:
    assert monitor._derive_events([_issue(created_at=BEFORE)]) == []


def test_derive_new_pr_opened(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events([_issue(pull_request={})])
    assert events[0].kind == "PR_OPENED"
    assert events[0].is_pr is True


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"state": "closed", "closed_at": AFTER, "state_reason": "completed"},
         "ISSUE_COMPLETED"),
        ({"state": "closed", "closed_at": AFTER, "state_reason": None},
         "ISSUE_COMPLETED"),
        ({"state": "closed", "closed_at": AFTER, "state_reason": "not_planned"},
         "ISSUE_NOT_PLANNED"),
        ({"state": "closed", "closed_at": AFTER, "state_reason": "duplicate"},
         "ISSUE_NOT_PLANNED"),
    ],
)
def test_derive_issue_close_kinds(
    monitor: GitHubMonitor, overrides: dict[str, object], expected: str
) -> None:
    # created before startup so only the close event is emitted
    events = monitor._derive_events([_issue(created_at=BEFORE, **overrides)])
    assert [e.kind for e in events] == [expected]


@pytest.mark.parametrize(
    ("pr_ref", "expected"),
    [
        ({"merged_at": "2026-07-03T01:00:00Z"}, "PR_MERGED"),
        ({"merged_at": None}, "PR_CLOSED"),
    ],
)
def test_derive_pr_close_kinds(
    monitor: GitHubMonitor, pr_ref: dict[str, object], expected: str
) -> None:
    events = monitor._derive_events(
        [_issue(created_at=BEFORE, state="closed", closed_at=AFTER,
                pull_request=pr_ref)]
    )
    assert [e.kind for e in events] == [expected]


def test_derive_open_and_close_same_poll(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events(
        [_issue(state="closed", closed_at=AFTER, state_reason="completed")]
    )
    assert {e.kind for e in events} == {"ISSUE_OPENED", "ISSUE_COMPLETED"}


def test_derive_ignores_close_before_startup(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events(
        [_issue(created_at=BEFORE, state="closed", closed_at=BEFORE,
                state_reason="completed")]
    )
    assert events == []


def test_event_render_covers_all_kinds() -> None:
    assert set(EVENT_RENDER) == {
        "ISSUE_OPENED", "ISSUE_COMPLETED", "ISSUE_NOT_PLANNED",
        "PR_OPENED", "PR_MERGED", "PR_CLOSED",
    }


def test_make_event_missing_user(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events([_issue(user=None)])
    assert events[0].author_login == ""
    assert events[0].author_avatar_url == ""


def test_event_is_frozen() -> None:
    event = GitHubActivityEvent(
        key="k", kind="ISSUE_OPENED", number=1, title="t", url="u",
        author_login="a", author_avatar_url="", is_pr=False,
    )
    with pytest.raises(AttributeError):
        setattr(event, "number", 2)  # noqa: B010
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github.py -q`
Expected: FAIL — `ImportError` (`EVENT_RENDER`, `GitHubActivityEvent`, etc. not
defined).

- [ ] **Step 3: Implement the data model and derivation in `lib/github.py`**

Replace the contents of `lib/github.py` with:

```python
"""GitHub issue/PR monitor: REST polling, GraphQL linkage, event derivation."""

import datetime
import logging
from dataclasses import dataclass
from typing import NotRequired, TypedDict

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

_ISSUE_CLOSE_KINDS: frozenset[str] = frozenset(
    {"ISSUE_COMPLETED", "ISSUE_NOT_PLANNED"}
)
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
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubMonitor:
    """Polls a GitHub repo for issue/PR activity and derives postable events."""

    def __init__(
        self, repo: str, token: str, started_at: datetime.datetime
    ) -> None:
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

    def _derive_events(
        self, issues: list[GitHubIssue]
    ) -> list[GitHubActivityEvent]:
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github.py -q`
Expected: PASS (all Task 2 tests green).

- [ ] **Step 5: Format, type-check, and commit**

```bash
uv run ruff format lib/github.py tests/test_github.py
uv run ruff check lib/github.py tests/test_github.py
uv run pyrefly check
git add lib/github.py tests/test_github.py
git commit -m "Add GitHub event model and derivation logic"
```

---

## Task 3: Async REST fetch, session lifecycle, and latest-activity

**Files:**

- Modify: `lib/github.py`
- Modify: `pyproject.toml` (declare `aiohttp`)
- Test: `tests/test_github.py`

**Interfaces:**

- Consumes: `GitHubMonitor.__init__`, `_make_event`, `_open_kind`,
  `_close_kind` (Task 2).
- Produces:
   - `async GitHubMonitor.start_session(self) -> None`
   - `async GitHubMonitor.close_session(self) -> None`
   - `async GitHubMonitor._fetch_updated_issues(self, *, since:
     datetime.datetime | None, max_pages: int = 5, per_page: int = 100) ->
     list[GitHubIssue]`
   - `async GitHubMonitor.get_latest_activity(self) -> GitHubActivityEvent |
     None`
   - Instance attribute `self._session: aiohttp.ClientSession | None`.

- [ ] **Step 1: Declare `aiohttp` as a direct dependency**

`aiohttp` is imported directly (not just transitively via discord.py), so
declare it:

Run: `uv add aiohttp`
Expected: `pyproject.toml` gains an `aiohttp>=…` entry under
`[project.dependencies]` and `uv.lock` updates. Keep whatever floor uv writes.

- [ ] **Step 2: Write failing tests for fetch, session, and latest-activity**

First, **replace the top import block** of `tests/test_github.py` with this
(adds `logging`, `unittest.mock`, `aiohttp`, and `async_test` in sorted order):

```python
"""Unit tests for the github.py module"""

import datetime
import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from lib.github import (
    EVENT_RENDER,
    GitHubActivityEvent,
    GitHubIssue,
    GitHubMonitor,
    _parse_dt,
)
from tests.utils import async_test
```

Then **append** these helpers and tests to the end of the file:

```python
def _mock_response(json_value: object) -> MagicMock:
    """Build a mock aiohttp response usable as an async context manager."""
    resp = MagicMock()
    resp.json = AsyncMock(return_value=json_value)
    resp.raise_for_status = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@async_test
async def test_start_and_close_session_sets_auth_header(
    monitor: GitHubMonitor,
) -> None:
    await monitor.start_session()
    assert monitor._session is not None
    assert monitor._session.headers["Authorization"] == "Bearer t"
    await monitor.close_session()
    assert monitor._session is None


@async_test
async def test_start_session_without_token_omits_auth() -> None:
    m = GitHubMonitor(repo="a/b", token="", started_at=START)  # noqa: S106
    await m.start_session()
    assert "Authorization" not in m._session.headers  # type: ignore[union-attr]
    await m.close_session()


@async_test
async def test_fetch_updated_issues_single_page(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.get = MagicMock(return_value=_mock_response([_issue()]))
    monitor._session = session
    issues = await monitor._fetch_updated_issues(since=START)
    assert len(issues) == 1
    _, kwargs = session.get.call_args
    assert kwargs["params"]["since"] == "2026-07-03T00:00:00Z"


@async_test
async def test_fetch_updated_issues_no_session_returns_empty(
    monitor: GitHubMonitor,
) -> None:
    monitor._session = None
    assert await monitor._fetch_updated_issues(since=None) == []


@async_test
async def test_fetch_updated_issues_paginates(monitor: GitHubMonitor) -> None:
    full_page = [_issue(number=n) for n in range(100)]
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[_mock_response(full_page), _mock_response([_issue()])]
    )
    monitor._session = session
    issues = await monitor._fetch_updated_issues(since=None)
    assert len(issues) == 101
    assert session.get.call_count == 2


@async_test
async def test_fetch_updated_issues_hits_page_cap(
    monitor: GitHubMonitor, caplog: pytest.LogCaptureFixture
) -> None:
    full_page = [_issue(number=n) for n in range(100)]
    session = MagicMock()
    session.get = MagicMock(return_value=_mock_response(full_page))
    monitor._session = session
    with caplog.at_level(logging.WARNING):
        issues = await monitor._fetch_updated_issues(since=None, max_pages=2)
    assert session.get.call_count == 2
    assert len(issues) == 200
    assert any("pagination hit" in r.message for r in caplog.records)


@async_test
async def test_fetch_updated_issues_client_error(
    monitor: GitHubMonitor,
) -> None:
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    monitor._session = session
    assert await monitor._fetch_updated_issues(since=None) == []


@async_test
async def test_get_latest_activity_none_when_empty(
    monitor: GitHubMonitor,
) -> None:
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[])
    ):
        assert await monitor.get_latest_activity() is None


@async_test
async def test_get_latest_activity_open_issue(monitor: GitHubMonitor) -> None:
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[_issue()])
    ):
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.kind == "ISSUE_OPENED"


@async_test
async def test_get_latest_activity_closed_pr(monitor: GitHubMonitor) -> None:
    payload = _issue(
        state="closed", closed_at=AFTER, pull_request={"merged_at": AFTER}
    )
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[payload])
    ):
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.kind == "PR_MERGED"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github.py -k "session or fetch or latest" -q`
Expected: FAIL — `AttributeError`/`ImportError` (methods not defined).

- [ ] **Step 4: Implement fetch, session, and latest-activity**

Add `import aiohttp` to the imports of `lib/github.py` (after `import
datetime`), add `self._session: aiohttp.ClientSession | None = None` to the end
of `__init__`, and add these methods to `GitHubMonitor`:

```python
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
    ) -> list[GitHubIssue]:
        """Fetch issues+PRs updated since `since`, following pagination."""
        if self._session is None:
            return []
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
                break
            if not page_items:
                break
            results.extend(page_items)
            if len(page_items) < per_page:
                break
        else:
            logger.warning(
                "GitHub REST pagination hit max_pages=%d cap", max_pages
            )
        return results

    async def get_latest_activity(self) -> GitHubActivityEvent | None:
        """Return an event for the single most-recently-updated item (no gate)."""
        issues = await self._fetch_updated_issues(
            since=None, max_pages=1, per_page=1
        )
        if not issues:
            return None
        issue = issues[0]
        is_pr = "pull_request" in issue
        if issue.get("state") == "closed":
            kind = self._close_kind(issue, is_pr)
        else:
            kind = self._open_kind(is_pr)
        return self._make_event(kind, issue)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github.py -q`
Expected: PASS (all Task 2 + Task 3 tests green).

- [ ] **Step 6: Format, type-check, and commit**

```bash
uv run ruff format lib/github.py tests/test_github.py
uv run ruff check lib/github.py tests/test_github.py
uv run pyrefly check
git add lib/github.py tests/test_github.py pyproject.toml uv.lock
git commit -m "Add async REST fetch and session lifecycle to GitHub monitor"
```

---

## Task 4: GraphQL linkage and `get_new_events` orchestration

**Files:**

- Modify: `lib/github.py`
- Test: `tests/test_github.py`

**Interfaces:**

- Consumes: `_derive_events` (Task 2), `_fetch_updated_issues` (Task 3),
  `config.GITHUB.EVENTS.*` (Task 1).
- Produces:
   - `async GitHubMonitor._resolve_linked_issues(self, pr_number: int) ->
     list[int]`
   - `GitHubMonitor._toggle_on(self, kind: str) -> bool`
   - `async GitHubMonitor.get_new_events(self) -> list[GitHubActivityEvent]`
     (fetch → derive → seen-gate → toggle → combine linked closes). Combined PR
     events carry closed issues in `linked_issues`; combined issue-close events
     are excluded from the standalone list. Sorted by `(number, kind)`.

- [ ] **Step 1: Write failing tests for linkage and orchestration**

Append to `tests/test_github.py`:

```python
def _pr(number: int, merged: bool = True) -> GitHubIssue:
    return _issue(
        number=number,
        title=f"PR {number}",
        html_url=f"https://github.com/JamesTurland/JimsGarage/pull/{number}",
        state="closed",
        created_at=BEFORE,
        closed_at=AFTER,
        pull_request={"merged_at": AFTER if merged else None},
    )


def _closed_issue(number: int) -> GitHubIssue:
    return _issue(
        number=number,
        state="closed",
        created_at=BEFORE,
        closed_at=AFTER,
        state_reason="completed",
    )


def test_toggle_on_reads_config(monitor: GitHubMonitor) -> None:
    assert monitor._toggle_on("PR_MERGED") is True


@async_test
async def test_resolve_linked_issues_parses_nodes(
    monitor: GitHubMonitor,
) -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "closingIssuesReferences": {"nodes": [{"number": 40}]}
                }
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    assert await monitor._resolve_linked_issues(42) == [40]


@async_test
async def test_resolve_linked_issues_no_token_returns_empty() -> None:
    m = GitHubMonitor(repo="a/b", token="", started_at=START)  # noqa: S106
    m._session = MagicMock()
    assert await m._resolve_linked_issues(42) == []


@async_test
async def test_resolve_linked_issues_no_pr_node(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_mock_response({"data": {"repository": {"pullRequest": None}}})
    )
    monitor._session = session
    assert await monitor._resolve_linked_issues(42) == []


@async_test
async def test_resolve_linked_issues_client_error(
    monitor: GitHubMonitor,
) -> None:
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    monitor._session = session
    assert await monitor._resolve_linked_issues(42) == []


@async_test
async def test_get_new_events_seen_gate(monitor: GitHubMonitor) -> None:
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[_issue()])
    ):
        first = await monitor.get_new_events()
        second = await monitor.get_new_events()
    assert [e.kind for e in first] == ["ISSUE_OPENED"]
    assert second == []  # already seen


@async_test
async def test_get_new_events_toggle_filter(
    monitor: GitHubMonitor, mock_config: MagicMock
) -> None:
    mock_config.GITHUB.EVENTS.ISSUE_OPENED = False
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[_issue()])
    ):
        assert await monitor.get_new_events() == []


@async_test
async def test_get_new_events_combines_linked_close(
    monitor: GitHubMonitor,
) -> None:
    items = [_pr(42), _closed_issue(40)]
    with (
        patch.object(
            monitor, "_fetch_updated_issues", new=AsyncMock(return_value=items)
        ),
        patch.object(
            monitor, "_resolve_linked_issues", new=AsyncMock(return_value=[40])
        ),
    ):
        events = await monitor.get_new_events()
    assert len(events) == 1
    assert events[0].kind == "PR_MERGED"
    assert [i.number for i in events[0].linked_issues] == [40]


@async_test
async def test_get_new_events_no_link_posts_separately(
    monitor: GitHubMonitor,
) -> None:
    items = [_pr(42), _closed_issue(40)]
    with (
        patch.object(
            monitor, "_fetch_updated_issues", new=AsyncMock(return_value=items)
        ),
        patch.object(
            monitor, "_resolve_linked_issues", new=AsyncMock(return_value=[])
        ),
    ):
        events = await monitor.get_new_events()
    assert {e.kind for e in events} == {"PR_MERGED", "ISSUE_COMPLETED"}
    assert all(e.linked_issues == () for e in events)


@async_test
async def test_get_new_events_pr_toggle_off_falls_back(
    monitor: GitHubMonitor, mock_config: MagicMock
) -> None:
    mock_config.GITHUB.EVENTS.PR_MERGED = False
    items = [_pr(42), _closed_issue(40)]
    with (
        patch.object(
            monitor, "_fetch_updated_issues", new=AsyncMock(return_value=items)
        ),
        patch.object(
            monitor, "_resolve_linked_issues", new=AsyncMock(return_value=[40])
        ),
    ):
        events = await monitor.get_new_events()
    # PR dropped by toggle; issue close is NOT combined, posts standalone
    assert [e.kind for e in events] == ["ISSUE_COMPLETED"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github.py -k "linked or new_events or toggle" -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement linkage and orchestration**

Add `from dataclasses import dataclass, replace` (update the existing
`dataclass` import line to also import `replace`) and add these methods to
`GitHubMonitor`:

```python
    def _toggle_on(self, kind: str) -> bool:
        """Return True if the config toggle for this event kind is enabled."""
        return bool(getattr(config.GITHUB.EVENTS, kind))

    async def _resolve_linked_issues(self, pr_number: int) -> list[int]:
        """Return issue numbers this PR officially closes (GraphQL)."""
        if not self._token or self._session is None:
            return []
        owner, _, name = self._repo.partition("/")
        query = (
            "query($owner:String!,$name:String!,$number:Int!){"
            "repository(owner:$owner,name:$name){"
            "pullRequest(number:$number){"
            "closingIssuesReferences(first:20){nodes{number}}}}}"
        )
        payload = {
            "query": query,
            "variables": {"owner": owner, "name": name, "number": pr_number},
        }
        try:
            async with self._session.post(
                GITHUB_GRAPHQL_URL, json=payload
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError:
            logger.exception("GraphQL request failed for PR #%d", pr_number)
            return []
        repository = (data or {}).get("data", {}).get("repository") or {}
        pull_request = repository.get("pullRequest") or {}
        refs = pull_request.get("closingIssuesReferences") or {}
        nodes = refs.get("nodes") or []
        return [n["number"] for n in nodes if "number" in n]

    async def get_new_events(self) -> list[GitHubActivityEvent]:
        """Poll, derive, gate, combine linked closes, and return postables."""
        poll_time = datetime.datetime.now(tz=datetime.UTC)
        issues = await self._fetch_updated_issues(since=self._last_checked)
        derived = self._derive_events(issues)
        fresh = [e for e in derived if e.key not in self._seen]
        for event in fresh:
            self._seen.add(event.key)
        self._last_checked = poll_time

        issue_closes = {
            e.number: e
            for e in fresh
            if not e.is_pr and e.kind in _ISSUE_CLOSE_KINDS
        }
        combined_numbers: set[int] = set()
        plan: list[GitHubActivityEvent] = []

        for event in fresh:
            if event.is_pr and event.kind in _PR_CLOSE_KINDS:
                if not self._toggle_on(event.kind):
                    continue
                linked_nums = await self._resolve_linked_issues(event.number)
                linked = [
                    issue_closes[n] for n in linked_nums if n in issue_closes
                ]
                combined_numbers.update(i.number for i in linked)
                plan.append(replace(event, linked_issues=tuple(linked)))

        for event in fresh:
            if event.is_pr and event.kind in _PR_CLOSE_KINDS:
                continue
            if event.number in combined_numbers and event.kind in _ISSUE_CLOSE_KINDS:
                continue
            if not self._toggle_on(event.kind):
                continue
            plan.append(event)

        plan.sort(key=lambda e: (e.number, e.kind))
        return plan
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github.py -q`
Expected: PASS (all github tests green).

- [ ] **Step 5: Verify 100% coverage of `lib/github.py`**

Run: `uv run pytest tests/test_github.py --cov=lib.github --cov-branch
--cov-report=term-missing -q`
Expected: `lib/github.py` shows 100% (no missing lines/branches). If any line is
missing, add a targeted test before committing.

- [ ] **Step 6: Format, type-check, and commit**

```bash
uv run ruff format lib/github.py tests/test_github.py
uv run ruff check lib/github.py tests/test_github.py
uv run pyrefly check
git add lib/github.py tests/test_github.py
git commit -m "Add GraphQL linkage and event orchestration to GitHub monitor"
```

---

## Task 5: Cog wiring — loop, bootstrap, and embed builder

**Files:**

- Modify: `lib/cogs/tasks.py`
- Test: `tests/cogs/test_tasks.py`

**Interfaces:**

- Consumes: `GitHubMonitor` (`start_session`, `close_session`,
  `get_new_events`, `get_latest_activity`), `GitHubActivityEvent`,
  `EVENT_RENDER` (Tasks 2–4); `config.CHANNELS.GITHUB`,
  `config.CHANNELS.BOT_PLAYGROUND`, `config.DRY_RUN_GITHUB`,
  `config.GITHUB.REPO`, `config.GITHUB.TOKEN`, `config.GITHUB.POLL_MINUTES`.
- Produces on the `Tasks` cog:
   - attribute `self.github_monitor: GitHubMonitor | None`
   - `@tasks.loop(minutes=5) async def monitor_github_activity(self) -> None`
   - `@monitor_github_activity.before_loop async def
     before_monitor_github_activity(self) -> None`
   - `def _build_github_embed(self, event: GitHubActivityEvent) ->
     discord.Embed`

- [ ] **Step 1: Extend the `tasks_cog` fixture**

In `tests/cogs/test_tasks.py`, inside the `tasks_cog` fixture (after the
`cog.monitor_youtube_videos.is_running = ...` line), add:

```python
        cog.monitor_github_activity.start = MagicMock()
        cog.monitor_github_activity.cancel = MagicMock()
        cog.monitor_github_activity.is_running = MagicMock(return_value=False)
```

- [ ] **Step 2: Write failing tests for the loop and embed**

First add `from lib.github import GitHubActivityEvent` to the top import block
of `tests/cogs/test_tasks.py` (first-party group, after
`from lib.cogs.tasks import Tasks`). Then add this module-level helper and test
class:

```python
def _gh_event(
    kind: str = "PR_MERGED",
    number: int = 42,
    *,
    title: str = "Fix things",
    url: str = "https://github.com/JamesTurland/JimsGarage/pull/42",
    author_login: str = "octocat",
    author_avatar_url: str = "https://avatars/1",
    is_pr: bool = True,
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

        with patch(
            "lib.github.GitHubMonitor", return_value=fake_monitor
        ):
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
        mock_config: MagicMock,
    ) -> None:
        with patch("discord.ext.tasks.Loop.start"), caplog.at_level(
            logging.WARNING
        ):
            cog = Tasks(discord_bot)
            with patch.object(cog, "monitor_github_activity") as mock_task:
                mock_task.is_running.return_value = True
                Tasks.__init__(cog, discord_bot)
        assert any(
            "monitor_github_activity task is already running" in r.message
            for r in caplog.records
        )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/cogs/test_tasks.py -k GitHub -q`
Expected: FAIL — `AttributeError` (`monitor_github_activity` /
`_build_github_embed` not defined).

- [ ] **Step 4: Wire the cog in `lib/cogs/tasks.py`**

Add the import near the top (with the other `from lib import ...` imports):

```python
from lib import github, youtube
```

(Replace the existing `from lib import youtube` line.)

In `__init__`, after the YouTube bootstrap block, add:

```python
        # Bootstrap task: GitHub Activity Monitor
        if not self.monitor_github_activity.is_running():
            self.github_monitor: github.GitHubMonitor | None = None
            self.monitor_github_activity.start()
        else:
            logger.warning("monitor_github_activity task is already running")
```

In `cog_unload`, after the YouTube cancel, add:

```python
        # Close task: GitHub Activity Monitor
        self.monitor_github_activity.cancel()
        if self.github_monitor is not None:
            await self.github_monitor.close_session()
```

Add these methods to the cog (place after `before_monitor_youtube_videos`):

```python
    @tasks.loop(minutes=5)
    async def monitor_github_activity(self) -> None:
        """Poll GitHub for new issue/PR activity and post to the channel."""
        if self.github_monitor is None:
            logger.warning("GitHub monitor not initialized, skipping run")
            return

        new_events = await self.github_monitor.get_new_events()
        if not new_events:
            logger.debug("No new GitHub activity found")
            return

        logger.info("New GitHub activity found: %d event(s)", len(new_events))
        await self.bot.log_bot_event(
            event="Task - GitHub Activity Monitor",
            details=f"{len(new_events)} new GitHub event(s)",
        )

        if config.DRY_RUN_GITHUB:
            channel = self.bot.get_channel(config.CHANNELS.BOT_PLAYGROUND)
        else:
            channel = self.bot.get_channel(config.CHANNELS.GITHUB)

        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "GitHub channel %s not found or not a TextChannel",
                config.CHANNELS.BOT_PLAYGROUND
                if config.DRY_RUN_GITHUB
                else config.CHANNELS.GITHUB,
            )
            return

        for event in new_events:
            await channel.send(embed=self._build_github_embed(event))

    def _build_github_embed(
        self, event: github.GitHubActivityEvent
    ) -> discord.Embed:
        """Build a compact embed for a GitHub activity event."""
        emoji, color, verb = github.EVENT_RENDER[event.kind]
        embed = discord.Embed(
            title=f"{emoji} {verb} #{event.number}",
            description=f"**[{event.title}]({event.url})**",
            color=discord.Color(color),
        )
        embed.set_author(name=event.author_login)
        if event.author_avatar_url:
            embed.set_thumbnail(url=event.author_avatar_url)
        embed.set_footer(text=config.GITHUB.REPO)
        if event.linked_issues:
            linked = "\n".join(
                f"• [#{issue.number}]({issue.url}) {issue.title}"
                for issue in event.linked_issues
            )
            embed.add_field(name="Closed issues", value=linked, inline=False)
        return embed

    @monitor_github_activity.before_loop
    async def before_monitor_github_activity(self) -> None:
        """Initialize the monitor, honor the configured interval, smoke-test."""
        logger.info("monitor_github_activity task is starting up...")
        started_at = datetime.datetime.now(tz=datetime.UTC)
        self.github_monitor = github.GitHubMonitor(
            repo=config.GITHUB.REPO,
            token=config.GITHUB.TOKEN,
            started_at=started_at,
        )
        await self.github_monitor.start_session()
        self.monitor_github_activity.change_interval(
            minutes=config.GITHUB.POLL_MINUTES
        )
        await self.bot.wait_until_ready()

        if config.DRY_RUN_GITHUB:
            channel = self.bot.get_channel(config.CHANNELS.BOT_PLAYGROUND)
            if isinstance(channel, discord.TextChannel):
                latest = await self.github_monitor.get_latest_activity()
                if latest is not None:
                    await channel.send(embed=self._build_github_embed(latest))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/cogs/test_tasks.py -q`
Expected: PASS (existing + new GitHub loop tests green).

- [ ] **Step 6: Run the full suite with coverage**

Run: `uv run pytest -q`
Expected: PASS with 100% coverage (`--cov-fail-under=100` does not trip). If a
branch is uncovered, add a targeted test.

- [ ] **Step 7: Format, type-check, and commit**

```bash
uv run ruff format lib/cogs/tasks.py tests/cogs/test_tasks.py
uv run ruff check lib/cogs/tasks.py tests/cogs/test_tasks.py
uv run pyrefly check
git add lib/cogs/tasks.py tests/cogs/test_tasks.py
git commit -m "Wire GitHub activity monitor into the tasks cog"
```

---

## Task 6: Version bump and Kubernetes manifest

**Files:**

- Modify: `pyproject.toml`
- Modify: `kubernetes/discordbot.yaml`

**Interfaces:**

- Consumes: nothing new.
- Produces: released version `0.10.0`; `GITHUB_TOKEN` + `DRY_RUN_GITHUB`
  container env.

- [ ] **Step 1: Bump the version in `pyproject.toml`**

Change `version = "0.9.5"` to `version = "0.10.0"`.

- [ ] **Step 2: Update the image tag in `kubernetes/discordbot.yaml`**

Change `image: ghcr.io/cyberops7/discord_bot:v0.9.5` to
`image: ghcr.io/cyberops7/discord_bot:v0.10.0`.

- [ ] **Step 3: Add the token secret and dry-run env**

In the container `env:` list, add a `GITHUB_TOKEN` entry mirroring `BOT_TOKEN`
and a `DRY_RUN_GITHUB` entry mirroring `DRY_RUN_YOUTUBE`:

```yaml
            - name: GITHUB_TOKEN
              valueFrom:
                secretKeyRef:
                  name: bot-secrets
                  key: GITHUB_TOKEN
            - name: DRY_RUN_GITHUB
              value: "false"
```

Note (out of band, not a file change): the `GITHUB_TOKEN` key must be added to
the `bot-secrets` Secret in the cluster before rollout.

- [ ] **Step 4: Verify all checks pass**

Run: `uv run invoke check`
Expected: all checks pass (ruff, pyrefly, bandit, hadolint, markdownlint,
yamllint, shellcheck, trivy).

Run: `uv run pytest -q`
Expected: PASS with 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml kubernetes/discordbot.yaml
git commit -m "Bump version to 0.10.0 and wire GITHUB_TOKEN for deploy"
```

---

## Self-Review

**Spec coverage:**

- Events opened/closed for issues + PRs, each config-toggleable → Task 1
  (config), Task 2 (derivation), Task 4 (toggle filtering). ✓
- PR merged vs closed-unmerged; issue completed vs not-planned → Task 2
  (`_close_kind`), Task 5 (`EVENT_RENDER`). ✓
- GraphQL authoritative linkage, combine only when closed in same cycle, never
  infer → Task 4 (`_resolve_linked_issues`, `get_new_events` combine). ✓
- Two-gate new-event model (timestamp > startup, seen-set) → Task 2 (timestamp
  gate), Task 4 (seen gate). ✓
- Compact embed, no `@everyone` → Task 5 (`_build_github_embed`, `channel.send`
  with no content mention). ✓
- `DRY_RUN_GITHUB` redirect + startup smoke post → Task 5. ✓
- Config singleton + env override + `sample.env` → Task 1. ✓
- aiohttp session lifecycle → Task 3 (`start_session`/`close_session`), Task 5
  (`cog_unload`). ✓
- `POLL_MINUTES` via `change_interval` → Task 5 (`before_loop`). ✓
- conftest mock updates → Task 1. ✓
- TypedDicts for pyrefly strict → Task 2. ✓
- Version + k8s + `GITHUB_TOKEN` secret → Task 6. ✓
- 100% coverage gates → Tasks 4 and 5 (explicit coverage steps). ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every
code step shows full code; every test step shows real assertions. ✓

**Type consistency:** `GitHubActivityEvent` fields, method signatures
(`get_new_events`, `_resolve_linked_issues`, `_fetch_updated_issues`,
`_build_github_embed`), and kind strings (`ISSUE_OPENED`, `ISSUE_COMPLETED`,
`ISSUE_NOT_PLANNED`, `PR_OPENED`, `PR_MERGED`, `PR_CLOSED`) are identical across
Tasks 1–6 and match `EVENT_RENDER` and the config `EVENTS` keys. ✓
