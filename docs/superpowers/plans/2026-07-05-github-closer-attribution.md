# GitHub Closer Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show who took the closing action on GitHub issue/PR close events in
the Discord embed as an `opener → closer` handoff, with the closer's avatar as
the thumbnail, without adding any new embed lines.

**Architecture:** Extend `GitHubActivityEvent` with closer fields. Resolve the
closer via GitHub GraphQL — PRs piggyback on the existing per-PR query
(`mergedBy` for merges, the last `CLOSED_EVENT` actor for non-merge closes),
standalone issue closes use one batched aliased query per poll. Repurpose the
embed's author line and thumbnail at render time based on event kind.

**Tech Stack:** Python 3.14, `discord.py`, `aiohttp`, `uv`, `pytest`
(`pytest-asyncio`, `pytest-mock`), `ruff`, `pyrefly`, `invoke`.

## Global Constraints

- **Version bump required:** bump `version` in `pyproject.toml`
  (`0.11.0` → `0.12.0`) and the image tag in `kubernetes/discordbot.yaml`
  (`v0.11.0` → `v0.12.0`).
- **100% test coverage** including branch coverage — every new branch needs a
  test in the same commit that adds it.
- **Strict typing:** `ruff` runs with `select = ["ALL"]`; `ANN401` (dynamically
  typed `Any` in signatures) is **NOT** allowed in `lib/github.py`. Use `object`
  parameters with `isinstance` narrowing, or keep dynamic values as unannotated
  locals from `await resp.json()` (as the existing code does).
- **Run `uv run invoke check` and `uv run invoke test` before every commit** —
  the pre-commit `run-checks` hook is blocking.
- **No Claude attribution** in any commit message.
- **uv pins** are already `0.11.26` everywhere and match the installed uv; only
  verify, do not change.
- **Markdown** (if touched) wraps at 80 chars; nested lists use 3-space indent.

---

## File Structure

- `lib/github.py` — event dataclass gains closer fields; add
  `_CLOSED_ACTOR_FRAGMENT`, `_PRCloseDetails`, `CLOSE_KINDS`,
  `_closer_from_actor`,
  `_resolve_pr_close_details` (refactor of `_resolve_linked_issues`),
  `_resolve_issue_closers`, `_resolve_closer`; wire `get_new_events` and
  `get_latest_activity`.
- `lib/cogs/tasks.py` — `_build_github_embed` renders dual attribution.
- `tests/test_github.py` — unit tests for parsing/resolution.
- `tests/cogs/test_tasks.py` — embed rendering tests; extend the `_gh_event`
  helper.
- `pyproject.toml`, `kubernetes/discordbot.yaml` — version + image tag.

---

## Task 1: Data model — closer fields + actor extractor

**Files:**

- Modify: `lib/github.py` (`GitHubActivityEvent` dataclass ~L58-70; add a static
  method to `GitHubMonitor`)
- Test: `tests/test_github.py`

**Interfaces:**

- Produces: `GitHubActivityEvent.closer_login: str` and
  `.closer_avatar_url: str` (both default `""`).
- Produces: `GitHubMonitor._closer_from_actor(actor: object) -> tuple[str, str]`
  — returns `(login, avatar_url)` from a GraphQL actor node, `("", "")` when
  `actor` is not a dict or the fields are absent/non-string.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_github.py` (near the other pure-function tests, e.g. after
`test_event_is_frozen`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_github.py::test_closer_from_actor_extracts_login_and_avatar tests/test_github.py::test_event_has_closer_defaults -v
```

Expected: FAIL — `AttributeError: ... has no attribute '_closer_from_actor'` and
`TypeError` / attribute error on `closer_login`.

- [ ] **Step 3: Add the dataclass fields**

In `lib/github.py`, extend `GitHubActivityEvent` (keep `linked_issues` last is
fine; add the two fields before it or after — both are keyword-defaulted):

```python
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
```

- [ ] **Step 4: Add the `_closer_from_actor` static method**

Add to `GitHubMonitor` (near the other `@staticmethod` helpers like
`_make_event`):

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -v`
Expected: PASS (all, including the four new ones).

- [ ] **Step 6: Check and commit**

```bash
uv run invoke check
uv run invoke test
git add lib/github.py tests/test_github.py
git commit -m "feat(github): add closer fields and actor extractor"
```

---

## Task 2: PR closer — refactor the per-PR query and wire it in

**Files:**

- Modify: `lib/github.py` (add module constants + dataclass; rename/replace
  `_resolve_linked_issues` ~L209-235; update `get_new_events` PR loop ~L259-266)
- Test: `tests/test_github.py`

**Interfaces:**

- Consumes: `_closer_from_actor` (Task 1).
- Produces: module constant `_CLOSED_ACTOR_FRAGMENT: str` (shared GraphQL
  fragment) and `_PRCloseDetails` frozen dataclass with fields
  `linked_issue_numbers: tuple[int, ...]`, `closer_login: str`,
  `closer_avatar_url: str`.
- Produces: `GitHubMonitor._resolve_pr_close_details(pr_number: int, *,
  is_merge: bool) -> _PRCloseDetails` — replaces `_resolve_linked_issues`.
  `is_merge=True` reads `mergedBy`; `is_merge=False` reads the last
  `CLOSED_EVENT` actor.
- Note: `_resolve_linked_issues` is **removed**; the get_new_events PR loop and
  all its tests move to the new method.

- [ ] **Step 1: Update existing linked-issue tests to the new method**

In `tests/test_github.py`, replace the seven `_resolve_linked_issues` tests
(`test_resolve_linked_issues_*`) with these (same mock data, new call + return
shape). Also add `_PRCloseDetails` to the imports from `lib.github`:

```python
from lib.github import (
    EVENT_RENDER,
    GitHubActivityEvent,
    GitHubIssue,
    GitHubMonitor,
    _parse_dt,
    _PRCloseDetails,
)
```

```python
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
```

- [ ] **Step 2: Add new closer-parsing tests**

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_github.py -k "resolve_pr_details" -v`
Expected: FAIL — `_PRCloseDetails` import error / `_resolve_pr_close_details`
not defined.

- [ ] **Step 4: Add constants + dataclass + the resolver**

In `lib/github.py`, add the shared fragment constant near the other module
constants (after `_PR_CLOSE_KINDS`):

```python
_CLOSED_ACTOR_FRAGMENT: str = (
    "timelineItems(itemTypes:[CLOSED_EVENT],last:1)"
    "{nodes{... on ClosedEvent{actor{login avatarUrl}}}}"
)
```

Add the result dataclass near `GitHubActivityEvent`:

```python
@dataclass(frozen=True)
class _PRCloseDetails:
    """Linked issue numbers and the closing actor for a PR-close event."""

    linked_issue_numbers: tuple[int, ...]
    closer_login: str
    closer_avatar_url: str
```

Replace `_resolve_linked_issues` with:

```python
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
    pull_request = (
        ((data or {}).get("data") or {}).get("repository") or {}
    ).get("pullRequest") or {}
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
```

- [ ] **Step 5: Wire the PR loop in `get_new_events`**

Replace the PR-close block in `get_new_events` (the `for event in fresh:` loop
that handles `_PR_CLOSE_KINDS`):

```python
for event in fresh:
    if event.is_pr and event.kind in _PR_CLOSE_KINDS:
        if not self._toggle_on(event.kind):
            continue
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
```

- [ ] **Step 6: Update the three `get_new_events` tests that patch resolvers**

In `tests/test_github.py`, change `test_get_new_events_combines_linked_close`,
`test_get_new_events_no_link_posts_separately`, and
`test_get_new_events_pr_toggle_off_falls_back` to patch
`_resolve_pr_close_details` returning a `_PRCloseDetails`. The linked numbers
now live in `.linked_issue_numbers`:

```python
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
            new=AsyncMock(
                return_value=_PRCloseDetails((40,), "merger", "https://a/9")
            ),
        ),
    ):
        events = await monitor.get_new_events()
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
        patch.object(
            monitor, "_resolve_issue_closers", new=AsyncMock(return_value={})
        ),
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
            new=AsyncMock(
                return_value=_PRCloseDetails((40,), "merger", "https://a/9")
            ),
        ),
        patch.object(
            monitor, "_resolve_issue_closers", new=AsyncMock(return_value={})
        ),
    ):
        events = await monitor.get_new_events()
    # PR toggled off -> issue #40 posts on its own (not combined)
    assert [e.kind for e in events] == ["ISSUE_COMPLETED"]
```

Note: `_resolve_issue_closers` is patched here in anticipation of Task 3; until
Task 3 exists, `patch.object` on a missing attribute fails — so **run these
three tests only after Step 4 of Task 3**. For this task's verification, run the
`resolve_pr_details` and `combines_linked_close` subsets (the latter does not
reference `_resolve_issue_closers`). The `no_link` / `toggle_off` tests reach
the standalone-issue path added in Task 3.

> Reconcile against `tests/test_github.py` line ~447 for the exact original body
> of `test_get_new_events_pr_toggle_off_falls_back` before editing; keep its
> original toggle target if it differs from `PR_MERGED`.

- [ ] **Step 7: Verify and commit**

Run:

```bash
uv run pytest tests/test_github.py -k "resolve_pr_details or combines_linked_close" -v
```

Expected: PASS.

```bash
uv run invoke check
git add lib/github.py tests/test_github.py
git commit -m "feat(github): resolve PR closer via extended GraphQL query"
```

Note: `uv run invoke test` (full coverage) will not reach 100% until Task 3 adds
the standalone-issue path and its tests — that is expected mid-refactor. If your
executor enforces coverage per commit, combine Tasks 2 and 3 into one commit.

---

## Task 3: Issue closer — batched aliased query + wiring

**Files:**

- Modify: `lib/github.py` (add `_resolve_issue_closers`; update the second loop
  in `get_new_events`)
- Test: `tests/test_github.py`

**Interfaces:**

- Consumes: `_CLOSED_ACTOR_FRAGMENT`, `_closer_from_actor` (Tasks 1-2).
- Produces: `GitHubMonitor._resolve_issue_closers(numbers: list[int]) ->
  dict[int, tuple[str, str]]` — one aliased GraphQL query for all `numbers`;
  maps each requested number to `(login, avatar_url)` (`("", "")` when absent).
  Returns `{}` for empty input, no token, or no session.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_github.py -k "resolve_issue_closers or populates_issue_closer" -v
```

Expected: FAIL — `_resolve_issue_closers` not defined.

- [ ] **Step 3: Add `_resolve_issue_closers`**

Add to `GitHubMonitor` (after `_resolve_pr_close_details`):

```python
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
```

- [ ] **Step 4: Wire the standalone-issue loop in `get_new_events`**

Replace the second `for event in fresh:` loop (the one appending non-PR-close
events) with:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -v`
Expected: PASS — including the three `get_new_events` tests updated in Task 2
(which now find `_resolve_issue_closers` to patch).

- [ ] **Step 6: Full check + coverage + commit**

```bash
uv run invoke check
uv run invoke test
git add lib/github.py tests/test_github.py
git commit -m "feat(github): batch-resolve issue closers per poll"
```

Expected: `invoke test` reports 100% coverage for `lib/github.py`.

---

## Task 4: Smoke-test path — `_resolve_closer` + `get_latest_activity`

**Files:**

- Modify: `lib/github.py` (add `CLOSE_KINDS`, `_resolve_closer`; update
  `get_latest_activity` ~L192-203)
- Test: `tests/test_github.py`

**Interfaces:**

- Consumes: `_resolve_pr_close_details`, `_resolve_issue_closers` (Tasks 2-3).
- Produces: module constant `CLOSE_KINDS: frozenset[str]` (union of issue + PR
  close kinds) — also consumed by Task 5.
- Produces: `GitHubMonitor._resolve_closer(event: GitHubActivityEvent) ->
  tuple[str, str]` — dispatches to the PR or issue resolver by event kind;
  `("", "")` for non-close events.
- Effect: `get_latest_activity` now populates closer fields on close events.

- [ ] **Step 1: Write the failing tests**

```python
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
            new=AsyncMock(
                return_value=_PRCloseDetails((), "merger", "https://a/9")
            ),
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_github.py -k "resolve_closer or get_latest_activity_resolves" -v
```

Expected: FAIL — `_resolve_closer` not defined; closer fields empty on close.

- [ ] **Step 3: Add `CLOSE_KINDS` and `_resolve_closer`**

Add the constant near `_PR_CLOSE_KINDS`:

```python
CLOSE_KINDS: frozenset[str] = _ISSUE_CLOSE_KINDS | _PR_CLOSE_KINDS
```

Add the dispatcher to `GitHubMonitor` (after `_resolve_issue_closers`):

```python
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
```

- [ ] **Step 4: Wire `get_latest_activity`**

Update the tail of `get_latest_activity` to resolve the closer for close events:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -v`
Expected: PASS (existing `test_get_latest_activity_closed_pr` still passes — it
only asserts `kind`; `_resolve_pr_close_details` runs unpatched with
`_session=None` and returns empty).

- [ ] **Step 6: Full check + commit**

```bash
uv run invoke check
uv run invoke test
git add lib/github.py tests/test_github.py
git commit -m "feat(github): resolve closer on latest-activity smoke path"
```

---

## Task 5: Render dual attribution in the embed

**Files:**

- Modify: `lib/cogs/tasks.py` (`_build_github_embed` ~L428-455)
- Test: `tests/cogs/test_tasks.py`

**Interfaces:**

- Consumes: `github.CLOSE_KINDS` (Task 4);
  `GitHubActivityEvent.closer_login` / `.closer_avatar_url` (Task 1).
- Behavior: close events render `set_author(name="opener → closer")` with the
  closer's avatar as thumbnail; opener/closer fall back to `"unknown"` when
  empty; the thumbnail falls back to the opener's avatar when the closer avatar
  is empty. Open events are unchanged.

- [ ] **Step 1: Extend the `_gh_event` test helper**

In `tests/cogs/test_tasks.py`, add closer params to `_gh_event` (~L1519):

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
    closer_login: str = "",
    closer_avatar_url: str = "",
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
        closer_login=closer_login,
        closer_avatar_url=closer_avatar_url,
        linked_issues=linked_issues,
    )
```

- [ ] **Step 2: Write the failing tests**

Add to `class TestGitHubMonitor` (near the other `test_build_embed_*` tests):

```python
def test_build_embed_close_shows_handoff(self, tasks_cog: Tasks) -> None:
    event = _gh_event(
        author_login="opener",
        closer_login="closer",
        closer_avatar_url="https://avatars/2",
    )
    embed = tasks_cog._build_github_embed(event)
    assert embed.author.name == "opener → closer"
    assert embed.thumbnail.url == "https://avatars/2"


def test_build_embed_open_unchanged(self, tasks_cog: Tasks) -> None:
    event = _gh_event(
        kind="ISSUE_OPENED",
        is_pr=False,
        author_login="opener",
        author_avatar_url="https://avatars/1",
    )
    embed = tasks_cog._build_github_embed(event)
    assert embed.author.name == "opener"
    assert embed.thumbnail.url == "https://avatars/1"


def test_build_embed_self_close(self, tasks_cog: Tasks) -> None:
    event = _gh_event(author_login="cyberops7", closer_login="cyberops7")
    embed = tasks_cog._build_github_embed(event)
    assert embed.author.name == "cyberops7 → cyberops7"


def test_build_embed_unknown_closer_falls_back(self, tasks_cog: Tasks) -> None:
    event = _gh_event(
        author_login="opener",
        author_avatar_url="https://avatars/1",
        closer_login="",
        closer_avatar_url="",
    )
    embed = tasks_cog._build_github_embed(event)
    assert embed.author.name == "opener → unknown"
    assert embed.thumbnail.url == "https://avatars/1"


def test_build_embed_bot_closer_rendered_as_is(self, tasks_cog: Tasks) -> None:
    event = _gh_event(author_login="opener", closer_login="github-actions[bot]")
    embed = tasks_cog._build_github_embed(event)
    assert embed.author.name == "opener → github-actions[bot]"


def test_build_embed_deleted_opener(self, tasks_cog: Tasks) -> None:
    event = _gh_event(author_login="", closer_login="closer")
    embed = tasks_cog._build_github_embed(event)
    assert embed.author.name == "unknown → closer"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/cogs/test_tasks.py -k "build_embed_close_shows_handoff or build_embed_unknown_closer" -v
```

Expected: FAIL — author name is currently `set_author(name=event.author_login)`,
so `embed.author.name` is `"opener"`, not the handoff string.

- [ ] **Step 4: Update `_build_github_embed`**

Replace the author/thumbnail block in `_build_github_embed`:

```python
def _build_github_embed(self, event: github.GitHubActivityEvent) -> discord.Embed:
    """Build a compact embed for a GitHub activity event."""
    emoji, color, verb = github.EVENT_RENDER[event.kind]
    embed = discord.Embed(
        title=f"{emoji} {verb} #{event.number}",
        description=f"**[{event.title}]({event.url})**",
        color=discord.Color(color),
    )
    if event.kind in github.CLOSE_KINDS:
        opener = event.author_login or "unknown"
        closer = event.closer_login or "unknown"
        embed.set_author(name=f"{opener} → {closer}")
        thumbnail_url = event.closer_avatar_url or event.author_avatar_url
    else:
        embed.set_author(name=event.author_login)
        thumbnail_url = event.author_avatar_url
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.set_footer(text=config.GITHUB.REPO)
    if event.linked_issues:
        lines = [
            f"• [#{issue.number}]({issue.url}) {issue.title}"
            for issue in event.linked_issues
        ]
        value = ""
        for index, line in enumerate(lines):
            candidate = f"{value}\n{line}" if value else line
            if len(candidate) > config.EMBED_MAX_LENGTH:
                tail = f"\n…and {len(lines) - index} more"
                if len(value) + len(tail) <= config.EMBED_MAX_LENGTH:
                    value += tail
                break
            value = candidate
        embed.add_field(name="Closed issues", value=value, inline=False)
    return embed
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/cogs/test_tasks.py -k build_embed -v`
Expected: PASS — all `test_build_embed_*`, including the six new ones. The
pre-existing `test_build_embed_plain`, `test_build_embed_no_avatar`, and
`test_build_embed_with_linked_issues` still pass (default `_gh_event()` kind
`PR_MERGED` renders `octocat → unknown` but those tests assert only
title/color/field/thumbnail).

- [ ] **Step 6: Full check + commit**

```bash
uv run invoke check
uv run invoke test
git add lib/cogs/tasks.py tests/cogs/test_tasks.py
git commit -m "feat(github): render opener to closer handoff in embed"
```

---

## Task 6: Version bump + deployment metadata

**Files:**

- Modify: `pyproject.toml` (`version`)
- Modify: `kubernetes/discordbot.yaml` (image tag)
- Modify: `uv.lock` (regenerated)

**Interfaces:** none (release metadata).

- [ ] **Step 1: Bump the project version**

In `pyproject.toml`, change:

```toml
version = "0.11.0"
```

to:

```toml
version = "0.12.0"
```

- [ ] **Step 2: Update the Kubernetes image tag**

In `kubernetes/discordbot.yaml` (line ~75), change:

```yaml
          image: ghcr.io/cyberops7/discord_bot:v0.11.0
```

to:

```yaml
          image: ghcr.io/cyberops7/discord_bot:v0.12.0
```

- [ ] **Step 3: Regenerate the lockfile**

Run: `uv lock`
Expected: `uv.lock` updates the project version to `0.12.0`.

- [ ] **Step 4: Verify uv pins are consistent (no change expected)**

Run: `uv --version` and confirm it prints `0.11.26`, then confirm the four pins
match:

Run:

```bash
grep -rn "0.11.26" .pre-commit-config.yaml .github/workflows/check-test.yaml docker/Dockerfile docker/Dockerfile-test
```

Expected: one match per file (all `0.11.26`). If `uv --version` differs, update
all four pins to that version.

- [ ] **Step 5: Final full check + tests**

Run: `uv run invoke check`
Run: `uv run invoke test`
Expected: all checks pass; coverage 100%.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml kubernetes/discordbot.yaml uv.lock
git commit -m "chore: bump version to 0.12.0"
```

---

## Self-Review

**Spec coverage:**

- Data model (closer fields) → Task 1. ✓
- GraphQL error handling (`errors[]` logged) → Tasks 2 & 3 (per-resolver
  `if data and data.get("errors")` + `logs_graphql_errors` tests). ✓
- PR closer via extended query; `mergedBy` for merges, `CLOSED_EVENT` actor for
  closes; timeline intentionally ignored for merges → Task 2. ✓
- Batched aliased issue query (one call per poll) → Task 3. ✓
- `get_new_events` + `get_latest_activity` wiring; shared `_resolve_closer` →
  Tasks 2-4. ✓
- Rendering: `opener → closer`, closer avatar thumbnail, `unknown` fallbacks
  (both sides), open events unchanged, bots as-is → Task 5. ✓
- Edge cases: self-close arrow, unresolved closer, deleted opener, bot suffix →
  Task 5 tests. ✓
- Test matrix: `actor: null`, empty timeline (`nodes: []`), `errors[]`, batched
  mapping, `state_reason` (already covered by existing
  `test_derive_issue_close_kinds`) → Tasks 1-5. ✓
- Version + image tag + uv pins → Task 6. ✓

**Placeholder scan:** No TBD/TODO; all steps carry concrete code and commands.

**Type consistency:** `_PRCloseDetails` fields (`linked_issue_numbers`,
`closer_login`, `closer_avatar_url`), `_resolve_pr_close_details(pr_number, *,
is_merge)`, `_resolve_issue_closers(numbers) -> dict[int, tuple[str, str]]`,
`_resolve_closer(event) -> tuple[str, str]`, and `CLOSE_KINDS` are used
consistently across tasks. `_closer_from_actor(actor: object)` returns
`tuple[str, str]` everywhere.

**Coverage risk notes:** `_resolve_closer`'s non-close `return "", ""` is
exercised by `test_resolve_closer_non_close_returns_empty`; empty-timeline and
`mergedBy`-null branches by dedicated tests; both `errors[]` branches by the
`logs_graphql_errors` tests and happy paths. Tasks 2 and 3 must land together
(or 3 immediately after 2) for full-suite green, since Task 2's updated
`get_new_events` tests patch `_resolve_issue_closers` (added in Task 3).
