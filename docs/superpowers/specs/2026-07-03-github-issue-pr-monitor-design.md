# GitHub Issue/PR Monitor — Design

**Date:** 2026-07-03
**Status:** Approved (pending spec review)

## Summary

Add a periodic background task to the Discord bot that watches the public
`JamesTurland/JimsGarage` GitHub repository for issue and pull-request activity
and posts to the `#github` channel (ID `1522491309003243660`) when issues/PRs
are opened or closed. When a merged PR is officially linked to the issue it
closes (via GitHub's own link data), the two are combined into a single message
to reduce noise.

The feature deliberately mirrors the existing YouTube monitor
(`lib/youtube.py` + `monitor_youtube_videos` in `lib/cogs/tasks.py`) in
structure — a periodic `@tasks.loop`, a dedicated parser/client class holding an
in-memory "seen" set that baselines at startup, and Discord embed posts. The
key difference is the data source: GitHub does not offer official Atom/RSS feeds
for issues or PRs, so this uses the **GitHub REST API** for polling plus a
targeted **GitHub GraphQL API** query for authoritative issue↔PR linkage.

### Channel context: a maintainer working channel

`#github` is a **working channel for the repo's maintainers**, not a dedicated
notification firehose. Bot posts share the channel with active human
discussion. Noise-minimization is therefore a first-class design concern, not an
afterthought:

- **No `@everyone`/`@here` pings** — ever.
- **Combining linked issue+PR closes** and the **per-event toggles** are the
  primary noise controls; maintainers can dial any event type down if it proves
  chatty.
- **Compact embeds** — a single tidy embed per event (linked title, small author
  avatar thumbnail, repo name). No large preview images, no multi-field walls of
  text, so posts inform without dominating the conversation.

## Goals

- Post to `#github` when an issue or PR is opened or closed.
- Distinguish close types: PR *merged* vs *closed-unmerged*; issue *completed*
  vs *not planned*.
- When a merged PR is officially linked (by GitHub) to an issue that closes in
  the same poll cycle, combine both into one embed.
- Never *infer* a link — only combine when GitHub itself records the
  relationship.
- Each event type is independently enable/disable-able via config.

## Non-goals

- Persisting state across restarts (matches the YouTube job's in-memory model).
- Watching repos other than `JamesTurland/JimsGarage` (single repo for v1, but
  the repo is a config value).
- Reacting to comments, reviews, labels, commits, releases, or other event
  types.
- Inferring issue↔PR links from PR body text or timing heuristics.

## Architecture & Components

### New module: `lib/github.py`

A `GitHubMonitor` class — the analog of `YoutubeFeedParser`. Responsibilities:

- Hold configuration (repo slug, token, event toggles).
- Perform the REST poll (`aiohttp`, async).
- Derive candidate events from the fetched items.
- Apply the "new event" gates (see State Model) against an in-memory `seen` set.
- Resolve authoritative PR→issue links via a targeted GraphQL query.
- Expose helpers the cog uses to build embeds (colors, titles, labels).

Uses `aiohttp`, which is already a transitive dependency of `discord.py` — **no
new runtime dependency**. Unlike `YoutubeFeedParser` (which calls `feedparser`
synchronously inside the async task), `GitHubMonitor` performs proper async I/O
so it never blocks the event loop.

### Extend: `lib/cogs/tasks.py`

Add, alongside `monitor_youtube_videos`:

- `monitor_github_activity` — a `@tasks.loop(minutes=<config>)` that calls the
  monitor, receives a post plan, and sends embeds to the target channel.
- `before_monitor_github_activity` — a `before_loop` bootstrap that constructs
  the `GitHubMonitor`, waits until the bot is ready, records the startup
  timestamp, and (in dry-run) performs the startup smoke-test post.
- Bootstrap/`cog_unload` wiring mirroring the YouTube task.

### Config: `conf/config.yaml`

```yaml
CHANNELS:
  GITHUB: 1522491309003243660
DRY_RUN_GITHUB: false          # when true, post to BOT_PLAYGROUND instead
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

The existing env-override system maps nested keys to underscore-joined env
vars, so `GITHUB.TOKEN` is overridden by the env var `GITHUB_TOKEN`,
`GITHUB.REPO` by `GITHUB_REPO`, and `GITHUB.EVENTS.PR_MERGED` by
`GITHUB_EVENTS_PR_MERGED`. `DRY_RUN_GITHUB` mirrors `DRY_RUN_YOUTUBE`.

### Tests

- `tests/test_github.py`, modeled on `tests/test_youtube.py`, mocking `aiohttp`
  responses for REST and GraphQL.
- Extend the task-cog tests for the new loop and bootstrap.
- 100% branch coverage (project requirement).

## Authentication

- A **fine-grained personal access token** with "Public repositories
  (read-only)" access and no account permissions. This is the tightest option:
  read-only, cannot touch private data, cannot write anywhere. (A token cannot
  be scoped to only `JimsGarage` because the user does not own it; public
  read-only is the closest least-privilege setting.)
- Stored as `GITHUB_TOKEN`: `.env` locally, a k8s `Secret` in production —
  identical handling to `BOT_TOKEN`.
- Both REST and GraphQL requests send `Authorization: Bearer <token>`.
- Rate limit: 5,000 req/hr authenticated; polling ~12×/hr uses a tiny fraction.

## Data Flow & State Model

### Fetch (REST)

Each poll issues:

```text
GET /repos/{REPO}/issues?state=all&sort=updated&direction=desc&since={last_checked}
```

- This single endpoint returns **both issues and PRs**. PRs carry a
  `pull_request` object, which includes `merged_at` — so *merged* vs
  *closed-unmerged* is determined without an extra call.
- `since` bounds each poll to items updated since the previous poll.
- Pagination is followed if a poll returns a full page (bounded; unlikely at a
  5-minute cadence).

### Event derivation

For each returned item, derive candidate events:

- `opened` — from `created_at`.
- Issue close — `completed` vs `not_planned`/`duplicate` from `state_reason`
  (null → `completed` bucket).
- PR close — `merged` if `pull_request.merged_at` is set, else `closed`.

Each event has a stable key, e.g. `issue:40:opened`, `issue:40:completed`,
`pr:42:merged`, `pr:42:closed`.

### Two-gate "new event" test

An event is announced only if **both** hold:

1. **Timestamp gate** — the event's own timestamp (`created_at` for opens,
   `closed_at`/`merged_at` for closes) is **after the bot's startup time**. This
   prevents announcing an `opened` event for a years-old issue that merely got a
   new comment (and thus reappears in the `since` window).
2. **Seen gate** — the event key is not already in the in-memory `seen` set.
   This prevents re-posting when an item resurfaces in later polls.

When an event is announced, its key is added to `seen`.

### Toggle filtering

After the two gates, an event is dropped if its corresponding
`GITHUB.EVENTS.*` toggle is disabled. (Exception: a linked issue-close shown as
a sub-line on a combined PR embed is governed by the PR's toggle — see Linkage.)

### Restart behavior

State is in-memory; startup resets `last_checked`/startup time to "now."
Consequently, events occurring **while the bot is down** are missed but never
double-posted. This matches the YouTube monitor's tradeoff and is acceptable for
this feature.

## Linkage Combining (GraphQL)

- Within a single poll, after computing the batch of new events, for each new
  **PR merged/closed** event, fire one GraphQL query for that PR's
  `closingIssuesReferences` (GitHub's authoritative "issues this PR closes"
  list).
- If a referenced issue **also has a new close event in the same poll batch**,
  merge: render one embed for the PR that lists the linked closed issue(s), and
  drop the standalone issue-close post(s) from the plan.
- If GitHub reports no link, or the two closes land in different poll cycles,
  they post separately. This satisfies the "never infer, only combine when
  closed together" scope.
- The combined embed follows the PR's event toggle (typically `PR_MERGED`); the
  linked issue appears as a sub-line regardless of the issue toggles.

### Poll processing order

1. Fetch (REST, paginated as needed).
2. Compute all candidate events; apply the two gates → batch of new events.
3. For each new PR close/merge, resolve `closingIssuesReferences` (GraphQL).
4. Build the post plan: combined embeds first, then standalone events.
5. Apply toggle filtering.
6. Send embeds to the target channel (ordered by item number / event time).
7. Mark all posted event keys as `seen`.

## Embed Appearance

- **No `@everyone`/`@here` ping.** `#github` is a maintainer working channel;
  embeds are posted with no mention.
- **Compact by design.** One tidy embed per event: a linked title
  (`#<number> <title>` → `html_url`), the author (small avatar as thumbnail),
  and the repo name. No large preview images and no multi-field walls of text,
  so posts inform without crowding out human discussion.

| Event | Color | Example title |
|---|---|---|
| Issue opened | green | 🟢 New issue #40 |
| Issue completed | purple | 🟣 Issue #40 closed as completed |
| Issue not planned | grey | ⚪ Issue #40 closed as not planned |
| PR opened | green | 🟢 New PR #42 |
| PR merged | purple | 🟣 PR #42 merged |
| PR closed (unmerged) | red | 🔴 PR #42 closed |
| PR merged + linked issue | purple | 🟣 PR #42 merged → closed #40 (issue title as sub-line/field) |

## Dry-Run Behavior

- `DRY_RUN_GITHUB: true` redirects all posts to `#bot-playground`
  (`CHANNELS.BOT_PLAYGROUND`) instead of `#github` — mirroring
  `DRY_RUN_YOUTUBE`.
- **Startup smoke-test post:** on boot in dry-run, the job posts the most recent
  issue and/or PR to `#bot-playground` as a rendering sanity check (analogous to
  the YouTube job posting the latest video on boot).

## Repository Standards Compliance

This section maps the design onto the repo's established conventions so the
implementation plan inherits them.

### Code organization

- The async client lives in **`lib/github.py`** (a module peer of
  `lib/youtube.py`). Fetch, state, event derivation, and linkage resolution all
  live in `GitHubMonitor` — the cog holds only orchestration + embed building.
- The loop lives in the existing **`Tasks` cog** (`lib/cogs/tasks.py`), which is
  auto-loaded from `lib/cogs/`. `main.py` is untouched (per "keep main.py
  minimal"). `DiscordBot` continues to be imported under the existing
  `if TYPE_CHECKING:` guard.

### Config singleton

- All new values live in `conf/config.yaml` and are accessed **only** via
  `from lib.config import config` — `config.CHANNELS.GITHUB`,
  `config.DRY_RUN_GITHUB`, `config.GITHUB.REPO`, `config.GITHUB.TOKEN`,
  `config.GITHUB.POLL_MINUTES`, `config.GITHUB.EVENTS.*`. No literals in code.
- Env overrides use the existing nested-underscore mechanism:
  `GITHUB_TOKEN`→`GITHUB.TOKEN`, `GITHUB_REPO`→`GITHUB.REPO`,
  `GITHUB_EVENTS_PR_MERGED`→`GITHUB.EVENTS.PR_MERGED`,
  `CHANNELS_GITHUB`→`CHANNELS.GITHUB`, `DRY_RUN_GITHUB`.
- **`sample.env`** gains a `GITHUB_TOKEN=` line.
- **Poll interval:** `discord.ext.tasks.loop` fixes its interval at decoration
  time, so the decorator uses a static default (`minutes=5`, matching the
  YouTube loop) and `before_monitor_github_activity` calls the loop's
  `change_interval(minutes=config.GITHUB.POLL_MINUTES)` so the configured value
  is honored without a literal in the loop body.

### DRY_RUN support

- `DRY_RUN_GITHUB` mirrors `DRY_RUN_YOUTUBE`: when true, posts are redirected to
  `CHANNELS.BOT_PLAYGROUND` and the startup smoke-test post fires; when false,
  posts go to `CHANNELS.GITHUB`. The feature keys off `DRY_RUN_GITHUB` (the
  YouTube redirect pattern), since the job has no destructive side effects to
  gate behind the global `config.DRY_RUN` — it only reads GitHub and posts to
  Discord.

### aiohttp session lifecycle

- `GitHubMonitor` owns an `aiohttp.ClientSession`, created in
  `before_monitor_github_activity` (which runs inside the event loop, after
  `wait_until_ready`) and closed in `cog_unload`. Requests send
  `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, and a
  `User-Agent`. Network/HTTP errors are caught and logged (as
  `YoutubeFeedParser` does around its fetches) so a transient GitHub outage
  skips a cycle rather than killing the loop.

### Unit testing (100% branch coverage)

- **`tests/test_github.py`** (peer of `test_youtube.py`): unit-test
  `GitHubMonitor` — event derivation, the two-gate new-event logic, toggle
  filtering, GraphQL linkage parsing, pagination, and error handling — mocking
  `aiohttp.ClientSession` responses for REST and GraphQL. Uses `pytest-asyncio`
  (auto mode) and `pytest-mock`.
- **Extend `tests/cogs/test_tasks.py`:** mock a `GitHubMonitor`, inject it as
  `tasks_cog.github_monitor`, and `await tasks_cog.monitor_github_activity()`
  directly — the same approach the existing tests use for
  `monitor_youtube_videos`. Cover: post to `#github`, dry-run redirect to
  `#bot-playground`, startup smoke post, each toggle on/off, combined vs.
  separate embeds, and the "already running" bootstrap branch.
- **conftest update (required):** the autouse `mock_config` fixture in
  `tests/conftest.py` hardcodes every config attribute and patches `config` per
  module namespace. It must gain: `mock_cfg.CHANNELS.GITHUB`,
  `mock_cfg.DRY_RUN_GITHUB`, `mock_cfg.GITHUB.REPO`, `mock_cfg.GITHUB.TOKEN`
  (`# noqa: S105`), `mock_cfg.GITHUB.POLL_MINUTES`, `mock_cfg.GITHUB.EVENTS.*`,
  and a `patch("lib.github.config", mock_cfg)` entry so the new module sees the
  mock.

### Linting / formatting (ruff `ALL`)

- Line length 88, double quotes, 4-space indent. Docstrings are optional (`D`
  ignored) but the module follows the existing class/method docstring style.
  `ruff format` and `ruff check` run clean before commit; watch the rules the
  repo already accommodates (`TRY300`, in-function-import `PLC0415` in tests,
  `UP043` on `Generator` fixture return types).

### Security (bandit)

- The token is read from env/config only and never logged. `tests/` is excluded
  from bandit; the test token literal carries `# noqa: S105`, as `BOT_TOKEN`
  does today.

### Typing (pyrefly strict)

- Full annotations on every function, method, and attribute. GitHub REST/GraphQL
  JSON is modeled with `TypedDict`s (and narrow parsing helpers) rather than raw
  `dict[str, Any]` where practical, so pyrefly can verify field access.
  `pyrefly check` runs clean before commit.

### Release & deploy

- Version bump `0.9.5` → `0.10.0` (semver minor, new feature) in
  `pyproject.toml`, with the matching image tag update
  (`v0.9.5` → `v0.10.0`) in `kubernetes/discordbot.yaml`.
- `kubernetes/discordbot.yaml` also gains a `GITHUB_TOKEN` env via
  `secretKeyRef` (mirroring `BOT_TOKEN`; the key is added to the `bot-secrets`
  Secret) and, optionally, a `DRY_RUN_GITHUB` plain env (mirroring the existing
  `DRY_RUN_YOUTUBE`).
- Confirm the installed `uv` version matches `.pre-commit-config.yaml` and
  `.github/workflows/check-test.yaml` before committing (per CLAUDE.md).

### Commit sequencing

Per CLAUDE.md, **each commit must independently pass all blocking checks**
(`invoke check`) and keep coverage at 100%. In particular, the `conftest.py`
mock-config additions and `conf/config.yaml` changes must land in the same
commit as (or before) any code/tests that depend on them, so no intermediate
commit references config keys the mock doesn't yet provide.

## Open Questions / Risks

- **GraphQL response shape drift** — `closingIssuesReferences` is stable, but
  tests should pin the exact query and mock its response.
- **Pagination edge** — a burst of activity could exceed one page; the poll
  follows pagination but caps the number of pages to avoid runaway loops (logged
  if the cap is hit).
- **Clock/timezone** — timestamp gating compares GitHub UTC timestamps against
  the bot's startup time; both normalized to UTC.
