# Decisions

Append-only. One numbered entry per decision.

## D2: Use one repo per deliverable
2030-01-02 · status: accepted · supersedes: none
Context: two deliverables with different release cadences.
Choice: separate repos.
Why: independent releases.

## D1: Keep a single changelog
2030-01-02 · status: accepted · supersedes: none
Context: release notes were scattered.
Choice: one changelog at the project level.
Why: one place to read.

## D3: Cache computed results per user and key
2030-01-03 · status: accepted · supersedes: none
Context: repeated lookups were slow.
Choice: cache keyed by user and key.
Why: latency.

## D4: Order of merges
2030-01-04 · status: accepted · supersedes: none
Choice: merge the core change first.

## D4: Order of merges (revised)
2030-01-05 · status: accepted · supersedes: none
Choice: merge the docs change first. This re-uses the heading D4 instead of adding an entry.

## D6: Drop the per-user cache
2030-01-06 · status: accepted · supersedes: none
Context: D3 turned out to leak across users.
Choice: remove the cache. This overturns D3.
Why: correctness over latency.
