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
        (
            {"state": "closed", "closed_at": AFTER, "state_reason": "completed"},
            "ISSUE_COMPLETED",
        ),
        (
            {"state": "closed", "closed_at": AFTER, "state_reason": None},
            "ISSUE_COMPLETED",
        ),
        (
            {"state": "closed", "closed_at": AFTER, "state_reason": "not_planned"},
            "ISSUE_NOT_PLANNED",
        ),
        (
            {"state": "closed", "closed_at": AFTER, "state_reason": "duplicate"},
            "ISSUE_NOT_PLANNED",
        ),
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
        [
            _issue(
                created_at=BEFORE, state="closed", closed_at=AFTER, pull_request=pr_ref
            )
        ]
    )
    assert [e.kind for e in events] == [expected]


def test_derive_open_and_close_same_poll(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events(
        [_issue(state="closed", closed_at=AFTER, state_reason="completed")]
    )
    assert {e.kind for e in events} == {"ISSUE_OPENED", "ISSUE_COMPLETED"}


def test_derive_ignores_close_before_startup(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events(
        [
            _issue(
                created_at=BEFORE,
                state="closed",
                closed_at=BEFORE,
                state_reason="completed",
            )
        ]
    )
    assert events == []


def test_event_render_covers_all_kinds() -> None:
    assert set(EVENT_RENDER) == {
        "ISSUE_OPENED",
        "ISSUE_COMPLETED",
        "ISSUE_NOT_PLANNED",
        "PR_OPENED",
        "PR_MERGED",
        "PR_CLOSED",
    }


def test_make_event_missing_user(monitor: GitHubMonitor) -> None:
    events = monitor._derive_events([_issue(user=None)])
    assert events[0].author_login == ""
    assert events[0].author_avatar_url == ""


def test_event_is_frozen() -> None:
    event = GitHubActivityEvent(
        key="k",
        kind="ISSUE_OPENED",
        number=1,
        title="t",
        url="u",
        author_login="a",
        author_avatar_url="",
        is_pr=False,
    )
    with pytest.raises(AttributeError):
        setattr(event, "number", 2)  # noqa: B010


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
    m = GitHubMonitor(repo="a/b", token="", started_at=START)
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
    with patch.object(monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[])):
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
    payload = _issue(state="closed", closed_at=AFTER, pull_request={"merged_at": AFTER})
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[payload])
    ):
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.kind == "PR_MERGED"


@async_test
async def test_close_session_when_already_none(monitor: GitHubMonitor) -> None:
    monitor._session = None
    await monitor.close_session()
    assert monitor._session is None


@async_test
async def test_fetch_updated_issues_empty_page_stops(
    monitor: GitHubMonitor,
) -> None:
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[_mock_response([_issue()]), _mock_response([])]
    )
    monitor._session = session
    issues = await monitor._fetch_updated_issues(since=None, per_page=1)
    assert len(issues) == 1
    assert session.get.call_count == 2
