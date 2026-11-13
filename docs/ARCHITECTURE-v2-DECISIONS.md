# ARCHITECTURE-v2: answers to section 12

These answers were chosen by the orchestrator on 2026-11-13, with the owner's go-ahead ("use best judgement answers to the questions"). Where this file and `ARCHITECTURE-v2.md` disagree, this file wins.

| # | Question | Answer |
|---|---|---|
| 1 | Claude Code `cleanupPeriodDays` | Done: the owner set it to 3650. |
| 2 | Remove `save` and `supersede` | Yes. git and `mv` do these jobs. Add `ingest` and `ui`. |
| 3 | Redaction / a raw copy | No redaction anywhere by default: not in the store, not in agent reads, not in the UI or exports (decision `d-406f9482`). Ingest flags secret matches and keeps the text unchanged. The store is the raw copy. Optional masking when the reading agent's provider differs from the source session's may come later; it is off by default. |
| 4 | Joining a Paseo agent to its provider session | First check whether Paseo exposes the provider session id. If it does not, join on cwd plus a time window and record a `join_confidence` column. |
| 5 | 256 KB string cap | No cap in the raw store; tool outputs are kept whole. The cap applies only to the derived FTS index. |
| 6 | Does awt delete store data | Never automatically, and v2 has no delete verb. Deletion is done by hand. |
| 7 | Store location | Separate, at `~/.local/share/awt-store` (`AWT_STORE` overrides). Directory mode 700. `doctor` warns when it is in a synced folder or a git repo. |
| 8 | Can a person mark sent straight from planned | Yes. |
| 9 | PR #11 split | Don't split. Verify the `ar/review` fixes, merge them into `feat/active-recall`, and land PR #11 whole. R1/R2 keep their interface; their ranking moves to FTS5 in phase 2. |
| 10 | Paseo screen | Not now. `awt ui` (Datasette) comes first. |
| 11 | Embedding test budget | Local model only. No paid budget. |
| 12 | Level numbering | Project is L1; every level below it shifts down one. The numbers are only used in docs. |
| 13 | A detected resend | On Claude Code, the host asks (`PreToolUse` returns `ask`), but only for an exact duplicate of a send already marked sent or unknown. Every other case is only recorded. |
| 14 | Inferring decisions and questions | Deferred (phase 8, gated). If built: local model only, with accuracy measured before anything relies on it. |
| 15 | The handoff prompt line | Drop it and rely on the automatic handoff. `state` stays available as an optional verb. |
| 16 | Archiving projects | Yes: check `archivedAt` when a workspace is archived and on each migration run. |

Other standing decisions:
- `7b25143`, the `apply` branch in `~/src/awt-worktrees/awt-apply`, is not merged. Phase 0 replaces it.
- Every feature gets one PR. **Nothing merges to `main` without the owner's explicit go-ahead.** Plain pushes to feature branches are fine.
- Phases 8 (inferring decisions) and 9 (sqlite-vec) are gated and not built.
