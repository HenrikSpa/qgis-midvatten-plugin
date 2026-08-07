> Source: distilled from Claude session transcripts, 2026-08-07. Background context, not a living spec.

# Midvatten — intent recovered from session transcripts

Durable goals, priorities, and constraints Henrik stated in working sessions that
are not captured in `CLAUDE.md` or the other `docs/` notes. Each item cites the
session turn it came from so it can be traced back.

## Why the `ai_test` refactor exists — and the priorities it serves

- The `ai_test` branch (diverged from `master`) is a heavy refactor whose whole
  point is three qualities, in this order of concern: **security** (no SQL
  injection), **maintainability**, and **UX** (clearer error messages, fewer
  quirks, faster). When weighing any change or "simplification" before release,
  judge it against those three — not against line count. [ff67cefa#1]
- **The large growth in lines of code is an accepted, deliberate cost, not a
  regression to undo.** Two causes are sanctioned: switching from long lines to
  black/ruff line-length style, and writing more verbose code that covers more
  edge cases. The old code was built for specific cases and raised errors when
  used other ways; the new code trades brevity for correctness across those
  cases. Do not "shrink" the codebase by re-narrowing it back to the happy path.
  [ff67cefa#1]
- The database layer is the archetype of this trade: the old version was short
  but crammed many operations into functions steered by `if`-statements — a quick
  read for a human, but fragile. The refactor makes it longer while making each
  part individually simpler. Longer-but-each-part-easier is the intended shape
  here; keep it. [ff67cefa#1]

## Release feel: familiar, then polished

- The target for the new release is that it **feels familiar to existing plugin
  users** — someone who has used Midvatten before should find the changes
  self-explanatory — while feeling more **polished**, meaning everything behaves
  the way the user expects. Familiarity first, polish on top; avoid redesigns
  that force existing users to relearn workflows. [ff67cefa#2]
- On a cancelled operation, prefer showing **nothing** over showing a partial
  result or a "partial report" notice — e.g. cancelling a report should produce
  no report and no partial-report message at all, rather than a confusing
  half-output. [f72067dd#2]

## Qt5 and Qt6 must both work — right now

- The plugin **must run on both Qt5 and Qt6 at the same time**; this is a live
  constraint, not a future goal. Do not introduce Qt6-only or Qt5-only code paths
  without a compatibility shim. [ff67cefa#2]
- When removing a Qt5-specific path (e.g. a Qt5-only backend force), explicitly
  check whether any capability is lost in the Qt6 configuration before dropping
  it — Henrik watches for silent capability loss during Qt version consolidation.
  [ff67cefa#8]
