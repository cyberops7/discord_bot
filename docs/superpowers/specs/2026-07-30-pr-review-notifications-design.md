# PR Review Notifications — Design

**Date:** 2026-07-30
**Status:** Approved (pending spec review)

## Summary

Extend the existing `GitHubMonitor` (`lib/github.py`) so its periodic poll also
detects **submitted pull-request reviews** on the watched repository
(`JamesTurland/JimsGarage`) and posts a compact embed to the `#github` channel.
The point is signal for contributors: when someone reviews a PR, the author and
other maintainers see it in Discord without watching GitHub.

The feature rides the existing 5-minute `monitor_github_activity` task — no new
task, no new channel, no inbound webhook. It reuses the same machinery the
issue/PR open/close events already use: an in-memory `seen` set baselined at
startup, per-event-kind config toggles under `GITHUB.EVENTS`, and compact
`EVENT_RENDER`-driven embeds.

Only **changes-requested** reviews notify by default. The design adds three
submitted-review kinds as independently toggleable config keys, so approvals and
plain review comments can be switched on later with a config-only change.
(Dismissals are out of scope — see Non-goals.)

### Channel context: a maintainer working channel

`#github` is a working channel for the repo's maintainers, not a notification
firehose. Noise minimization stays a first-class concern, consistent with the
existing monitor:

- **No `@everyone`/`@here` pings** — ever.
- **Per-kind toggles** are the primary noise control; default is
  changes-requested only.
- **Compact embeds** — one tidy embed per review (linked title, small reviewer
  avatar, repo footer). No review body text, no walls of fields.

## Goals

- Post to `#github` when a review is submitted on an **open** PR in the watched
  repo.
- Distinguish submitted review states: changes-requested, approved, commented —
  each a separate event kind.
- Each review kind is independently enable/disable-able via `GITHUB.EVENTS`,
  with only `PR_REVIEW_CHANGES_REQUESTED` defaulting to `true`.
- Never re-post a review already seen, and never burst old reviews after a
  restart.

## Non-goals

- Individual review *comments* (single inline comments) — only submitted reviews
  that carry a verdict/state. Note: a review finished with the "Comment" verdict
  produces a `COMMENTED` review (possibly with an empty body), so
  `PR_REVIEW_COMMENTED`, when enabled, fires on comment-only reviews too.
- Review *requests* ("X was requested to review") — a different event.
- **Review dismissals** — a dismissal does not re-submit the review (its
  `submittedAt` is unchanged) and is not exposed on the `reviews` connection; it
  is a separate `REVIEW_DISMISSED_EVENT` timeline item. Detecting it would need
  a distinct timeline query keyed on the dismissal's `createdAt`, so it is
  deferred as future work — there is no `PR_REVIEW_DISMISSED` kind in this
  design.
- Reviews on closed/merged PRs — only reviews on PRs still in the `open` state.
- Webhook ingestion (`pull_request_review`) — polling only, matching the
  existing architecture; a webhook would need public ingress and secret
  validation the bot does not have.
- Persisting state across restarts (matches the existing in-memory model). A
  review submitted while the bot is down (before `_started_at`, with `_seen`
  cleared) is missed — consistent with the existing open/close events.
- Including the review body text in the embed.

## Architecture & Components

### Reuse: `GitHubMonitor` in `lib/github.py`

No new module. The review path is a new **async** helper on `GitHubMonitor`
(call it `_derive_review_events`), invoked from `get_new_events` and threading
through the existing poll:

1. `_fetch_updated_issues` already returns issues **and** PRs updated since
   `_last_checked`. **Assumption (load-bearing, testable):** submitting a review
   bumps the PR's `updated_at`, so a reviewed open PR resurfaces in this
   `since`-filtered fetch. This is the same mechanism the open/close events rely
   on and is the sole way a review reaches the bot.
2. From the raw fetched items, select **open PRs** (`"pull_request" in item` and
   `item["state"] == "open"`). The PR `number` and `title` come from these REST
   items; the review fields come from GraphQL (step 3).
3. Fetch recent reviews for those PR numbers (see Fetch mechanism).
4. For each review node, in order: map `state` → kind (skip unrecognized states
   and `PENDING`); skip if that kind is not toggled on; skip if
   `submitted_at <= _started_at`; build the dedup key
   `review:{pr_number}:{databaseId}` and **skip if already in `_seen`**;
   otherwise **add the key to `_seen`** and emit an event.
5. Emit one `GitHubActivityEvent` per surviving review via a **dedicated
   constructor** (not `_make_event`, which reads REST `issue["user"]` /
   `issue["html_url"]`). Critically, the event's `.key` field itself is set to
   the composite `review:{pr_number}:{databaseId}` — the reviewer populates
   `author_login` / `author_avatar_url`, `url` is the review's `html_url`,
   `number`/`title` come from the REST item, and `is_pr=True`.

**Dedup rationale (why the review path manages `_seen` itself):** the existing
`get_new_events` dedups open/close events on the dataclass `.key` field
(`fresh = [e for e in derived if e.key not in self._seen]`, then
`self._seen.add(...)`), and `_make_event` hardcodes `key = f"{kind}:{number}"`.
Two same-kind reviews on one PR would collide under that scheme, and the review
helper runs **after** that `fresh` block, so it does its own `_seen`
membership-check-and-add (step 4). The composite key makes each review distinct.

The derived review events are appended to the same `plan` list
`get_new_events` already returns, so the cog posts them exactly like any other
event.

**Gating note:** reviews are gated on `submitted_at > _started_at` (plus the
`_seen` set) and deliberately **not** on `_last_checked`. `get_new_events`
reassigns `self._last_checked = poll_time` (captured at poll start) *before* the
plan is assembled, so a `submitted_at > _last_checked` gate read there would be
`submitted_at > poll_time` — false for every real review, silently posting
nothing. `_started_at` (stable) + `_seen` (composite key) together give both the
no-restart-burst and no-double-post guarantees without that trap.

### New event kinds

Add to `EVENT_RENDER` in `lib/github.py`:

| Kind | Emoji | Color | Title verb |
|---|---|---|---|
| `PR_REVIEW_CHANGES_REQUESTED` | 🟠 | orange (`0xE67E22`) | "Changes requested on" |
| `PR_REVIEW_APPROVED` | ✅ | green (`0x2ECC71`) | "Approved" |
| `PR_REVIEW_COMMENTED` | 💬 | grey (`0x95A5A6`) | "Reviewed" |

`PR_REVIEW_CHANGES_REQUESTED` uses orange (not `PR_CLOSED`'s red 🔴) and
`PR_REVIEW_APPROVED` uses ✅ (not `PR_OPENED`'s 🟢) so review posts are
distinguishable from open/close posts at a glance.

A `_PR_REVIEW_KINDS: frozenset[str]` groups them for gating/derivation,
mirroring `_PR_CLOSE_KINDS`.

GitHub review `state` → kind mapping:

- `CHANGES_REQUESTED` → `PR_REVIEW_CHANGES_REQUESTED`
- `APPROVED` → `PR_REVIEW_APPROVED`
- `COMMENTED` → `PR_REVIEW_COMMENTED`
- `PENDING` (an unsubmitted draft, no `submittedAt`) → ignored.
- `DISMISSED` or any unrecognized state → ignored (see Non-goals for
  dismissals).

### Fetch mechanism

**One aliased GraphQL query per poll**, mirroring the existing
`_resolve_issue_closers` batching. For the set of updated open-PR numbers, issue
a single query with `pr{n}: pullRequest(number:{n})` aliases, each selecting
`reviews(last:N){nodes{ ... }}` with the fields needed
(`databaseId`, `state`, `submittedAt`, `url`, `author{login avatarUrl}`). All
GraphQL fields are verified to exist on `PullRequestReview`. This holds review
resolution to one call per poll regardless of how many PRs were touched,
bounding secondary-rate-limit risk. Guard the call like `_resolve_issue_closers`
— return no reviews early when the open-PR set is empty, or the token/session is
absent.

Parse defensively (mirroring `_closer_from_actor`): a review `author` can be
`null` (deleted/ghosted account) — fall back to empty login/avatar rather than
indexing; skip any node missing `databaseId` or `submittedAt`.

`N` (reviews fetched per PR) is bounded (e.g. 20); if a single PR somehow
receives more than `N` reviews within one poll interval, the oldest are dropped.
Log that drop, consistent with the existing pagination-cap warning. (Optionally
narrow with the `reviews(states: [...])` argument to fetch only toggled-on
states.)

*Rejected alternative:* N REST calls to
`/repos/{repo}/pulls/{n}/reviews` — simpler per call but scales linearly with PR
count and diverges from the GraphQL batching already in the module.

### State model & restart safety

- The in-memory `_seen` set gains review keys of the form
  `review:{pr_number}:{databaseId}`. `databaseId` is the stable REST integer id
  (distinct from the opaque GraphQL node `id`), so a review is never posted
  twice within a run.
- The `submitted_at > _started_at` gate prevents a burst of pre-existing reviews
  from being re-posted after a restart — the same guarantee the open/close
  events already rely on via their `created_at` / `closed_at` gates.
- Reviews are **not** gated on `_last_checked` (see the Gating note above for
  why that would drop every review); `_seen` covers the "PR resurfaced for an
  unrelated reason" case.
- **Pagination-cap limitation (shared with the open/close path):**
  `_fetch_updated_issues` caps at `max_pages × per_page` (500 items) and
  advances `_last_checked` regardless. If a reviewed PR falls past that cap in a
  single burst poll, its review is lost, not merely delayed. Low-probability for
  this repo; documented as an accepted limitation, not fixed here.

### DRY-RUN startup preview

`get_latest_activity` (the single-item preview posted at startup when
`DRY_RUN_GITHUB` is on) stays issue/PR-only. Reviews are **not** added to that
path — it exists to sanity-check connectivity, and keeping it review-free avoids
an extra fetch there.

### Rendering

`_build_github_embed` in `lib/cogs/tasks.py` already keys the emoji/color/verb
off `EVENT_RENDER[event.kind]` and sets the embed author from the event's
`author_*` fields, so review events render with **no change** to that method.
The existing format is preserved: the embed **title** is `{emoji} {verb}
#{number}` (e.g. "🟠 Changes requested on #42"), the linked PR title sits in the
**description** (linking to the event `url`, which for reviews is the review's
`html_url`), the reviewer is the embed author with avatar, and `GITHUB.REPO` is
the footer. No review body.

The closer-specific branch is already gated on `event.kind in CLOSE_KINDS`, and
review kinds are not in `CLOSE_KINDS`, so it is cleanly skipped;
`event.linked_issues` defaults to `()` so that block is skipped too. `is_pr` is
otherwise unused by the embed, so `is_pr=True` on review events is safe.

## Configuration

`conf/config.yaml` — add under `GITHUB.EVENTS` (keys kept alphabetical):

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

Touchpoints that must stay in lockstep with the new keys:

- `tests/conftest.py` `mock_config` fixture — set all three
  `mock_cfg.GITHUB.EVENTS.PR_REVIEW_*` values, and explicitly set the two
  default-off ones (`_APPROVED`, `_COMMENTED`) to `False`: `_toggle_on` does
  `bool(getattr(...))`, and an unset `MagicMock` attribute is truthy, so
  omitting them would make suppression tests false-pass.
- **No** `lib/config.pyi` change and **no** new `mock_config` patch-list entry:
  `GITHUB.EVENTS` keys resolve dynamically through `ConfigDict.__getattr__ ->
  Any` (the existing six keys aren't declared in the stub either), and the
  review path adds no new config-reading module — `lib.github` and
  `lib.cogs.tasks` are already patched.

## Error handling

- A failed GraphQL review fetch logs via `logger.exception` and returns no
  review events for that poll (the poll cursor still advances; the open/close
  events from the same poll are unaffected) — matching the existing
  `_resolve_*` failure behavior.
- GraphQL `errors` in the response are logged as a warning; whatever data came
  back is still parsed defensively (same pattern as
  `_resolve_pr_close_details`).
- A review node missing `submittedAt` (a `PENDING` draft) or `databaseId` is
  skipped; a `null` `author` falls back to empty login/avatar.
- Empty open-PR set, or missing token/session → the helper returns no reviews
  without issuing a request.

## Testing

New unit tests in `tests/` (100% branch coverage required), mirroring the
existing `_resolve_*` and `get_new_events` tests:

- Review `state` → kind mapping for each recognized state, plus the ignored
  `PENDING`, an unrecognized/unknown state, and `DISMISSED` (all ignored).
- Toggle gating: a changes-requested review posts by default; approved and
  commented are suppressed unless toggled on (with the off-keys set to explicit
  `False` in the fixture).
- The restart gate: a review with `submitted_at <= _started_at` is not posted.
- The `_seen` dedup: a review posted in a prior poll is not re-posted when its
  PR resurfaces; two same-kind reviews on one PR both post (distinct composite
  keys, no collision).
- Open-PR scoping: a review on a closed/merged PR is ignored; a non-PR updated
  issue is ignored (the `"pull_request" in item` False branch).
- Short-circuit guards: empty open-PR set and missing token/session return no
  reviews without a request.
- The `> N` reviews-per-PR cap branch (oldest dropped + logged).
- Defensive parse: `null` author, node missing `databaseId`/`submittedAt`.
- GraphQL parse: well-formed response, `errors` present, malformed/empty nodes,
  request failure.
- Embed rendering for a review event (reviewer author, review `url`, no body,
  no closer line; `{emoji} {verb} #{number}` title + linked description).

## Delivery

- Version bump in `pyproject.toml` and the matching image tag in
  `kubernetes/discordbot.yaml`, per project rules.
- Add/branch → PR against `main` (this repo's standard finish), green CI.
- Mark the `.claude/todo.md` item done once shipped.
