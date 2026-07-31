# PR Review Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post a compact Discord embed to `#github` when a review is submitted
on an open PR in `JamesTurland/JimsGarage`, gated by per-kind config toggles
(only changes-requested on by default).

**Architecture:** Extend the existing poll-based `GitHubMonitor`
(`lib/github.py`). The existing `/issues` REST poll already resurfaces PRs whose
`updated_at` bumped (a submitted review bumps it). A new async helper
GraphQL-batch-fetches recent reviews for the open PRs from that poll, gates each
review by state→kind toggle, a startup-time cutoff, and an in-memory dedup set,
and emits the same `GitHubActivityEvent` the cog already renders. No new task,
channel, module, or webhook.

**Tech Stack:** Python 3.13, uv, discord.py, aiohttp, GitHub GraphQL API,
pytest (pytest-asyncio, pytest-mock), pyrefly (strict), ruff.

## Global Constraints

- **Type checking:** pyrefly strict. Run `uv run pyrefly check` before every
  commit. All new code fully type-hinted.
- **Formatting/lint:** run `uv run ruff format` then `uv run ruff check` before
  every commit. Markdown ≤80 cols (MD013).
- **Test coverage:** 100% including branch coverage. Every new branch needs a
  test. Run `uv run invoke test`.
- **Config access:** all config via the `config` singleton
  (`from lib.config import config`). New config keys go in `conf/config.yaml`.
- **Version bump:** bump `pyproject.toml` version `0.13.0` → `0.14.0` and match
  the image tag in `kubernetes/discordbot.yaml` (`v0.13.0` → `v0.14.0`).
- **UV pin sync:** before committing, run `uv --version`; if it differs from the
  pins, update all four (`.pre-commit-config.yaml`,
  `.github/workflows/check-test.yaml`, and the `ghcr.io/astral-sh/uv` tag in
  `docker/Dockerfile` and `docker/Dockerfile-test`).
- **Git artifacts:** no Claude/AI attribution in any commit message, PR title,
  or PR body.
- **Signing:** commits are signed via 1Password SSH agent. If a commit fails
  with `1Password: failed to fill whole buffer` or any signing/auth error,
  STOP and ask the human to unlock — never bypass with `--no-gpg-sign` or
  `--no-verify`.
- **Commit authority:** in this repo, subagent `git commit` fails signing. The
  controller performs commits; a subagent executing a task stages changes and
  hands the commit back to the controller.
- **Finish:** push the feature branch and open a PR against `main` (not a local
  merge).
- **discord.py gotcha:** review events set `is_pr=True`; the embed's
  closer-branch is gated on `event.kind in CLOSE_KINDS`, which excludes review
  kinds — no `_build_github_embed` change is required or wanted.

---

## Task 1: Render metadata, kind grouping, state map, config, conftest

Adds the static scaffolding every later task consumes: the three review event
kinds' render metadata, the kind frozenset, the state→kind map, the per-PR
review cap constant, the config toggles, and the test-config fixture values.

**Files:**

- Modify: `lib/github.py` (after `EVENT_RENDER` ~L18-25 and the kind frozensets
  ~L27-33)
- Modify: `conf/config.yaml` (`GITHUB.EVENTS` block ~L17-23)
- Modify: `tests/conftest.py` (`mock_config` fixture, after the existing
  `mock_cfg.GITHUB.EVENTS.*` lines ~L119-124)
- Modify: `tests/test_github.py` (imports ~L11-18; update
  `test_event_render_covers_all_kinds` ~L149-157; add mapping tests)

**Interfaces:**

- Produces:
   - `EVENT_RENDER` gains keys `PR_REVIEW_CHANGES_REQUESTED`,
     `PR_REVIEW_APPROVED`, `PR_REVIEW_COMMENTED` → `tuple[str, int, str]`.
   - `_PR_REVIEW_KINDS: frozenset[str]`.
   - `_REVIEW_STATE_TO_KIND: dict[str, str]` (review `state` → event kind).
   - `_REVIEWS_PER_PR: int = 50`.
   - Config keys
     `GITHUB.EVENTS.PR_REVIEW_{CHANGES_REQUESTED,APPROVED,COMMENTED}`.

- [ ] **Step 1: Write failing tests** in `tests/test_github.py`.

Update the imports to add the new symbols:

```python
from lib.github import (
    EVENT_RENDER,
    GitHubActivityEvent,
    GitHubIssue,
    GitHubMonitor,
    _parse_dt,
    _PRCloseDetails,
    _PR_REVIEW_KINDS,
    _REVIEW_STATE_TO_KIND,
    _REVIEWS_PER_PR,
)
```

Replace `test_event_render_covers_all_kinds` with the review kinds added, and
add two mapping tests:

```python
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
    assert _PR_REVIEW_KINDS <= set(EVENT_RENDER)


def test_review_state_to_kind_mapping() -> None:
    assert _REVIEW_STATE_TO_KIND == {
        "CHANGES_REQUESTED": "PR_REVIEW_CHANGES_REQUESTED",
        "APPROVED": "PR_REVIEW_APPROVED",
        "COMMENTED": "PR_REVIEW_COMMENTED",
    }
    assert _REVIEWS_PER_PR == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github.py::test_review_state_to_kind_mapping -v`
Expected: FAIL — `ImportError` (`_REVIEW_STATE_TO_KIND` not defined).

- [ ] **Step 3: Add the metadata to `lib/github.py`.**

Append three rows to `EVENT_RENDER`:

```python
EVENT_RENDER: dict[str, tuple[str, int, str]] = {
    "ISSUE_OPENED": ("🟢", 0x2ECC71, "New issue"),
    "ISSUE_COMPLETED": ("🟣", 0x9B59B6, "Issue closed as completed"),
    "ISSUE_NOT_PLANNED": ("⚪", 0x95A5A6, "Issue closed as not planned"),
    "PR_OPENED": ("🟢", 0x2ECC71, "New PR"),
    "PR_MERGED": ("🟣", 0x9B59B6, "PR merged"),
    "PR_CLOSED": ("🔴", 0xE74C3C, "PR closed"),
    "PR_REVIEW_CHANGES_REQUESTED": ("🟠", 0xE67E22, "Changes requested on"),
    "PR_REVIEW_APPROVED": ("✅", 0x2ECC71, "Approved"),
    "PR_REVIEW_COMMENTED": ("💬", 0x95A5A6, "Reviewed"),
}
```

After the existing `CLOSE_KINDS` line (~L29), add the review groupings and cap:

```python
_PR_REVIEW_KINDS: frozenset[str] = frozenset(
    {
        "PR_REVIEW_CHANGES_REQUESTED",
        "PR_REVIEW_APPROVED",
        "PR_REVIEW_COMMENTED",
    }
)
_REVIEW_STATE_TO_KIND: dict[str, str] = {
    "CHANGES_REQUESTED": "PR_REVIEW_CHANGES_REQUESTED",
    "APPROVED": "PR_REVIEW_APPROVED",
    "COMMENTED": "PR_REVIEW_COMMENTED",
}
_REVIEWS_PER_PR: int = 50
```

- [ ] **Step 4: Add config toggles to `conf/config.yaml`.**

Under `GITHUB.EVENTS`, keep keys alphabetical:

```yaml
GITHUB:
  EVENTS:
    ISSUE_COMPLETED: true
    ISSUE_NOT_PLANNED: true
    ISSUE_OPENED: true
    PR_CLOSED: true
    PR_MERGED: true
    PR_OPENED: true
    PR_REVIEW_APPROVED: false
    PR_REVIEW_CHANGES_REQUESTED: true
    PR_REVIEW_COMMENTED: false
```

- [ ] **Step 5: Add the mock-config values to `tests/conftest.py`.**

After the existing `mock_cfg.GITHUB.EVENTS.PR_CLOSED = True` line, add (the two
default-off keys MUST be explicit `False`: `_toggle_on` does
`bool(getattr(...))` and an unset `MagicMock` attribute is truthy, so omitting
them would make suppression tests false-pass):

```python
    mock_cfg.GITHUB.EVENTS.PR_REVIEW_CHANGES_REQUESTED = True
    mock_cfg.GITHUB.EVENTS.PR_REVIEW_APPROVED = False
    mock_cfg.GITHUB.EVENTS.PR_REVIEW_COMMENTED = False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -k "render or mapping or review" -v`
Expected: PASS.

- [ ] **Step 7: Format, lint, type-check**

Run: `uv run ruff format && uv run ruff check && uv run pyrefly check`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add lib/github.py conf/config.yaml tests/conftest.py tests/test_github.py
git commit -m "feat(github): add PR review event kinds, render metadata, config"
```

---

## Task 2: Review-node parsing and GraphQL batch fetch

Adds the `_ReviewNode` value type, a defensive single-node parser, and the
aliased one-query-per-poll fetch mirroring `_resolve_issue_closers`.

**Files:**

- Modify: `lib/github.py` (add `_ReviewNode` dataclass near the other frozen
  dataclasses ~L80-87; add `_parse_review_node` and `_fetch_pr_reviews` methods
  on `GitHubMonitor`)
- Modify: `tests/test_github.py` (import `_ReviewNode`; add tests)

**Interfaces:**

- Consumes: `_REVIEWS_PER_PR`, `GITHUB_GRAPHQL_URL`, `_closer_from_actor`,
  `self._repo`, `self._token`, `self._session` (all existing).
- Produces:
   - `@dataclass(frozen=True) class _ReviewNode` with fields
     `database_id: int`, `state: str`, `submitted_at: str`, `url: str`,
     `author_login: str`, `author_avatar_url: str`.
   - `_parse_review_node(self, node: object) -> _ReviewNode | None` on
     `GitHubMonitor`.
   - `_fetch_pr_reviews(self, pr_numbers: list[int]) ->
     dict[int, list[_ReviewNode]]` (async) on `GitHubMonitor`.

- [ ] **Step 1: Write failing tests** in `tests/test_github.py`.

Add `_ReviewNode` to the `lib.github` import block. Add a small helper near the
top-level test helpers and these tests (reuse the existing `_mock_response`
helper and `monitor`/`caplog` fixtures):

```python
def _reviews_response(
    reviews_by_pr: dict[int, list[dict[str, object]]],
) -> dict[str, object]:
    repo: dict[str, object] = {
        f"pr{n}": {"reviews": {"nodes": nodes}}
        for n, nodes in reviews_by_pr.items()
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
def test_parse_review_node_rejects_bad(
    monitor: GitHubMonitor, raw: object
) -> None:
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
        return_value=_mock_response(
            {"data": None, "errors": [{"message": "bad"}]}
        )
    )
    monitor._session = session
    with caplog.at_level(logging.WARNING):
        result = await monitor._fetch_pr_reviews([42])
    assert result == {42: []}
    assert any(
        "GraphQL errors resolving PR reviews" in r.message
        for r in caplog.records
    )


@async_test
async def test_fetch_pr_reviews_missing_pr_node(monitor: GitHubMonitor) -> None:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_mock_response({"data": {"repository": {}}})
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github.py::test_fetch_pr_reviews_parses -v`
Expected: FAIL — `AttributeError` (`_fetch_pr_reviews` not defined).

- [ ] **Step 3: Add `_ReviewNode` to `lib/github.py`.**

After the `_PRCloseDetails` dataclass (~L87), add:

```python
@dataclass(frozen=True)
class _ReviewNode:
    """A parsed PR review node from the GraphQL `reviews` connection."""

    database_id: int
    state: str
    submitted_at: str
    url: str
    author_login: str
    author_avatar_url: str
```

- [ ] **Step 4: Add the parser and fetch methods** on `GitHubMonitor`.

Place `_parse_review_node` near `_closer_from_actor`, and `_fetch_pr_reviews`
near `_resolve_issue_closers`:

```python
    def _parse_review_node(self, node: object) -> _ReviewNode | None:
        """Parse one GraphQL review node; return None if unusable."""
        if not isinstance(node, dict):
            return None
        database_id = node.get("databaseId")
        submitted_at = node.get("submittedAt")
        state = node.get("state")
        url = node.get("url")
        if not isinstance(database_id, int):
            return None
        if not isinstance(submitted_at, str):
            return None
        if not isinstance(state, str):
            return None
        login, avatar = self._closer_from_actor(node.get("author"))
        return _ReviewNode(
            database_id=database_id,
            state=state,
            submitted_at=submitted_at,
            url=url if isinstance(url, str) else "",
            author_login=login,
            author_avatar_url=avatar,
        )

    async def _fetch_pr_reviews(
        self, pr_numbers: list[int]
    ) -> dict[int, list[_ReviewNode]]:
        """Batch-fetch recent reviews for open PRs via one aliased query.

        Mirrors `_resolve_issue_closers`: one GraphQL call per poll regardless
        of how many PRs were touched, bounding secondary-rate-limit risk.
        """
        if not pr_numbers or not self._token or self._session is None:
            return {}
        owner, _, name = self._repo.partition("/")
        fields = "".join(
            f"pr{n}:pullRequest(number:{n})"
            f"{{reviews(last:{_REVIEWS_PER_PR})"
            "{nodes{databaseId state submittedAt url author{login avatarUrl}}}}}"
            for n in pr_numbers
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
            logger.exception("GraphQL request failed for PR reviews")
            return {}
        if data and data.get("errors"):
            logger.warning("GraphQL errors resolving PR reviews: %s", data["errors"])
        repository = ((data or {}).get("data") or {}).get("repository") or {}
        result: dict[int, list[_ReviewNode]] = {}
        for number in pr_numbers:
            node = repository.get(f"pr{number}") or {}
            reviews = node.get("reviews") or {}
            nodes = reviews.get("nodes") or []
            if len(nodes) >= _REVIEWS_PER_PR:
                logger.warning(
                    "PR #%d returned the review page cap (%d); older reviews "
                    "may be missed",
                    number,
                    _REVIEWS_PER_PR,
                )
            result[number] = [
                parsed
                for raw in nodes
                if (parsed := self._parse_review_node(raw)) is not None
            ]
        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -k "review_node or fetch_pr" -v`
Expected: PASS.

- [ ] **Step 6: Format, lint, type-check**

Run: `uv run ruff format && uv run ruff check && uv run pyrefly check`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add lib/github.py tests/test_github.py
git commit -m "feat(github): batch-fetch and parse PR reviews via GraphQL"
```

---

## Task 3: Review event derivation, gating, and dedup

Turns fetched review nodes into gated, deduped `GitHubActivityEvent`s.

**Files:**

- Modify: `lib/github.py` (add `_make_review_event` near `_make_event`; add
  `_derive_review_events` near `get_new_events`)
- Modify: `tests/test_github.py` (add helpers and tests)

**Interfaces:**

- Consumes: `_REVIEW_STATE_TO_KIND`, `_toggle_on`, `_parse_dt`,
  `self._started_at`, `self._seen`, `_fetch_pr_reviews`, `_ReviewNode`,
  `GitHubActivityEvent`, `GitHubIssue`.
- Produces:
   - `_make_review_event(kind: str, issue: GitHubIssue, node: _ReviewNode) ->
     GitHubActivityEvent` (staticmethod). The event's `.key` is
     `f"review:{number}:{node.database_id}"`, `url` is the review URL,
     `is_pr=True`.
   - `_derive_review_events(self, open_prs: list[GitHubIssue]) ->
     list[GitHubActivityEvent]` (async). Manages `self._seen` itself; gates on
     kind toggle, `submitted_at > _started_at`, and dedup key not already seen.

- [ ] **Step 1: Write failing tests** in `tests/test_github.py`.

Add these helpers and tests (they patch `_fetch_pr_reviews` so no HTTP is
involved):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github.py -k derive_review_changes -v`
Expected: FAIL — `AttributeError` (`_derive_review_events` not defined).

- [ ] **Step 3: Implement the derivation methods** in `lib/github.py`.

Add `_make_review_event` near `_make_event`:

```python
    @staticmethod
    def _make_review_event(
        kind: str, issue: GitHubIssue, node: _ReviewNode
    ) -> GitHubActivityEvent:
        """Build a review activity event from a REST PR item + a review node."""
        number = issue["number"]
        return GitHubActivityEvent(
            key=f"review:{number}:{node.database_id}",
            kind=kind,
            number=number,
            title=issue["title"],
            url=node.url,
            author_login=node.author_login,
            author_avatar_url=node.author_avatar_url,
            is_pr=True,
        )
```

Add `_derive_review_events` (place it just above `get_new_events`):

```python
    async def _derive_review_events(
        self, open_prs: list[GitHubIssue]
    ) -> list[GitHubActivityEvent]:
        """Fetch and gate new reviews on open PRs into postable events.

        Runs after the open/close dedup in `get_new_events`, so it manages
        `self._seen` itself. Reviews are gated on the toggle, a
        `submitted_at > _started_at` startup cutoff, and the dedup key —
        deliberately NOT on `_last_checked` (already advanced this poll).
        """
        if not open_prs:
            return []
        reviews_by_pr = await self._fetch_pr_reviews(
            [issue["number"] for issue in open_prs]
        )
        events: list[GitHubActivityEvent] = []
        for issue in open_prs:
            for node in reviews_by_pr.get(issue["number"], []):
                kind = _REVIEW_STATE_TO_KIND.get(node.state)
                if kind is None or not self._toggle_on(kind):
                    continue
                submitted = _parse_dt(node.submitted_at)
                if submitted is None or submitted <= self._started_at:
                    continue
                event = self._make_review_event(kind, issue, node)
                if event.key in self._seen:
                    continue
                self._seen.add(event.key)
                events.append(event)
        return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -k "derive_review" -v`
Expected: PASS.

- [ ] **Step 5: Format, lint, type-check**

Run: `uv run ruff format && uv run ruff check && uv run pyrefly check`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add lib/github.py tests/test_github.py
git commit -m "feat(github): derive gated, deduped PR review events"
```

---

## Task 4: Wire reviews into the poll (`get_new_events`)

Selects open PRs from the poll's fetched items and appends their review events
to the returned plan.

**Files:**

- Modify: `lib/github.py` (`get_new_events`, after the
  `_enqueue_non_pr_events(...)` call and before `plan.sort(...)` ~L394-396)
- Modify: `tests/test_github.py` (add tests)

**Interfaces:**

- Consumes: `_derive_review_events`, the local `issues` and `plan` in
  `get_new_events`.
- Produces: `get_new_events` return value now includes review events for open
  PRs surfaced this poll.

- [ ] **Step 1: Write failing tests** in `tests/test_github.py`.

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github.py -k get_new_events_includes -v`
Expected: FAIL — no review events in the plan yet.

- [ ] **Step 3: Wire the review path into `get_new_events`.**

Locate the tail of `get_new_events`:

```python
        await self._enqueue_non_pr_events(fresh, combined_numbers, plan)
        plan.sort(key=lambda e: (e.number, e.kind))
        return plan
```

Insert the open-PR selection and review derivation between the enqueue and the
sort:

```python
        await self._enqueue_non_pr_events(fresh, combined_numbers, plan)
        open_prs = [
            issue
            for issue in issues
            if "pull_request" in issue and issue.get("state") == "open"
        ]
        plan.extend(await self._derive_review_events(open_prs))
        plan.sort(key=lambda e: (e.number, e.kind))
        return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github.py -k "get_new_events" -v`
Expected: PASS (existing `get_new_events` tests still pass too).

- [ ] **Step 5: Format, lint, type-check**

Run: `uv run ruff format && uv run ruff check && uv run pyrefly check`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add lib/github.py tests/test_github.py
git commit -m "feat(github): surface open-PR reviews from the activity poll"
```

---

## Task 5: Lock the review embed rendering (no production change)

Confirms `_build_github_embed` renders a review event correctly with no code
change: the closer-branch is skipped, the reviewer is the author, the review URL
is the linked description, and no body field is added.

**Files:**

- Modify: `tests/cogs/test_tasks.py` (add a test beside the other
  `test_build_embed_*` methods ~L1708-1754)

**Interfaces:**

- Consumes: the existing `_gh_event` test helper and `tasks_cog` fixture;
  `Tasks._build_github_embed`.
- Produces: no production change — a regression test only.

- [ ] **Step 1: Write the test** in `tests/cogs/test_tasks.py`.

Add alongside the existing `test_build_embed_*` methods (same class):

```python
    def test_build_embed_review(self, tasks_cog: Tasks) -> None:
        url = "https://github.com/JamesTurland/JimsGarage/pull/42#r1"
        event = _gh_event(
            kind="PR_REVIEW_CHANGES_REQUESTED",
            number=42,
            title="Fix the thing",
            url=url,
            author_login="reviewer",
            author_avatar_url="https://avatars/7",
        )
        embed = tasks_cog._build_github_embed(event)
        assert embed.title == "🟠 Changes requested on #42"
        assert embed.description == f"**[Fix the thing]({url})**"
        assert embed.author.name == "reviewer"
        assert embed.thumbnail.url == "https://avatars/7"
        assert embed.fields == []
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/cogs/test_tasks.py -k test_build_embed_review -v`
Expected: PASS immediately (no production change needed). If it fails on the
`_gh_event` signature, adjust the kwargs to match the helper's parameters —
do NOT change `_build_github_embed`.

- [ ] **Step 3: Commit**

```bash
git add tests/cogs/test_tasks.py
git commit -m "test(tasks): lock review-event embed rendering"
```

---

## Task 6: Version bump, deploy tag, full-suite verification, PR

Bumps the version and image tag, runs the whole gate, and ships the branch.

**Files:**

- Modify: `pyproject.toml` (`version` ~L3)
- Modify: `kubernetes/discordbot.yaml` (image tag ~L75)

**Interfaces:**

- Consumes: everything from Tasks 1-5.
- Produces: a green full suite and an open PR against `main`.

- [ ] **Step 1: Bump the version** in `pyproject.toml`:

```toml
version = "0.14.0"
```

- [ ] **Step 2: Match the image tag** in `kubernetes/discordbot.yaml`:

```yaml
          image: ghcr.io/cyberops7/discord_bot:v0.14.0
```

- [ ] **Step 3: UV pin sync check**

Run: `uv --version`
If it differs from the current pins, update all four:
`.pre-commit-config.yaml`, `.github/workflows/check-test.yaml`, and the
`ghcr.io/astral-sh/uv` tag in `docker/Dockerfile` and `docker/Dockerfile-test`.
If it matches, no change.

- [ ] **Step 4: Full lint + type + coverage gate**

Run: `uv run invoke check`
Expected: all linters pass (ruff, bandit, pyrefly, hadolint, markdownlint,
yamllint, shellcheck).

Run: `uv run invoke test`
Expected: PASS with 100% coverage. If coverage is <100%, add the missing-branch
test rather than lowering the threshold.

- [ ] **Step 5: Commit the version bump**

```bash
git add pyproject.toml kubernetes/discordbot.yaml
git commit -m "chore: bump version to 0.14.0"
```

(If `uv --version` required pin updates in Step 3, `git add` those files into a
separate `chore: sync uv pin to <version>` commit.)

- [ ] **Step 6: Push and open the PR**

```bash
git push -u origin cyberops7/github-pr-reviews
gh pr create --base main --head cyberops7/github-pr-reviews \
  --title "feat: notify Discord when PRs receive reviews" \
  --body "$(cat <<'EOF'
## Summary

Extends the GitHub activity monitor to post a compact `#github` embed when a
review is submitted on an open PR in `JamesTurland/JimsGarage`. Gated by new
per-kind config toggles under `GITHUB.EVENTS`; only
`PR_REVIEW_CHANGES_REQUESTED` is on by default (approvals and plain review
comments can be enabled with a config-only change).

## How it works

- The existing `/issues` poll already resurfaces PRs whose `updated_at` bumped
  (a submitted review bumps it). A single aliased GraphQL query fetches recent
  reviews for the open PRs in that poll.
- Reviews are gated on the kind toggle, a `submitted_at > startup` cutoff, and
  an in-memory dedup set keyed on `review:{pr}:{databaseId}`.
- Review dismissals are out of scope (a timeline event, not on the `reviews`
  connection) and noted as future work.

## Testing

- `uv run invoke check` — clean
- `uv run invoke test` — 100% coverage

Spec: `docs/superpowers/specs/2026-07-30-pr-review-notifications-design.md`
Plan: `docs/superpowers/plans/2026-07-30-pr-review-notifications.md`
EOF
)"
```

- [ ] **Step 7: Confirm CI is green**

Run: `gh pr checks --watch`
Expected: all checks pass.

- [ ] **Step 8 (post-merge nicety):** mark the item done in
  `/Users/david/code/github/discord_bot/.claude/todo.md` (that file lives in
  the main checkout, not this worktree, and is not part of the PR).

---

## Self-Review Notes

- **Spec coverage:** review kinds + render (T1), GraphQL batch fetch + defensive
  parse + page-cap log (T2), state→kind map / toggle / startup gate / dedup
  (T3), open-PR-only scoping + poll wiring (T4), embed rendering (T5), version
  bump + delivery (T6). DISMISSED and webhooks are spec non-goals — no task,
  intentionally. `config.pyi` is intentionally untouched (keys resolve via
  `ConfigDict.__getattr__ -> Any`).
- **Branch coverage:** unmapped state (PENDING/DISMISSED/unknown), toggle
  off/on, before-startup and unparseable `submitted_at`, dedup across polls,
  two-same-kind distinct keys, empty-PR/no-token/no-session short circuits,
  client error, GraphQL errors, missing PR node, page cap, null/bad review
  nodes, and all three branches of the open-PR selection (open PR / closed PR /
  non-PR issue) each have a test.
- **Type consistency:** `_ReviewNode` fields, `_fetch_pr_reviews ->
  dict[int, list[_ReviewNode]]`, `_derive_review_events(list[GitHubIssue]) ->
  list[GitHubActivityEvent]`, and the `review:{number}:{database_id}` key format
  are used identically across tasks.
