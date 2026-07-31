"""Unit tests for the github.py module"""

import datetime
import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from lib.github import (
    _PR_REVIEW_KINDS,
    _REVIEW_STATE_TO_KIND,
    _REVIEWS_PER_PR,
    EVENT_RENDER,
    GitHubActivityEvent,
    GitHubIssue,
    GitHubMonitor,
    _parse_dt,
    _PRCloseDetails,
    _ReviewNode,
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
        "PR_REVIEW_CHANGES_REQUESTED",
        "PR_REVIEW_APPROVED",
        "PR_REVIEW_COMMENTED",
    }


def test_review_kinds_have_render_metadata() -> None:
    assert set(EVENT_RENDER) >= _PR_REVIEW_KINDS


def test_review_state_to_kind_mapping() -> None:
    assert _REVIEW_STATE_TO_KIND == {
        "CHANGES_REQUESTED": "PR_REVIEW_CHANGES_REQUESTED",
        "APPROVED": "PR_REVIEW_APPROVED",
        "COMMENTED": "PR_REVIEW_COMMENTED",
    }
    assert _REVIEWS_PER_PR == 50


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


def test_closer_from_actor_non_string_values_returns_empty() -> None:
    assert GitHubMonitor._closer_from_actor({"login": 42, "avatarUrl": []}) == ("", "")


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
async def test_resolve_pr_details_closed_selects_last_timeline_node(
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
                            {
                                "actor": {
                                    "login": "old_closer",
                                    "avatarUrl": "https://a/old",
                                }
                            },
                            {
                                "actor": {
                                    "login": "new_closer",
                                    "avatarUrl": "https://a/new",
                                }
                            },
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
        "new_closer",
        "https://a/new",
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
async def test_get_new_events_includes_reviews(monitor: GitHubMonitor) -> None:
    # Open PR created before startup → no open/close event, only its review.
    with (
        patch.object(
            monitor,
            "_fetch_updated_issues",
            new=AsyncMock(return_value=[_open_pr(42)]),
        ),
        patch.object(
            monitor,
            "_fetch_pr_reviews",
            new=AsyncMock(return_value={42: [_review_node(database_id=1)]}),
        ),
    ):
        events = await monitor.get_new_events()
    assert [e.kind for e in events] == ["PR_REVIEW_CHANGES_REQUESTED"]


@async_test
async def test_get_new_events_closed_pr_not_reviewed(
    monitor: GitHubMonitor,
) -> None:
    fetch_reviews = AsyncMock(return_value={})
    with (
        patch.object(
            monitor,
            "_fetch_updated_issues",
            new=AsyncMock(return_value=[_pr(42, merged=False)]),
        ),
        patch.object(monitor, "_fetch_pr_reviews", new=fetch_reviews),
        patch.object(
            monitor,
            "_resolve_pr_close_details",
            new=AsyncMock(return_value=_PRCloseDetails((), "", "")),
        ),
    ):
        events = await monitor.get_new_events()
    assert all(not e.kind.startswith("PR_REVIEW") for e in events)
    fetch_reviews.assert_not_awaited()


@async_test
async def test_get_new_events_open_issue_not_reviewed(
    monitor: GitHubMonitor,
) -> None:
    fetch_reviews = AsyncMock(return_value={})
    with (
        patch.object(
            monitor,
            "_fetch_updated_issues",
            new=AsyncMock(return_value=[_issue()]),
        ),
        patch.object(monitor, "_fetch_pr_reviews", new=fetch_reviews),
    ):
        await monitor.get_new_events()
    fetch_reviews.assert_not_awaited()


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
    assert "last:1" in sent_query


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
    assert event.closer_avatar_url == "https://a/2"


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
    assert event.closer_avatar_url == ""


def _reviews_response(
    reviews_by_pr: dict[int, list[dict[str, object]]],
) -> dict[str, object]:
    repo: dict[str, object] = {
        f"pr{n}": {"reviews": {"nodes": nodes}} for n, nodes in reviews_by_pr.items()
    }
    return {"data": {"repository": repo}}


def _raw_review(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "databaseId": 1,
        "state": "CHANGES_REQUESTED",
        "submittedAt": AFTER,
        "url": "https://github.com/o/r/pull/42#pullrequestreview-1",
        "author": {"login": "rev", "avatarUrl": "https://avatars/9"},
    }
    base.update(overrides)
    return base


def test_parse_review_node_valid(monitor: GitHubMonitor) -> None:
    node = monitor._parse_review_node(_raw_review())
    assert node == _ReviewNode(
        database_id=1,
        state="CHANGES_REQUESTED",
        submitted_at=AFTER,
        url="https://github.com/o/r/pull/42#pullrequestreview-1",
        author_login="rev",
        author_avatar_url="https://avatars/9",
    )


def test_parse_review_node_null_author(monitor: GitHubMonitor) -> None:
    node = monitor._parse_review_node(_raw_review(author=None))
    assert node is not None
    assert node.author_login == ""
    assert node.author_avatar_url == ""


def test_parse_review_node_non_string_url(monitor: GitHubMonitor) -> None:
    node = monitor._parse_review_node(_raw_review(url=999))
    assert node is not None
    assert node.url == ""


@pytest.mark.parametrize(
    "raw",
    [
        {"state": "APPROVED", "submittedAt": AFTER},  # no databaseId
        {"databaseId": 1, "submittedAt": AFTER},  # no state
        {"databaseId": 1, "state": "APPROVED"},  # no submittedAt
        {"databaseId": "x", "state": "APPROVED", "submittedAt": AFTER},  # bad id
        "not-a-dict",
    ],
)
def test_parse_review_node_rejects_bad(monitor: GitHubMonitor, raw: object) -> None:
    assert monitor._parse_review_node(raw) is None


@async_test
async def test_fetch_pr_reviews_parses(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_mock_response(_reviews_response({42: [_raw_review()]}))
    )
    monitor._session = session
    result = await monitor._fetch_pr_reviews([42])
    assert result[42][0].database_id == 1
    assert result[42][0].state == "CHANGES_REQUESTED"


@async_test
async def test_fetch_pr_reviews_empty_numbers(monitor: GitHubMonitor) -> None:
    assert await monitor._fetch_pr_reviews([]) == {}


@async_test
async def test_fetch_pr_reviews_no_token() -> None:
    m = GitHubMonitor(repo="a/b", token="", started_at=START)
    m._session = MagicMock()
    assert await m._fetch_pr_reviews([42]) == {}


@async_test
async def test_fetch_pr_reviews_no_session(monitor: GitHubMonitor) -> None:
    monitor._session = None
    assert await monitor._fetch_pr_reviews([42]) == {}


@async_test
async def test_fetch_pr_reviews_client_error(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    monitor._session = session
    assert await monitor._fetch_pr_reviews([42]) == {}


@async_test
async def test_fetch_pr_reviews_logs_graphql_errors(
    monitor: GitHubMonitor, caplog: pytest.LogCaptureFixture
) -> None:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_mock_response({"data": None, "errors": [{"message": "bad"}]})
    )
    monitor._session = session
    with caplog.at_level(logging.WARNING):
        result = await monitor._fetch_pr_reviews([42])
    assert result == {42: []}
    assert any(
        "GraphQL errors resolving PR reviews" in r.message for r in caplog.records
    )


@async_test
async def test_fetch_pr_reviews_missing_pr_node(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=_mock_response({"data": {"repository": {}}}))
    monitor._session = session
    assert await monitor._fetch_pr_reviews([42]) == {42: []}


@async_test
async def test_fetch_pr_reviews_page_cap_warns(
    monitor: GitHubMonitor, caplog: pytest.LogCaptureFixture
) -> None:
    nodes = [_raw_review(databaseId=i) for i in range(_REVIEWS_PER_PR)]
    session = MagicMock()
    session.post = MagicMock(
        return_value=_mock_response(_reviews_response({42: nodes}))
    )
    monitor._session = session
    with caplog.at_level(logging.WARNING):
        result = await monitor._fetch_pr_reviews([42])
    assert len(result[42]) == _REVIEWS_PER_PR
    assert any("review page cap" in r.message for r in caplog.records)


def _review_node(**overrides: object) -> _ReviewNode:
    defaults: dict[str, object] = {
        "database_id": 1,
        "state": "CHANGES_REQUESTED",
        "submitted_at": AFTER,
        "url": "https://github.com/JamesTurland/JimsGarage/pull/42#r1",
        "author_login": "rev",
        "author_avatar_url": "https://avatars/9",
    }
    defaults.update(overrides)
    return _ReviewNode(**defaults)  # type: ignore[arg-type]


def _open_pr(number: int = 42) -> GitHubIssue:
    return _issue(
        number=number,
        title=f"PR {number}",
        html_url=f"https://github.com/JamesTurland/JimsGarage/pull/{number}",
        state="open",
        created_at=BEFORE,
        pull_request={},
    )


@async_test
async def test_derive_review_changes_requested(monitor: GitHubMonitor) -> None:
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(return_value={42: [_review_node()]}),
    ):
        events = await monitor._derive_review_events([_open_pr(42)])
    assert len(events) == 1
    event = events[0]
    assert event.kind == "PR_REVIEW_CHANGES_REQUESTED"
    assert event.number == 42
    assert event.title == "PR 42"
    assert event.url == "https://github.com/JamesTurland/JimsGarage/pull/42#r1"
    assert event.author_login == "rev"
    assert event.key == "review:42:1"
    assert event.is_pr is True


@async_test
async def test_derive_review_empty_prs(monitor: GitHubMonitor) -> None:
    fetch = AsyncMock(return_value={})
    with patch.object(monitor, "_fetch_pr_reviews", new=fetch):
        assert await monitor._derive_review_events([]) == []
    fetch.assert_not_awaited()


@async_test
@pytest.mark.parametrize("bad_state", ["PENDING", "DISMISSED", "WAT"])
async def test_derive_review_ignores_unmapped_state(
    monitor: GitHubMonitor, bad_state: str
) -> None:
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(return_value={42: [_review_node(state=bad_state)]}),
    ):
        assert await monitor._derive_review_events([_open_pr(42)]) == []


@async_test
async def test_derive_review_default_off_suppressed(
    monitor: GitHubMonitor,
) -> None:
    # Real config.yaml defaults PR_REVIEW_APPROVED false.
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(return_value={42: [_review_node(state="APPROVED")]}),
    ):
        assert await monitor._derive_review_events([_open_pr(42)]) == []


@async_test
async def test_derive_review_toggle_on_posts(
    monitor: GitHubMonitor, mock_config: MagicMock
) -> None:
    mock_config.GITHUB.EVENTS.PR_REVIEW_APPROVED = True
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(
            return_value={42: [_review_node(state="APPROVED", database_id=7)]}
        ),
    ):
        events = await monitor._derive_review_events([_open_pr(42)])
    assert [e.kind for e in events] == ["PR_REVIEW_APPROVED"]


@async_test
async def test_derive_review_before_startup_ignored(
    monitor: GitHubMonitor,
) -> None:
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(return_value={42: [_review_node(submitted_at=BEFORE)]}),
    ):
        assert await monitor._derive_review_events([_open_pr(42)]) == []


@async_test
async def test_derive_review_unparseable_submitted_ignored(
    monitor: GitHubMonitor,
) -> None:
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(return_value={42: [_review_node(submitted_at="")]}),
    ):
        assert await monitor._derive_review_events([_open_pr(42)]) == []


@async_test
async def test_derive_review_dedup_across_polls(monitor: GitHubMonitor) -> None:
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(return_value={42: [_review_node(database_id=1)]}),
    ):
        first = await monitor._derive_review_events([_open_pr(42)])
        second = await monitor._derive_review_events([_open_pr(42)])
    assert len(first) == 1
    assert second == []


@async_test
async def test_derive_review_two_same_kind_distinct(
    monitor: GitHubMonitor,
) -> None:
    with patch.object(
        monitor,
        "_fetch_pr_reviews",
        new=AsyncMock(
            return_value={
                42: [_review_node(database_id=1), _review_node(database_id=2)]
            }
        ),
    ):
        events = await monitor._derive_review_events([_open_pr(42)])
    assert {e.key for e in events} == {"review:42:1", "review:42:2"}
