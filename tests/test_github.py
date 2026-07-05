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
    _PRCloseDetails,
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


def test_closer_from_actor_extracts_login_and_avatar() -> None:
    assert GitHubMonitor._closer_from_actor(
        {"login": "closer", "avatarUrl": "https://avatars/2"}
    ) == ("closer", "https://avatars/2")


def test_closer_from_actor_none_returns_empty() -> None:
    assert GitHubMonitor._closer_from_actor(None) == ("", "")


def test_closer_from_actor_missing_fields_returns_empty() -> None:
    assert GitHubMonitor._closer_from_actor({}) == ("", "")


def test_event_has_closer_defaults(monitor: GitHubMonitor) -> None:
    event = monitor._make_event("ISSUE_OPENED", _issue())
    assert event.closer_login == ""
    assert event.closer_avatar_url == ""


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
    assert issues is not None
    assert len(issues) == 1
    _, kwargs = session.get.call_args
    assert kwargs["params"]["since"] == "2026-07-03T00:00:00Z"


@async_test
async def test_fetch_updated_issues_no_session_returns_none(
    monitor: GitHubMonitor,
) -> None:
    monitor._session = None
    assert await monitor._fetch_updated_issues(since=None) is None


@async_test
async def test_fetch_updated_issues_paginates(monitor: GitHubMonitor) -> None:
    full_page = [_issue(number=n) for n in range(100)]
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[_mock_response(full_page), _mock_response([_issue()])]
    )
    monitor._session = session
    issues = await monitor._fetch_updated_issues(since=None)
    assert issues is not None
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
    assert issues is not None
    assert len(issues) == 200
    assert any("pagination hit" in r.message for r in caplog.records)


@async_test
async def test_fetch_updated_issues_client_error_returns_none(
    monitor: GitHubMonitor,
) -> None:
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    monitor._session = session
    assert await monitor._fetch_updated_issues(since=None) is None


@async_test
async def test_fetch_updated_issues_client_error_midway_returns_none(
    monitor: GitHubMonitor,
) -> None:
    full_page = [_issue(number=n) for n in range(100)]
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[_mock_response(full_page), aiohttp.ClientError("boom")]
    )
    monitor._session = session
    assert await monitor._fetch_updated_issues(since=None) is None
    assert session.get.call_count == 2


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
    ) as fetch_mock:
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.kind == "ISSUE_OPENED"
    fetch_mock.assert_called_once_with(since=None, max_pages=1, per_page=1)


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
    assert issues is not None
    assert len(issues) == 1
    assert session.get.call_count == 2


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
async def test_resolve_pr_details_parses_linked(monitor: GitHubMonitor) -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "mergedBy": None,
                    "closingIssuesReferences": {"nodes": [{"number": 40}]},
                    "timelineItems": {"nodes": []},
                }
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=False)
    assert details.linked_issue_numbers == (40,)


@async_test
async def test_resolve_pr_details_no_token_returns_empty() -> None:
    m = GitHubMonitor(repo="a/b", token="", started_at=START)
    m._session = MagicMock()
    details = await m._resolve_pr_close_details(42, is_merge=True)
    assert details == _PRCloseDetails((), "", "")


@async_test
async def test_resolve_pr_details_no_pr_node(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_mock_response({"data": {"repository": {"pullRequest": None}}})
    )
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=True)
    assert details == _PRCloseDetails((), "", "")


@async_test
async def test_resolve_pr_details_data_null(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response({"data": None}))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=True)
    assert details == _PRCloseDetails((), "", "")


@async_test
async def test_resolve_pr_details_skips_nodes_without_number(
    monitor: GitHubMonitor,
) -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "mergedBy": None,
                    "closingIssuesReferences": {
                        "nodes": [{"number": 40}, {"title": "no number"}]
                    },
                    "timelineItems": {"nodes": []},
                }
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=False)
    assert details.linked_issue_numbers == (40,)


@async_test
async def test_resolve_pr_details_client_error(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=True)
    assert details == _PRCloseDetails((), "", "")


@async_test
async def test_resolve_pr_details_merged_uses_mergedby(
    monitor: GitHubMonitor,
) -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "mergedBy": {"login": "merger", "avatarUrl": "https://avatars/9"},
                    "closingIssuesReferences": {"nodes": []},
                    "timelineItems": {
                        "nodes": [{"actor": {"login": "other", "avatarUrl": "x"}}]
                    },
                }
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=True)
    assert (details.closer_login, details.closer_avatar_url) == (
        "merger",
        "https://avatars/9",
    )


@async_test
async def test_resolve_pr_details_closed_uses_timeline(
    monitor: GitHubMonitor,
) -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "mergedBy": None,
                    "closingIssuesReferences": {"nodes": []},
                    "timelineItems": {
                        "nodes": [
                            {"actor": {"login": "closer", "avatarUrl": "https://a/3"}}
                        ]
                    },
                }
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=False)
    assert (details.closer_login, details.closer_avatar_url) == (
        "closer",
        "https://a/3",
    )


@async_test
async def test_resolve_pr_details_closed_empty_timeline(
    monitor: GitHubMonitor,
) -> None:
    data = {
        "data": {
            "repository": {
                "pullRequest": {
                    "mergedBy": None,
                    "closingIssuesReferences": {"nodes": []},
                    "timelineItems": {"nodes": []},
                }
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    details = await monitor._resolve_pr_close_details(42, is_merge=False)
    assert (details.closer_login, details.closer_avatar_url) == ("", "")


@async_test
async def test_resolve_pr_details_logs_graphql_errors(
    monitor: GitHubMonitor, caplog: pytest.LogCaptureFixture
) -> None:
    data = {"data": {"repository": None}, "errors": [{"type": "RATE_LIMITED"}]}
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    with caplog.at_level(logging.WARNING):
        details = await monitor._resolve_pr_close_details(42, is_merge=True)
    assert details == _PRCloseDetails((), "", "")
    assert any("GraphQL errors" in r.message for r in caplog.records)


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
            monitor,
            "_resolve_pr_close_details",
            new=AsyncMock(return_value=_PRCloseDetails((40,), "merger", "https://a/9")),
        ),
    ):
        events = await monitor.get_new_events()
    assert len(events) == 1
    pr_event = next(e for e in events if e.is_pr)
    assert [i.number for i in pr_event.linked_issues] == [40]
    assert pr_event.closer_login == "merger"


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
            monitor,
            "_resolve_pr_close_details",
            new=AsyncMock(return_value=_PRCloseDetails((), "", "")),
        ),
        patch.object(monitor, "_resolve_issue_closers", new=AsyncMock(return_value={})),
    ):
        events = await monitor.get_new_events()
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
            monitor,
            "_resolve_pr_close_details",
            new=AsyncMock(return_value=_PRCloseDetails((40,), "merger", "https://a/9")),
        ),
        patch.object(monitor, "_resolve_issue_closers", new=AsyncMock(return_value={})),
    ):
        events = await monitor.get_new_events()
    # PR toggled off -> issue #40 posts on its own (not combined)
    assert [e.kind for e in events] == ["ISSUE_COMPLETED"]


@async_test
async def test_get_new_events_fetch_failure_keeps_cursor(
    monitor: GitHubMonitor,
) -> None:
    before = monitor._last_checked
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=None)
    ):
        result = await monitor.get_new_events()
    assert result == []
    assert monitor._last_checked == before


@async_test
async def test_resolve_issue_closers_empty_returns_empty(
    monitor: GitHubMonitor,
) -> None:
    assert await monitor._resolve_issue_closers([]) == {}


@async_test
async def test_resolve_issue_closers_no_session(monitor: GitHubMonitor) -> None:
    monitor._session = None
    assert await monitor._resolve_issue_closers([40]) == {}


@async_test
async def test_resolve_issue_closers_no_token() -> None:
    m = GitHubMonitor(repo="a/b", token="", started_at=START)
    m._session = MagicMock()
    assert await m._resolve_issue_closers([40]) == {}


@async_test
async def test_resolve_issue_closers_parses_aliases(
    monitor: GitHubMonitor,
) -> None:
    data = {
        "data": {
            "repository": {
                "i40": {
                    "timelineItems": {
                        "nodes": [
                            {"actor": {"login": "alice", "avatarUrl": "https://a/1"}}
                        ]
                    }
                },
                "i41": {"timelineItems": {"nodes": []}},
            }
        }
    }
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    result = await monitor._resolve_issue_closers([40, 41])
    assert result == {40: ("alice", "https://a/1"), 41: ("", "")}


@async_test
async def test_resolve_issue_closers_builds_aliased_query(
    monitor: GitHubMonitor,
) -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response({"data": {"repository": {}}}))
    monitor._session = session
    await monitor._resolve_issue_closers([40, 41])
    sent_query = session.post.call_args.kwargs["json"]["query"]
    assert "i40:issue(number:40)" in sent_query
    assert "i41:issue(number:41)" in sent_query
    assert "CLOSED_EVENT" in sent_query


@async_test
async def test_resolve_issue_closers_client_error(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    monitor._session = session
    assert await monitor._resolve_issue_closers([40]) == {}


@async_test
async def test_resolve_issue_closers_logs_graphql_errors(
    monitor: GitHubMonitor, caplog: pytest.LogCaptureFixture
) -> None:
    data = {"data": {"repository": {}}, "errors": [{"type": "FORBIDDEN"}]}
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response(data))
    monitor._session = session
    with caplog.at_level(logging.WARNING):
        result = await monitor._resolve_issue_closers([40])
    assert result == {40: ("", "")}
    assert any("GraphQL errors" in r.message for r in caplog.records)


@async_test
async def test_get_new_events_populates_issue_closer(
    monitor: GitHubMonitor,
) -> None:
    with (
        patch.object(
            monitor,
            "_fetch_updated_issues",
            new=AsyncMock(return_value=[_closed_issue(40)]),
        ),
        patch.object(
            monitor,
            "_resolve_issue_closers",
            new=AsyncMock(return_value={40: ("closer", "https://a/2")}),
        ),
    ):
        events = await monitor.get_new_events()
    assert len(events) == 1
    assert events[0].closer_login == "closer"
    assert events[0].closer_avatar_url == "https://a/2"


@async_test
async def test_resolve_closer_non_close_returns_empty(
    monitor: GitHubMonitor,
) -> None:
    event = monitor._make_event("ISSUE_OPENED", _issue())
    assert await monitor._resolve_closer(event) == ("", "")


@async_test
async def test_get_latest_activity_resolves_pr_closer(
    monitor: GitHubMonitor,
) -> None:
    payload = _issue(state="closed", closed_at=AFTER, pull_request={"merged_at": AFTER})
    with (
        patch.object(
            monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[payload])
        ),
        patch.object(
            monitor,
            "_resolve_pr_close_details",
            new=AsyncMock(return_value=_PRCloseDetails((), "merger", "https://a/9")),
        ),
    ):
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.closer_login == "merger"
    assert event.closer_avatar_url == "https://a/9"


@async_test
async def test_get_latest_activity_resolves_issue_closer(
    monitor: GitHubMonitor,
) -> None:
    payload = _closed_issue(40)
    with (
        patch.object(
            monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[payload])
        ),
        patch.object(
            monitor,
            "_resolve_issue_closers",
            new=AsyncMock(return_value={40: ("closer", "https://a/2")}),
        ),
    ):
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.closer_login == "closer"


@async_test
async def test_get_latest_activity_open_has_no_closer(
    monitor: GitHubMonitor,
) -> None:
    with patch.object(
        monitor, "_fetch_updated_issues", new=AsyncMock(return_value=[_issue()])
    ):
        event = await monitor.get_latest_activity()
    assert event is not None
    assert event.closer_login == ""
