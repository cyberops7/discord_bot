# GitHub Closer Attribution — Design

**Date:** 2026-07-05
**Status:** Approved (pending spec review)

## Summary

The GitHub issue/PR monitor (`lib/github.py` +
`monitor_github_activity` in `lib/cogs/tasks.py`) posts a compact embed when
issues/PRs are opened or closed. Each embed currently attributes only the
**opener** (author line + avatar thumbnail). This enhancement adds the
**closer** — the person who merged/closed the issue or PR — to the same embed
**without adding any new lines**.

On close events the author line becomes a handoff:
`opener → closer` (e.g. `DefNotJeffrey → cyberops7`), and the thumbnail shows
the **closer's** avatar, because they took the action this post is about. Open
events are unchanged (`opener`, opener avatar).

## Goals

- Show who took the closing action on `ISSUE_COMPLETED`, `ISSUE_NOT_PLANNED`,
  `PR_MERGED`, and `PR_CLOSED` events.
- Give the opener and closer **equal visual weight** — both names sit in the
  same prominent author-line slot, same styling.
- Add **zero new lines** to the embed (author line and thumbnail are
  repurposed; footer and fields are untouched).
- Preserve today's behavior exactly for open events.

## Non-Goals

- No closer attribution for issues rolled up under a PR merge's "Closed issues"
  field — those remain plain `• #123 title` list entries.
- No new embed lines, fields, or footer changes.
- No change to event derivation, gating, toggles, or the linked-issue combining
  logic.

## Presentation

Discord embed anatomy (from the live `PR merged #169` example):

| Slot | Today | After |
| --- | --- | --- |
| Author line | opener login | open: `opener` · close: `opener → closer` |
| Thumbnail | opener avatar | open: opener avatar · close: closer avatar |
| Title | `🟣 PR merged #169` | unchanged |
| Description | bold linked title | unchanged |
| Field | optional "Closed issues" | unchanged |
| Footer | repo name | unchanged |

**Rendering rule:** the thumbnail always shows the **actor of this event** —
opener for opens, closer for closes. In `opener → closer`, the closer is the
rightmost name and the thumbnail sits top-right, so the avatar visually aligns
with the person it represents.

### Edge cases

- **Self-close** (opener == closer): render the arrow consistently, e.g.
  `cyberops7 → cyberops7`. The arrow is *always* shown on close events; it makes
  self-actions explicit.
- **Closer unresolved** (API error, missing/`null` actor, or no token): render
  `opener → unknown` and fall back to the **opener's** avatar for the thumbnail.
  The post still goes out.
- **Bot / GitHub App closer** (e.g. `github-actions[bot]`, `dependabot[bot]`):
  render the login **as-is**, including the `[bot]` suffix, with the app's
  avatar. No stripping or annotation — the suffix is self-explanatory and honest
  about who acted.
- **Deleted opener** (`author_login == ""`): render `unknown` on the left side
  too, so a close never renders a bare ` → closer`.

## Data model

Add two fields to the `GitHubActivityEvent` frozen dataclass, defaulting to
empty and populated only for close events:

```python
closer_login: str = ""
closer_avatar_url: str = ""
```

`author_login` / `author_avatar_url` continue to mean the **opener**.

## Sourcing the closer

The closer is not present in the REST `/issues` list, so it is fetched via
GitHub's **GraphQL API** (the monitor already uses GraphQL for linked-issue
resolution). Both paths below tolerate a missing token / session by returning an
empty closer, which renders as `unknown` per the edge-case rule.

### GraphQL error handling (applies to every query below)

GitHub's GraphQL API returns **HTTP 200 even on partial failure** — rate
limiting (`errors[].type == "RATE_LIMITED"`), missing scope (`FORBIDDEN`), or a
deleted node (`NOT_FOUND`) come back as a 200 body with an `errors` array and
the failed node set to `null`. The existing `_resolve_linked_issues` only calls
`raise_for_status()` then digs into `data`, so a *failed* lookup is
indistinguishable from a legitimately-absent actor. Since closer resolution now
runs on far more events than linkage did, each query (extended PR query, issue
batch query, and the inherited linkage path) must **inspect `data.get("errors")`
and log at `warning`** before reading `data`. A query failure still degrades to
`unknown` per the edge-case rule — but it is logged, not silently swallowed.

### Pull requests — piggyback on the existing PR query

`_resolve_linked_issues(pr_number)` already runs a GraphQL query for **every**
PR close event. Extend that single query to also return the closer, so PRs cost
**zero new API calls**. The method is renamed/refactored to return both the
linked issue numbers and the closer.

```graphql
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      mergedBy{login avatarUrl}
      closingIssuesReferences(first:20){nodes{number}}
      timelineItems(itemTypes:[CLOSED_EVENT],last:1){
        nodes{... on ClosedEvent{actor{login avatarUrl}}}
      }
    }
  }
}
```

Closer selection by event kind:

- `PR_MERGED` → `mergedBy` (`mergedBy` is `null` for non-merge closes).
- `PR_CLOSED` → the last `CLOSED_EVENT` actor from `timelineItems`.

> **Note:** a merge emits *both* a `MergedEvent` and a `ClosedEvent`, so
> `timelineItems` returns a node on merged PRs too. `PR_MERGED` **intentionally
> ignores** that node and uses `mergedBy`, which is reliably populated for
> merges (the merge's `ClosedEvent.actor` can be `null` in edge cases). Do not
> "simplify" the two PR paths into one.

A small frozen result type carries both pieces back to the caller:

```python
@dataclass(frozen=True)
class _PRCloseDetails:
    linked_issue_numbers: tuple[int, ...]
    closer_login: str
    closer_avatar_url: str
```

### Standalone issue closes — one batched GraphQL query per poll

An issue closed directly (not swept under a PR merge) is not queried via GraphQL
today. Its closer lives on a separate node (`issue(number:…)`). Rather than fire
one call per issue — which, on a mass-close (a stale-issue sweep, a milestone
cleanup, a bot closing many at once), could mean dozens-to-hundreds of serial
calls in a single poll and risk GitHub's **secondary rate limits** — resolve all
standalone issue closers for a poll in **one batched query** using field
aliases:

```graphql
query($owner:String!,$name:String!){
  repository(owner:$owner,name:$name){
    i0: issue(number:1){ timelineItems(itemTypes:[CLOSED_EVENT],last:1){
      nodes{... on ClosedEvent{actor{login avatarUrl}}}}}
    i1: issue(number:2){ timelineItems(itemTypes:[CLOSED_EVENT],last:1){
      nodes{... on ClosedEvent{actor{login avatarUrl}}}}}
    # … one aliased field per standalone issue-close in this poll
  }
}
```

The query is built dynamically from the poll's standalone issue-close numbers;
results are read back by alias into a `{number: (login, avatar_url)}` map. This
holds closer resolution to **one issue call per poll** regardless of how many
issues closed. (`closingIssuesReferences(first:20)` on the PR query already caps
linked issues at 20, so a poll's standalone-issue count stays bounded in
practice.)

Issues rolled up under a PR merge (in `combined_numbers`) are **not** posted as
standalone embeds and need no closer lookup.

## Integration points

- **`get_new_events`** — PR close events already call the PR resolver; use the
  extended result to `replace(event, linked_issues=…, closer_login=…,
  closer_avatar_url=…)`. Collect the poll's standalone issue-close numbers,
  resolve them all in the single batched issue query, then `replace(...)` the
  closer fields on each from the alias map.
- **`get_latest_activity`** — the dry-run smoke test uses the same
  `_build_github_embed`. For close events it resolves the closer (PR or issue
  path) so the smoke test matches production rendering. Factor closer resolution
  into a shared helper so both entry points stay DRY.
- **`_build_github_embed`** — branch on whether the kind is a close kind
  (`_ISSUE_CLOSE_KINDS | _PR_CLOSE_KINDS`):
   - close: `set_author(name=f"{opener or 'unknown'} → {closer or 'unknown'}")`,
     thumbnail = `closer_avatar_url or author_avatar_url`.
   - open: unchanged (`opener`, opener avatar).

## Testing

100% branch coverage is required. Add/extend tests for:

- **GraphQL parsing** — PR merged (`mergedBy`), PR closed-not-merged
  (`CLOSED_EVENT` actor), standalone issue close, `actor: null`, and
  `nodes: []` (no `CLOSED_EVENT` — e.g. only a `MergedEvent` present) → empty
  closer.
- **GraphQL `errors[]`** — a 200 body carrying an `errors` array logs a warning
  and degrades the affected closer to empty (not silently swallowed).
- **Batched issue query** — multiple standalone issue closes resolve from one
  aliased query and map back to the correct numbers.
- **Reopen → reclose fixture** — `timelineItems(last:1)` returns the *most
  recent* closer (locks in `last:1`, guards against a regression to `first:1`).
- **`state_reason` mapping** — `completed`, `not_planned`, `duplicate`, and
  `null` classify as expected (pins the mapping so a new value can't silently
  land in "completed").
- **No token / no session** → empty closer.
- **`_build_github_embed`** — open event (unchanged author + thumbnail), PR
  merge (`opener → closer` + closer avatar), self-close
  (`cyberops7 → cyberops7`), unknown closer (`opener → unknown` + opener avatar
  fallback), bot closer (`[bot]` login rendered as-is), and deleted opener
  (`unknown → closer`).

## Versioning & deployment

- Bump the version in `pyproject.toml` (minor: additive feature).
- Update the matching image tag in `kubernetes/discordbot.yaml`.
- Sync uv pins if the installed uv version differs (per project convention).

## Files touched

- `lib/github.py` — dataclass fields, extended PR GraphQL query + refactor,
  batched issue-closer query, GraphQL `errors[]` inspection/logging, shared
  closer-resolution helper, `get_new_events` / `get_latest_activity` wiring.
- `lib/cogs/tasks.py` — `_build_github_embed` dual-attribution rendering.
- `tests/` — new/updated coverage per above.
- `pyproject.toml`, `kubernetes/discordbot.yaml` — version + image tag.
