# ADR 0006: verb swap, `ingest` and `ui` for `save` and `supersede`

Status: decided by the owner (ARCHITECTURE-v2-DECISIONS, decision 2); implemented in phase 5.

## Context

SPEC rule 8: at most 16 top-level verbs; a new verb means removing one. v2 adds `ingest` (phase 1) and `ui` (phase 5). `save` was removed in phase 1.

## Decision

- Remove `supersede`. Host-native replacement: `mkdir -p docs/_superseded && mv -n docs/old.md docs/_superseded/ && test ! -e docs/old.md` (creates the folder on first use and never replaces an earlier superseded doc: a name already taken stays put and the last test fails) plus `awt note "docs/new.md replaces docs/old.md: why"`. Listing still hides `docs/_superseded/`; old `doc` rows still read.
- `save` stays removed: `git commit` under host permissions, with `awt doctor --staged` as the secret check.
- `decide --supersedes ID` is a flag and stays.
- Both removed verbs print a `fix:` line with the replacement and exit 2, so an agent that remembers them is told once.
- The cap is 16 again (a test checks it).

## Consequences

- A superseded doc leaves no `doc` event; the `note` carries the reason. The loss is small: the move is visible in git.
- Prompts and templates no longer mention `supersede`.
