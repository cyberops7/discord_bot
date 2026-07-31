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

Only **changes-requested** reviews notify by default. The design adds all four
review kinds as independently toggleable config keys, so approvals, plain
review comments, and dismissals can be switched on later with a config-only
change.

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
- Distinguish review states: changes-requested, approved, commented, dismissed —
  each a separate event kind.
- Each review kind is independently enable/disable-able via `GITHUB.EVENTS`,
  with only `PR_REVIEW_CHANGES_REQUESTED` defaulting to `true`.
- Never re-post a review already seen, and never burst old reviews after a
  restart.

## Non-goals

- Individual review *comments* (single inline comments) — only submitted reviews
  that carry a verdict/state.
- Review *requests* ("X was requested to review") — a different event.
- Reviews on closed/merged PRs — only reviews on PRs still in the `open` state.
- Webhook ingestion (`pull_request_review`) — polling only, matching the
  existing architecture; a webhook would need public ingress and secret
  validation the bot does not have.
- Persisting state across restarts (matches the existing in-memory model).
- Including the review body text in the embed.

## Architecture & Components

### Reuse: `GitHubMonitor` in `lib/github.py`

No new module. The review path threads through the existing poll:

1. `_fetch_updated_issues` already returns issues **and** PRs updated since
   `_last_checked`; a submitted review bumps its PR's `updated_at`, so reviewed
   PRs surface here for free.
2. Select the fetched items that are **open PRs** (`"pull_request" in item` and
   `state == "open"`).
3. Fetch recent reviews for those PRs (see Fetch mechanism).
4. Keep each review whose `submitted_at` is **after both** `_last_checked` and
   `_started_at`, whose `state` maps to a review kind, and whose kind is
   toggled on.
5. Emit one `GitHubActivityEvent` per surviving review, reusing the existing
   frozen dataclass — the reviewer populates `author_login` /
   `author_avatar_url` and `url` is the review's `html_url`.

The derived review events are appended to the same `plan` list
`get_new_events` already returns, so the cog posts them exactly like any other
event.

### New event kinds

Add to `EVENT_RENDER` in `lib/github.py`:

| Kind | Emoji | Color | Title verb |
|---|---|---|---|
| `PR_REVIEW_CHANGES_REQUESTED` | 🔴 | red (`0xE74C3C`) | "Changes requested on" |
| `PR_REVIEW_APPROVED` | 🟢 | green (`0x2ECC71`) | "Approved" |
| `PR_REVIEW_COMMENTED` | 💬 | grey (`0x95A5A6`) | "Reviewed" |
| `PR_REVIEW_DISMISSED` | ⚪ | grey (`0x95A5A6`) | "Review dismissed on" |

A `_PR_REVIEW_KINDS: frozenset[str]` groups them for gating/derivation,
mirroring `_PR_CLOSE_KINDS`.

GitHub review `state` → kind mapping:

- `CHANGES_REQUESTED` → `PR_REVIEW_CHANGES_REQUESTED`
- `APPROVED` → `PR_REVIEW_APPROVED`
- `COMMENTED` → `PR_REVIEW_COMMENTED`
- `DISMISSED` → `PR_REVIEW_DISMISSED`
- `PENDING` (an unsubmitted draft review) → ignored (no `submitted_at`).

### Fetch mechanism

**One aliased GraphQL query per poll**, mirroring the existing
`_resolve_issue_closers` batching. For the set of updated open-PR numbers, issue
a single query with `pr{n}: pullRequest(number:{n})` aliases, each selecting
`reviews(last:N){nodes{ ... }}` with the fields needed
(`databaseId`, `state`, `submittedAt`, `url`, `author{login avatarUrl}`). This
holds review resolution to one call per poll regardless of how many PRs were
touched, bounding secondary-rate-limit risk.

`N` (reviews fetched per PR) is bounded (e.g. 20); if a single PR somehow
receives more than `N` reviews within one poll interval, the oldest are
dropped — logged, consistent with the existing pagination-cap warning.

*Rejected alternative:* N REST calls to
`/repos/{repo}/pulls/{n}/reviews` — simpler per call but scales linearly with PR
count and diverges from the GraphQL batching already in the module.

### State model & restart safety

- The in-memory `_seen` set gains review keys of the form
  `review:{pr_number}:{review_databaseId}`. Review IDs are stable, so a review
  is never posted twice within a run.
- The `submitted_at > _started_at` gate prevents a burst of pre-existing reviews
  from being re-posted after a restart — the same guarantee the open/close
  events already rely on via their `created_at` / `closed_at` gates.
- The `submitted_at > _last_checked` gate keeps steady-state polls from
  re-surfacing reviews on a PR that was updated again for an unrelated reason.

### DRY-RUN startup preview

`get_latest_activity` (the single-item preview posted at startup when
`DRY_RUN_GITHUB` is on) stays issue/PR-only. Reviews are **not** added to that
path — it exists to sanity-check connectivity, and keeping it review-free avoids
an extra fetch there.

### Rendering

`_build_github_embed` in `lib/cogs/tasks.py` already keys the emoji/color/verb
off `EVENT_RENDER[event.kind]` and sets the embed author from the event's
`author_*` fields, so review events render with minimal change. The embed shows:
emoji + verb + `PR #<n>: <title>`, the reviewer as the embed author with avatar,
the title linking to the review `url`, and `GITHUB.REPO` in the footer. No body.

Any close-specific branch (the closer footer/line) must be scoped to
`CLOSE_KINDS` so review events don't accidentally pick it up.

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
    PR_REVIEW_DISMISSED: false
```

Touchpoints that must stay in lockstep with the new keys:

- `lib/config.pyi` — add the four keys to the `EVENTS` type surface.
- `tests/conftest.py` `mock_config` fixture — set all four
  `mock_cfg.GITHUB.EVENTS.PR_REVIEW_*` values.

## Error handling

- A failed GraphQL review fetch logs via `logger.exception` and returns no
  review events for that poll (the poll cursor still advances; the open/close
  events from the same poll are unaffected) — matching the existing
  `_resolve_*` failure behavior.
- GraphQL `errors` in the response are logged as a warning; whatever data came
  back is still parsed defensively (same pattern as
  `_resolve_pr_close_details`).
- A review node missing `submittedAt` (a `PENDING` draft) is skipped.

## Testing

New unit tests in `tests/` (100% branch coverage required), mirroring the
existing `_resolve_*` and `get_new_events` tests:

- Review `state` → kind mapping, including the ignored `PENDING` case.
- Toggle gating: a changes-requested review posts by default; approved/
  commented/dismissed are suppressed unless toggled on.
- The restart gate: a review with `submitted_at <= _started_at` is not posted.
- The `_last_checked` gate: a review already seen in a prior poll is not
  re-posted (via `_seen` and via timestamp).
- Open-PR scoping: a review on a closed/merged PR is ignored.
- GraphQL parse: well-formed response, `errors` present, malformed/empty nodes,
  request failure.
- Embed rendering for a review event (reviewer author, review `url`, no body,
  no closer line).

## Delivery

- Version bump in `pyproject.toml` and the matching image tag in
  `kubernetes/discordbot.yaml`, per project rules.
- Add/branch → PR against `main` (this repo's standard finish), green CI.
- Mark the `.claude/todo.md` item done once shipped.
