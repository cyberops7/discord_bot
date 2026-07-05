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

A small frozen result type carries both pieces back to the caller:

```python
@dataclass(frozen=True)
class _PRCloseDetails:
    linked_issue_numbers: tuple[int, ...]
    closer_login: str
    closer_avatar_url: str
```

### Standalone issue closes — new per-issue GraphQL query

An issue closed directly (not swept under a PR merge) is not queried via GraphQL
today. Its closer lives on a separate node (`issue(number:…)`), so it needs one
new GraphQL call per standalone issue-close event:

```graphql
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    issue(number:$number){
      timelineItems(itemTypes:[CLOSED_EVENT],last:1){
        nodes{... on ClosedEvent{actor{login avatarUrl}}}
      }
    }
  }
}
```

Issues rolled up under a PR merge (in `combined_numbers`) are **not** posted as
standalone embeds and need no closer lookup.

## Integration points

- **`get_new_events`** — PR close events already call the PR resolver; use the
  extended result to `replace(event, linked_issues=…, closer_login=…,
  closer_avatar_url=…)`. Standalone issue-close events (second loop) call the
  new issue resolver and `replace(...)` the closer fields.
- **`get_latest_activity`** — the dry-run smoke test uses the same
  `_build_github_embed`. For close events it resolves the closer (PR or issue
  path) so the smoke test matches production rendering. Factor closer resolution
  into a shared helper so both entry points stay DRY.
- **`_build_github_embed`** — branch on whether the kind is a close kind
  (`_ISSUE_CLOSE_KINDS | _PR_CLOSE_KINDS`):
   - close: `set_author(name=f"{opener} → {closer or 'unknown'}")`, thumbnail =
     `closer_avatar_url or author_avatar_url`.
   - open: unchanged (`opener`, opener avatar).

## Testing

100% branch coverage is required. Add/extend tests for:

- **GraphQL parsing** — PR merged (`mergedBy`), PR closed-not-merged
  (`CLOSED_EVENT` actor), standalone issue close, and `null`/missing actor →
  empty closer.
- **No token / no session** → empty closer.
- **`_build_github_embed`** — open event (unchanged author + thumbnail), PR
  merge (`opener → closer` + closer avatar), self-close
  (`cyberops7 → cyberops7`), and unknown closer (`opener → unknown` + opener
  avatar fallback).

## Versioning & deployment

- Bump the version in `pyproject.toml` (minor: additive feature).
- Update the matching image tag in `kubernetes/discordbot.yaml`.
- Sync uv pins if the installed uv version differs (per project convention).

## Files touched

- `lib/github.py` — dataclass fields, extended PR GraphQL query + refactor, new
  issue closer query, shared closer-resolution helper, `get_new_events` /
  `get_latest_activity` wiring.
- `lib/cogs/tasks.py` — `_build_github_embed` dual-attribution rendering.
- `tests/` — new/updated coverage per above.
- `pyproject.toml`, `kubernetes/discordbot.yaml` — version + image tag.
